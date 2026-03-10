import logging
from datetime import timedelta

from celery import shared_task
from django.conf import settings as django_settings
from django.utils import timezone

from .ai import personalize_email
from .gmail_service import check_for_replies, send_gmail
from .models import CampaignLead, SequenceStep

logger = logging.getLogger(__name__)

def _get_campaign_steps(campaign):
    """
    Returns ordered steps for a campaign.
    Querying fresh steps avoids stale in-memory references after
    campaign saves that delete and recreate sequence steps.
    """
    return list(
        SequenceStep.objects.filter(
            campaign=campaign
        ).order_by("step_order")
    )

def _get_campaign_raw_steps(campaign):
    settings = campaign.settings if isinstance(campaign.settings, dict) else {}
    raw_steps = settings.get('steps')
    return raw_steps if isinstance(raw_steps, list) else []


def _coerce_int(value):
    try:
        if value is None or value == '':
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _get_step_metadata(raw_steps, step_order):
    index = step_order - 1
    if index < 0 or index >= len(raw_steps):
        return {}

    raw_step = raw_steps[index]
    if not isinstance(raw_step, dict):
        return {}

    condition_branch = str(raw_step.get('condition_branch') or '').strip().lower()
    if condition_branch not in {'yes', 'no'}:
        condition_branch = None

    return {
        'channel_type': str(raw_step.get('type') or raw_step.get('channel_type') or '').strip().upper(),
        'condition_branch': condition_branch,
        'condition_parent_index': _coerce_int(raw_step.get('condition_parent_index')),
    }


def _find_branch_step_order(raw_steps, condition_step_order, branch):
    target_branch = str(branch or '').strip().lower()
    if target_branch not in {'yes', 'no'}:
        return None

    condition_index = condition_step_order - 1
    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            continue
        parent_index = _coerce_int(raw_step.get('condition_parent_index'))
        branch_value = str(raw_step.get('condition_branch') or '').strip().lower()
        if parent_index == condition_index and branch_value == target_branch:
            return index + 1

    return None


def _campaign_has_condition_reply_yes_branch(campaign):
    raw_steps = _get_campaign_raw_steps(campaign)
    for index in range(len(raw_steps)):
        step_meta = _get_step_metadata(raw_steps, index + 1)
        if step_meta.get('channel_type') != 'CONDITION_REPLY':
            continue
        if _find_branch_step_order(raw_steps, index + 1, 'yes'):
            return True
    return False


def _activate_step(clead, step, now=None):
    now = now or timezone.now()
    clead.current_step = step
    clead.next_execution_time = now + timedelta(minutes=max(step.delay_minutes, 0))
    clead.status = 'ACTIVE'
    clead.save(update_fields=['current_step', 'next_execution_time', 'status'])


def _maybe_mark_campaign_completed(campaign):
    if campaign.status == 'COMPLETED':
        return

    if not campaign.enrolled_leads.exists():
        return

    terminal_statuses = ['FINISHED', 'REPLIED', 'BOUNCED']
    has_unfinished = campaign.enrolled_leads.exclude(status__in=terminal_statuses).exists()
    if has_unfinished:
        return

    campaign.status = 'COMPLETED'
    campaign.save(update_fields=['status'])
    logger.info(f"Campaign marked COMPLETED: {campaign.id}")


def _advance_to_next_step(clead, completed_step, now=None):
    now = now or timezone.now()
    raw_steps = _get_campaign_raw_steps(clead.campaign)
    completed_meta = _get_step_metadata(raw_steps, completed_step.step_order)
    completed_branch = completed_meta.get('condition_branch')
    completed_parent_index = completed_meta.get('condition_parent_index')

    next_step = None
    steps = _get_campaign_steps(clead.campaign)

    for candidate in steps:
        if candidate.step_order <= completed_step.step_order:
            continue
        if completed_branch and completed_parent_index is not None:
            candidate_meta = _get_step_metadata(raw_steps, candidate.step_order)
            if (
                candidate_meta.get('condition_parent_index') == completed_parent_index
                and candidate_meta.get('condition_branch')
                and candidate_meta.get('condition_branch') != completed_branch
            ):
                continue
        next_step = candidate
        break

    if next_step:
        _activate_step(clead, next_step, now=now)
        return

    clead.current_step = None
    clead.next_execution_time = None
    clead.status = 'FINISHED'
    clead.save(update_fields=['current_step', 'next_execution_time', 'status'])
    _maybe_mark_campaign_completed(clead.campaign)


