"""
Django signals to automatically maintain cached counters on Campaign model.
This ensures real-time consistency when CampaignLead records are modified.
"""

from django.db.models import Count, F, Q
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from .models import CampaignLead, Campaign
from leads.models import Lead

SENT_STATUSES = {'ACTIVE', 'FINISHED', 'REPLIED', 'BOUNCED'}


def _campaignlead_counter_flags(status, last_opened_at, last_clicked_at):
    return {
        'leads_count': 1,
        'sent_count': 1 if status in SENT_STATUSES else 0,
        'open_count': 1 if last_opened_at else 0,
        'reply_count': 1 if status == 'REPLIED' else 0,
        'clicked_count': 1 if last_clicked_at else 0,
        'bounced_count': 1 if status == 'BOUNCED' else 0,
    }


def _apply_campaign_counter_delta(campaign_id, delta):
    if not campaign_id or not any(delta.values()):
        return

    Campaign.objects.filter(id=campaign_id).update(
        leads_count=F('leads_count') + delta['leads_count'],
        sent_count=F('sent_count') + delta['sent_count'],
        open_count=F('open_count') + delta['open_count'],
        reply_count=F('reply_count') + delta['reply_count'],
        clicked_count=F('clicked_count') + delta['clicked_count'],
        bounced_count=F('bounced_count') + delta['bounced_count'],
    )


def _delta_from_states(new_state, old_state):
    return {
        key: new_state[key] - old_state[key]
        for key in new_state.keys()
    }


def _update_campaign_counters(campaign):
    """
    Recalculate and update all cached counters for a campaign.
    Called when a CampaignLead changes.
    """
    qs = CampaignLead.objects.filter(campaign=campaign)
    
    # Total enrolled leads
    leads_count = qs.count()
    
    # Sent: leads with status in ['ACTIVE', 'FINISHED', 'REPLIED', 'BOUNCED']
    sent_count = qs.filter(
        status__in=['ACTIVE', 'FINISHED', 'REPLIED', 'BOUNCED']
    ).count()
    
    # Opened: leads with last_opened_at not null
    open_count = qs.filter(last_opened_at__isnull=False).count()
    
    # Replied: leads with status 'REPLIED'
    reply_count = qs.filter(status='REPLIED').count()
    
    # Clicked: leads with last_clicked_at not null
    clicked_count = qs.filter(last_clicked_at__isnull=False).count()
    
    # Bounced: leads with status 'BOUNCED'
    bounced_count = qs.filter(status='BOUNCED').count()
    
    # Update campaign with all new counts
    campaign.leads_count = leads_count
    campaign.sent_count = sent_count
    campaign.open_count = open_count
    campaign.reply_count = reply_count
    campaign.clicked_count = clicked_count
    campaign.bounced_count = bounced_count
    campaign.save(
        update_fields=[
            'leads_count',
            'sent_count',
            'open_count',
            'reply_count',
            'clicked_count',
            'bounced_count',
        ]
    )


@receiver(pre_save, sender=CampaignLead)
def capture_previous_campaignlead_state(sender, instance, **kwargs):
    """
    Preserve the previous CampaignLead state so post_save can apply a delta.
    """
    if not instance.pk:
        instance._previous_campaignlead_state = None
        return

    instance._previous_campaignlead_state = sender.objects.filter(pk=instance.pk).values(
        'campaign_id',
        'lead_id',
        'status',
        'last_opened_at',
        'last_clicked_at',
    ).first()


def _calculate_lead_score(lead):
    """
    Derive a simple engagement score for a lead from related CampaignLead rows.
    """
    agg = CampaignLead.objects.filter(lead=lead).aggregate(
        open_count=Count('id', filter=Q(last_opened_at__isnull=False)),
        click_count=Count('id', filter=Q(last_clicked_at__isnull=False)),
        reply_count=Count('id', filter=Q(status='REPLIED')),
        bounced_count=Count('id', filter=Q(status='BOUNCED')),
        active_count=Count('id', filter=Q(status='ACTIVE')),
    )

    score = (
        (agg['open_count'] * 5)
        + (agg['click_count'] * 7)
        + (agg['reply_count'] * 10)
        + (agg['active_count'] * 2)
        - (agg['bounced_count'] * 5)
        - (5 if lead.global_unsubscribe else 0)
    )
    return max(score, 0)


def _update_lead_score(lead):
    lead.score = _calculate_lead_score(lead)
    lead.save(update_fields=['score'])


@receiver(post_save, sender=CampaignLead)
def update_campaign_counters_on_save(sender, instance, created, **kwargs):
    """
    When a CampaignLead is created or updated, recalculate campaign counters.
    """
    previous_state = getattr(instance, '_previous_campaignlead_state', None)
    new_state = _campaignlead_counter_flags(
        instance.status,
        instance.last_opened_at,
        instance.last_clicked_at,
    )

    if previous_state is None:
        _apply_campaign_counter_delta(instance.campaign_id, new_state)
    else:
        old_state = _campaignlead_counter_flags(
            previous_state['status'],
            previous_state['last_opened_at'],
            previous_state['last_clicked_at'],
        )
        delta = _delta_from_states(new_state, old_state)

        if previous_state['campaign_id'] != instance.campaign_id:
            _apply_campaign_counter_delta(previous_state['campaign_id'], {
                key: -value for key, value in old_state.items()
            })
            _apply_campaign_counter_delta(instance.campaign_id, new_state)
        else:
            _apply_campaign_counter_delta(instance.campaign_id, delta)

    _update_lead_score(instance.lead)


@receiver(post_delete, sender=CampaignLead)
def update_campaign_counters_on_delete(sender, instance, **kwargs):
    """
    When a CampaignLead is deleted, recalculate campaign counters.
    We need to check if the campaign still exists (it might have been cascade deleted).
    """
    _apply_campaign_counter_delta(
        instance.campaign_id,
        {
            key: -value
            for key, value in _campaignlead_counter_flags(
                instance.status,
                instance.last_opened_at,
                instance.last_clicked_at,
            ).items()
        },
    )
    try:
        lead = Lead.objects.get(id=instance.lead_id)
        _update_lead_score(lead)
    except Lead.DoesNotExist:
        # Lead was already deleted, nothing to update
        pass