def _execute_non_email_step(clead, step, now=None):
    if step.channel_type == 'CONDITION_REPLY':
        _execute_condition_reply_step(clead, step, now=now)
        return
    if step.channel_type == 'CONDITION_OPEN':
        _execute_condition_open_step(clead, step, now=now)
        return
    if step.channel_type == 'CONDITION_CLICK':
        _execute_condition_click_step(clead, step, now=now)
        return
    logger.info(f"Auto-advancing non-email step {step.channel_type} for {clead.lead.email}")
    _advance_to_next_step(clead, step, now=now)


def _detect_reply_for_campaign_lead(clead):
    if clead.last_replied_at:
        return True
    if clead.status == "REPLIED":
        return True

    if not clead.last_sent_message_id:
        return False

    account = clead.campaign.connected_account
    if not account:
        return False

    try:
        replies = check_for_replies(account, [clead.last_sent_message_id])
    except Exception as err:
        logger.warning(f"Reply lookup failed for {clead.lead.email}: {err}")
        return False

    return clead.last_sent_message_id in replies


def _execute_condition_event_step(clead, step, event_detected, now=None):
    now = now or timezone.now()
    raw_steps = _get_campaign_raw_steps(clead.campaign)
    yes_branch_step_order = _find_branch_step_order(raw_steps, step.step_order, 'yes')
    no_branch_step_order = _find_branch_step_order(raw_steps, step.step_order, 'no')

    if event_detected:
        if yes_branch_step_order and yes_branch_step_order > step.step_order:
            steps = _get_campaign_steps(clead.campaign)
            yes_step = next((s for s in steps if s.step_order == yes_branch_step_order), None)
            if yes_step:
                _activate_step(clead, yes_step, now=now)
                return
        _advance_to_next_step(clead, step, now=now)
        return

    if no_branch_step_order and no_branch_step_order > step.step_order:
        steps = _get_campaign_steps(clead.campaign)
        no_step = next((s for s in steps if s.step_order == no_branch_step_order), None)
        if no_step:
            _activate_step(clead, no_step, now=now)
            return
    # If there is no explicit "no" branch, end the sequence for this lead.
    clead.current_step = None
    clead.next_execution_time = None
    clead.status = 'FINISHED'
    clead.save(update_fields=['current_step', 'next_execution_time', 'status'])
    _maybe_mark_campaign_completed(clead.campaign)
    return


def _execute_condition_open_step(clead, step, now=None):
    event_detected = clead.last_opened_at is not None
    _execute_condition_event_step(clead, step, event_detected, now=now)


def _execute_condition_click_step(clead, step, now=None):
    event_detected = clead.last_clicked_at is not None
    _execute_condition_event_step(clead, step, event_detected, now=now)


def _execute_condition_reply_step(clead, step, now=None):
    """
    CONDITION_REPLY behavior:
    - If a reply to the last sent email is detected, mark lead as REPLIED and stop sequence.
    - Otherwise, continue to the next step (no-reply path).
    """
    now = now or timezone.now()
    raw_steps = _get_campaign_raw_steps(clead.campaign)
    yes_branch_step_order = _find_branch_step_order(raw_steps, step.step_order, 'yes')
    no_branch_step_order = _find_branch_step_order(raw_steps, step.step_order, 'no')

    has_reply = _detect_reply_for_campaign_lead(clead)
    if has_reply and not clead.last_replied_at:
        clead.last_replied_at = now
        clead.save(update_fields=['last_replied_at'])

    logger.info(
        f"Reply condition evaluated for {clead.lead.email} | status={clead.status} | result={has_reply}"
    )

    if has_reply:
        if yes_branch_step_order and yes_branch_step_order > step.step_order:
            steps = _get_campaign_steps(clead.campaign)
            yes_step = next((s for s in steps if s.step_order == yes_branch_step_order), None)
            
            if yes_step:
                _activate_step(clead, yes_step, now=now)
                logger.info(
                    f"Reply condition matched for {clead.lead.email}; "
                    f"routing to Yes branch step {yes_step.step_order}."
                )
                return

        clead.status = "REPLIED"
        clead.current_step = None
        clead.next_execution_time = None
        clead.save(update_fields=['status', 'current_step', 'next_execution_time'])
        logger.info(f"Reply condition matched for {clead.lead.email}; sequence stopped.")
        _maybe_mark_campaign_completed(clead.campaign)
        return

    # Respect the configured condition window (step.delay_minutes).
    # Before the window expires, keep waiting on this step.
    if clead.next_execution_time and clead.next_execution_time > now:
        logger.info(
            f"Reply condition still waiting for {clead.lead.email}; "
            f"next check at {clead.next_execution_time}."
        )
        return

    # Condition window expired — route to "no" branch or finish.
    logger.info(f"Reply window expired for {clead.lead.email}")
    if no_branch_step_order and no_branch_step_order > step.step_order:
        steps = _get_campaign_steps(clead.campaign)
        no_step = next((s for s in steps if s.step_order == no_branch_step_order), None)
        
        if no_step:
            _activate_step(clead, no_step, now=now)
            logger.info(
                f"Reply condition not met for {clead.lead.email}; "
                f"routing to No branch step {no_step.step_order}."
            )
            return
    clead.current_step = None
    clead.next_execution_time = None
    clead.status = 'FINISHED'
    clead.save(update_fields=['current_step', 'next_execution_time', 'status'])
    _maybe_mark_campaign_completed(clead.campaign)
    return


@shared_task
def send_email_step(campaign_lead_id, step_id):
    """
    Dispatches an email through the connected Gmail account (or falls back to mock logging).
    """
    try:
        clead = CampaignLead.objects.select_related('lead', 'campaign').get(id=campaign_lead_id)
        step = SequenceStep.objects.get(id=step_id)

        if step.channel_type != 'EMAIL':
            _execute_non_email_step(clead, step)
            return

        # Atomic guard: claim this send by nullifying next_execution_time.
        # Only one concurrent caller can win; prevents duplicate sends.
        claimed = CampaignLead.objects.filter(
            id=campaign_lead_id,
            current_step_id=step_id,
            next_execution_time__isnull=False,
        ).update(next_execution_time=None)
        if not claimed:
            logger.info(
                f"Skipping duplicate send for {clead.lead.email} on step {step.step_order}"
            )
            return

        subject, body = personalize_email(step.template_subject, step.template_body, clead.lead)

        account = clead.campaign.connected_account
        if account:
            try:
                message_id = send_gmail(account, clead.lead.email, subject, body)
                clead.last_sent_message_id = message_id
                clead.save(update_fields=['last_sent_message_id'])
                logger.info(f"Gmail SENT to {clead.lead.email} | msg_id={message_id}")
            except Exception as gmail_err:
                logger.error(f"Gmail API send failed for {clead.lead.email}: {gmail_err}")
                # Restore next_execution_time so the lead can be retried later.
                clead.next_execution_time = timezone.now() + timedelta(minutes=15)
                clead.save(update_fields=['next_execution_time'])
                return
        else:
            logger.info(f"Mock SENDING EMAIL to {clead.lead.email} | Subject: {subject}")

        _advance_to_next_step(clead, step)

    except Exception as e:
        logger.error(f"Failed to send email step: {e}")


@shared_task
def process_active_leads():
    """
    Runs every minute via Celery Beat to fetch scheduled tasks and execute them.
    """
    processed = process_active_leads_once()
    return f"Triggered execution for {processed} campaign leads."


def process_active_leads_once(now=None):
    """
    Process currently due campaign leads exactly once.
    Returns the number of leads that were advanced/queued.
    """
    now = now or timezone.now()

    ready_leads = CampaignLead.objects.filter(
        status__in=['ENROLLED', 'ACTIVE'],
        campaign__status='ACTIVE',
    ).select_related('campaign', 'current_step', 'lead')

    processed = 0
    eager_mode = bool(getattr(django_settings, 'CELERY_TASK_ALWAYS_EAGER', False))
    for clead in ready_leads:
        lead_processed = False
        for _ in range(20):
            if not clead.current_step:
                if clead.status not in {'ENROLLED', 'ACTIVE'}:
                    break
                
                steps = _get_campaign_steps(clead.campaign)
                first_step = steps[0] if steps else None
                
                if not first_step:
                    break
                clead.current_step = first_step
                clead.next_execution_time = now + timedelta(minutes=max(first_step.delay_minutes, 0))
                clead.status = 'ACTIVE'
                clead.save(update_fields=['current_step', 'next_execution_time', 'status'])

            if not clead.next_execution_time:
                clead.next_execution_time = now + timedelta(minutes=max(clead.current_step.delay_minutes, 0))
                clead.save(update_fields=['next_execution_time'])

            if clead.next_execution_time > now:
                break

            if clead.current_step.channel_type == 'EMAIL':
                prev_step_id = clead.current_step_id
                prev_next_time = clead.next_execution_time
                send_email_step.delay(clead.id, clead.current_step.id)
                lead_processed = True
                if not eager_mode:
                    break
                clead.refresh_from_db(fields=['current_step', 'next_execution_time', 'status'])
                if clead.current_step_id == prev_step_id and clead.next_execution_time == prev_next_time:
                    # Task likely queued/mocked but not executed inline; avoid repeated dispatch.
                    break
                if clead.next_execution_time and clead.next_execution_time > now:
                    break
                continue

            _execute_non_email_step(clead, clead.current_step, now=now)
            lead_processed = True
            clead.refresh_from_db(fields=['current_step', 'next_execution_time', 'status'])

        if lead_processed:
            processed += 1

    return processed


@shared_task
def poll_gmail_for_replies():
    """
    Runs every 5 minutes via Celery Beat.
    Checks connected Gmail accounts for replies to sent campaign emails.
    """
    if not getattr(django_settings, 'ENABLE_AUTO_REPLY_DETECTION', False):
        return "Reply polling disabled"

    active_leads = CampaignLead.objects.filter(
        status__in=['ACTIVE', 'ENROLLED', 'FINISHED'],
        last_sent_message_id__isnull=False,
        campaign__connected_account__isnull=False,
    ).select_related('campaign__connected_account', 'lead')

    account_map = {}
    for clead in active_leads:
        acct = clead.campaign.connected_account
        if acct.id not in account_map:
            account_map[acct.id] = {'account': acct, 'leads': []}
        account_map[acct.id]['leads'].append(clead)

    total_replies = 0
    campaign_branching_cache = {}
    for data in account_map.values():
        account = data['account']
        leads = data['leads']
        msg_ids = [cl.last_sent_message_id for cl in leads]

        try:
            replies = check_for_replies(account, msg_ids)
        except Exception as e:
            logger.error(f"Failed to poll replies for {account.email_address}: {e}")
            continue

        for clead in leads:
            if clead.last_sent_message_id in replies:
                campaign_id = clead.campaign_id
                uses_reply_yes_branch = campaign_branching_cache.get(campaign_id)
                if uses_reply_yes_branch is None:
                    uses_reply_yes_branch = _campaign_has_condition_reply_yes_branch(clead.campaign)
                    campaign_branching_cache[campaign_id] = uses_reply_yes_branch

                if uses_reply_yes_branch:
                    clead.last_replied_at = timezone.now()
                    clead.save(update_fields=['last_replied_at'])
                    total_replies += 1
                    logger.info(
                        f"Reply detected for {clead.lead.email} in campaign {clead.campaign.name}; "
                        "marked last_replied_at for CONDITION_REPLY branch."
                    )

                    # If currently parked on CONDITION_REPLY, execute branch routing now
                    # so the follow-up email can be sent immediately.
                    if clead.current_step and clead.current_step.channel_type == 'CONDITION_REPLY':
                        _execute_condition_reply_step(clead, clead.current_step, now=timezone.now())
                    elif clead.status in {'FINISHED', 'REPLIED'}:
                        # Recovery path: if the lead was already closed before reply was detected,
                        # re-open it at CONDITION_REPLY and evaluate the yes/no routing.
                        condition_step = (
                            SequenceStep.objects.filter(
                                campaign=clead.campaign,
                                channel_type='CONDITION_REPLY',
                            )
                            .order_by('step_order')
                            .first()
                        )
                        if condition_step:
                            clead.current_step = condition_step
                            clead.status = 'ACTIVE'
                            clead.next_execution_time = timezone.now()
                            clead.save(update_fields=['current_step', 'status', 'next_execution_time'])
                            _execute_condition_reply_step(clead, condition_step, now=timezone.now())
                    continue

                clead.status = 'REPLIED'
                clead.save(update_fields=['status'])
                total_replies += 1
                logger.info(f"Reply detected for {clead.lead.email} in campaign {clead.campaign.name}")
                _maybe_mark_campaign_completed(clead.campaign)

    return f"Detected {total_replies} new replies."
