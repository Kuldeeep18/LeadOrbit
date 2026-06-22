import logging


import urllib.parse
from django.core.signing import Signer, BadSignature
from django.http import HttpResponseRedirect, HttpResponseBadRequest
# ------------------------------------------

from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from leads.models import Lead
from users.permissions import IsOrgManager

from .models import Campaign, CampaignLead, SequenceStep, EmailTemplate
from .serializers import CampaignSerializer, SequenceStepSerializer, EmailTemplateSerializer

logger = logging.getLogger(__name__)

class CampaignViewSet(viewsets.ModelViewSet):
    serializer_class = CampaignSerializer
    queryset = Campaign.objects.all()
    manager_actions = frozenset({
        'create',
        'update',
        'partial_update',
        'destroy',
        'enroll',
        'launch',
        'pause',
        'resume',
    })

    def get_permissions(self):
        permissions = super().get_permissions()
        if self.action in self.manager_actions:
            permissions.append(IsOrgManager())
        return permissions

    def get_queryset(self):
        return (
            Campaign.objects.filter(organization=self.request.user.organization)
            .select_related('connected_account')
            .prefetch_related('steps', 'enrolled_leads')
        )

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)

    @action(detail=True, methods=['post'])
    def enroll(self, request, pk=None):
        campaign = self.get_object()
        lead_ids = request.data.get('lead_ids', [])
        
        enrolled_count = 0
        for lead_id in lead_ids:
            try:
                lead = Lead.objects.get(id=lead_id, organization=request.user.organization)
                CampaignLead.objects.get_or_create(
                    campaign=campaign,
                    lead=lead,
                    defaults={'organization': request.user.organization},
                )
                enrolled_count += 1
            except Lead.DoesNotExist:
                continue
        
        # Refresh campaign to get updated cached counters from signals
        campaign.refresh_from_db()
        
        return Response(
            {
                "message": f"Successfully enrolled {enrolled_count} leads.",
                "total_enrolled": campaign.leads_count,
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'])
    def launch(self, request, pk=None):
        """
        Activates the campaign and triggers an immediate processing pass.
        In dev, this works without a separate Celery worker when eager mode is enabled.
        """
        from django.conf import settings as django_settings
        from .tasks import process_active_leads, process_active_leads_once

        campaign = self.get_object()

        if campaign.connected_account_id:
            # Fetch the account using unscoped query to avoid TenantManager hiding it
            from .models import ConnectedEmailAccount
            try:
                account = ConnectedEmailAccount._default_manager.get(id=campaign.connected_account_id)
            except ConnectedEmailAccount.DoesNotExist:
                return Response(
                    {
                        "error": "Connected email account not found. Please reconnect your Gmail account in Settings.",
                        "campaign_id": str(campaign.id),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Verify the account belongs to the same organization
            if account.organization_id != request.user.organization_id:
                return Response(
                    {
                        "error": "Selected sender account belongs to another organization.",
                        "campaign_id": str(campaign.id),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Ownership check: allow if connected_by matches OR if connected_by is not set (legacy)
            user_email = (request.user.email or '').lower()
            owned_by_user = (
                account.connected_by_id == request.user.id
                or account.connected_by_id is None  # Legacy accounts without per-user tracking
                or (account.email_address or '').lower() == user_email
            )
            if not owned_by_user:
                return Response(
                    {
                        "error": "Selected sender account belongs to another user. "
                                 "Choose your own connected Gmail account before launch.",
                        "campaign_id": str(campaign.id),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        enrolled_count = campaign.leads_count
        if enrolled_count == 0:
            return Response(
                {
                    "error": "No leads enrolled. Add leads before launching.",
                    "campaign_id": str(campaign.id),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if campaign.status != 'ACTIVE':
            campaign.status = 'ACTIVE'
            campaign.save(update_fields=['status'])

        immediate_processed = 0
        if django_settings.CELERY_TASK_ALWAYS_EAGER:
            # Keep launch endpoint responsive; run only a bounded number of immediate passes.
            immediate_passes = max(0, int(getattr(django_settings, 'LAUNCH_IMMEDIATE_PASSES', 1)))
            for _ in range(immediate_passes):
                processed = process_active_leads_once()
                immediate_processed += processed
                if processed == 0:
                    break
        else:
            # Run one in-process pass so due steps (including SMS) can execute
            # even when a worker queue is delayed or misconfigured.
            immediate_processed = process_active_leads_once()
            process_active_leads.delay()

        return Response(
            {
                "message": "Campaign launched. Processing queue triggered.",
                "campaign_id": str(campaign.id),
                "enrolled_leads": enrolled_count,
                "immediate_processed": immediate_processed,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        campaign = self.get_object()

        if campaign.status != 'ACTIVE':
            return Response(
                {
                    "error": "Only active campaigns can be paused.",
                    "campaign_id": str(campaign.id),
                    "status": campaign.status,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        campaign.status = 'PAUSED'
        campaign.save(update_fields=['status'])

        return Response(
            {
                "message": "Campaign paused.",
                "campaign_id": str(campaign.id),
                "status": campaign.status,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        from .tasks import process_active_leads

        campaign = self.get_object()

        if campaign.status != 'PAUSED':
            return Response(
                {
                    "error": "Only paused campaigns can be resumed.",
                    "campaign_id": str(campaign.id),
                    "status": campaign.status,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        campaign.status = 'ACTIVE'
        campaign.save(update_fields=['status'])
        process_active_leads.delay()

        return Response(
            {
                "message": "Campaign resumed. Processing queue triggered.",
                "campaign_id": str(campaign.id),
                "status": campaign.status,
            },
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=['get'])
    def metrics(self, request, pk=None):
        """Get comprehensive campaign performance metrics."""
        campaign = self.get_object()
        enrolled_leads = campaign.enrolled_leads.all()
        total = enrolled_leads.count()

        if total == 0:
            return Response({
                'total_leads': 0,
                'active': 0,
                'replied': 0,
                'bounced': 0,
                'opened': 0,
                'clicked': 0,
                'engagement_rate': 0,
                'conversion_rate': 0,
                'click_through_rate': 0,
            })

        active = enrolled_leads.filter(status='ACTIVE').count()
        replied = enrolled_leads.filter(status='REPLIED').count()
        bounced = enrolled_leads.filter(status='BOUNCED').count()
        opened = enrolled_leads.filter(last_opened_at__isnull=False).count()
        clicked = enrolled_leads.filter(last_clicked_at__isnull=False).count()

        return Response({
            'campaign_id': str(campaign.id),
            'campaign_name': campaign.name,
            'total_leads': total,
            'active': active,
            'replied': replied,
            'bounced': bounced,
            'opened': opened,
            'clicked': clicked,
            'engagement_rate': round((opened / total * 100) if total > 0 else 0, 2),
            'conversion_rate': round((replied / total * 100) if total > 0 else 0, 2),
            'click_through_rate': round((clicked / total * 100) if total > 0 else 0, 2),
        })

    @action(detail=True, methods=['get'])
    def leads(self, request, pk=None):
        """Get paginated list of enrolled leads with metrics."""
        campaign = self.get_object()
        status_filter = request.query_params.get('status')
        limit = int(request.query_params.get('limit', 50))
        offset = int(request.query_params.get('offset', 0))

        leads_qs = campaign.enrolled_leads.select_related('lead').order_by('-updated_at')

        if status_filter:
            leads_qs = leads_qs.filter(status=status_filter)

        total = leads_qs.count()
        leads_data = []

        for cl in leads_qs[offset:offset+limit]:
            leads_data.append({
                'lead_id': str(cl.lead.id),
                'email': cl.lead.email,
                'status': cl.status,
                'current_step': cl.current_step.step_order if cl.current_step else None,
                'last_sent_at': cl.last_sent_message_id,
                'last_opened_at': cl.last_opened_at.isoformat() if cl.last_opened_at else None,
                'last_clicked_at': cl.last_clicked_at.isoformat() if cl.last_clicked_at else None,
                'last_replied_at': cl.last_replied_at.isoformat() if cl.last_replied_at else None,
                'next_execution': cl.next_execution_time.isoformat() if cl.next_execution_time else None,
            })

        return Response({
            'campaign_id': str(campaign.id),
            'total_leads': total,
            'offset': offset,
            'limit': limit,
            'leads': leads_data,
        })

    @action(detail=True, methods=['post'])
    def process_now(self, request, pk=None):
        """Immediately process all pending leads in the campaign."""
        from .tasks import process_active_leads_once

        campaign = self.get_object()

        if campaign.status != 'ACTIVE':
            return Response(
                {
                    "error": "Campaign must be active to process leads.",
                    "campaign_id": str(campaign.id),
                    "status": campaign.status,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        processed = process_active_leads_once()

        return Response(
            {
                "success": True,
                "processed_leads": processed,
                "message": f"Processed {processed} campaign leads immediately.",
            },
            status=status.HTTP_200_OK,
        )

class SequenceStepViewSet(viewsets.ModelViewSet):
    serializer_class = SequenceStepSerializer
    queryset = SequenceStep.objects.all()
    manager_actions = frozenset({'create', 'update', 'partial_update', 'destroy'})

    def get_permissions(self):
        permissions = super().get_permissions()
        if self.action in self.manager_actions:
            permissions.append(IsOrgManager())
        return permissions

    def get_queryset(self):
        return SequenceStep.objects.filter(organization=self.request.user.organization)

    def perform_create(self, serializer):
        campaign_id = self.kwargs.get('campaign_pk')
        campaign = Campaign.objects.get(id=campaign_id, organization=self.request.user.organization)
        serializer.save(campaign=campaign, organization=self.request.user.organization)

class EmailTemplateViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = EmailTemplateSerializer
    queryset = EmailTemplate.objects.all()

    def get_queryset(self):
        return EmailTemplate.objects.filter(organization=self.request.user.organization)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)

from rest_framework.views import APIView
from django.utils import timezone
from django.conf import settings as django_settings
from pathlib import Path

class WebhookView(APIView):
    """
    Receives webhooks from email service provider (e.g. SendGrid/Mailgun)
    to track opens, clicks, bounces.
    """
    permission_classes = [AllowAny] # Webhooks need to be publicly accessible

    @staticmethod
    def _extract_bounce_details(payload):
        bounce_payload = payload.get('bounce')
        if not isinstance(bounce_payload, dict):
            bounce_payload = {}

        bounce_type = (
            payload.get('bounce_type')
            or bounce_payload.get('type')
            or bounce_payload.get('bounce_type')
            or payload.get('type')
            or ''
        )
        bounce_code = (
            payload.get('code')
            or bounce_payload.get('code')
            or bounce_payload.get('smtp_code')
            or bounce_payload.get('status')
            or ''
        )
        bounce_reason = (
            payload.get('reason')
            or payload.get('description')
            or bounce_payload.get('reason')
            or bounce_payload.get('description')
            or bounce_payload.get('detail')
            or payload.get('message')
            or ''
        )

        return {
            'bounce_type': str(bounce_type).strip().lower() or None,
            'bounce_code': str(bounce_code).strip() or None,
            'bounce_reason': str(bounce_reason).strip() or None,
        }
    
    def post(self, request, *args, **kwargs):
        event_type = (request.data.get('event') or '').strip().lower()
        lead_email = request.data.get('email')
        message_id = request.data.get('message_id') or request.data.get('messageId')
        bounce_details = self._extract_bounce_details(request.data)
        
        # Simple MVP tracking
        if event_type and lead_email:
            try:
                # Find active campaign lead matching this email
                base_qs = CampaignLead.objects.filter(
                    lead__email=lead_email,
                    status__in=['ACTIVE', 'ENROLLED'],
                )
                if message_id:
                    base_qs = base_qs.filter(last_sent_message_id=message_id)
                cleads = list(base_qs)

                now = timezone.now()
                from campaigns.tasks import (
                    _campaign_has_condition_reply_yes_branch,
                    _execute_condition_click_step,
                    _execute_condition_open_step,
                    _execute_condition_reply_step,
                )

                for cl in cleads:
                    if event_type == 'bounce':
                        cl.status = 'BOUNCED'
                        if bounce_details['bounce_type']:
                            cl.bounce_type = bounce_details['bounce_type']
                        if bounce_details['bounce_code']:
                            cl.bounce_code = bounce_details['bounce_code']
                        if bounce_details['bounce_reason']:
                            cl.bounce_reason = bounce_details['bounce_reason']
                        cl.save(update_fields=[
                            'status',
                            'bounce_type',
                            'bounce_code',
                            'bounce_reason',
                        ])
                        logger.info(
                            'Webhook bounce processed for email=%s type=%s code=%s reason=%s',
                            lead_email,
                            cl.bounce_type or 'unknown',
                            cl.bounce_code or 'unknown',
                            cl.bounce_reason or 'unknown',
                        )
                    elif event_type == 'reply':
                        cl.last_replied_at = now
                        # Only hard-stop if there is no reply-yes branch configured.
                        if not _campaign_has_condition_reply_yes_branch(cl.campaign):
                            cl.status = 'REPLIED'
                            cl.current_step = None
                            cl.next_execution_time = None
                            cl.save(update_fields=['status', 'current_step', 'next_execution_time', 'last_replied_at'])
                        else:
                            cl.save(update_fields=['last_replied_at'])
                            if cl.current_step and cl.current_step.channel_type == 'CONDITION_REPLY':
                                _execute_condition_reply_step(cl, cl.current_step, now=now)
                    elif event_type == 'open':
                        cl.last_opened_at = now
                        cl.save(update_fields=['last_opened_at'])
                        if cl.current_step and cl.current_step.channel_type == 'CONDITION_OPEN':
                            _execute_condition_open_step(cl, cl.current_step, now=now)
                    elif event_type == 'click':
                        cl.last_clicked_at = now
                        cl.save(update_fields=['last_clicked_at'])
                        if cl.current_step and cl.current_step.channel_type == 'CONDITION_CLICK':
                            _execute_condition_click_step(cl, cl.current_step, now=now)
            except Exception as e:
                logger.exception(
                    'Webhook processing error for event=%s email=%s: %s',
                    event_type,
                    lead_email,
                    e,
                )
                
                return Response(
                    {"error": "Webhook processing failed"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
                            
        return Response({"status": "received"}, status=status.HTTP_200_OK)

class DashboardAnalyticsView(APIView):
    """
    Returns high-level aggregated metrics for the analytics page.
    Accepts ?days=N query param (default 30).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        from django.utils import timezone
        from datetime import timedelta
        from django.db.models import Count, Q, Sum
        from django.db.models.functions import TruncDate

        org = getattr(request.user, 'organization', None)
        if org is None:
            return Response(
                {'detail': 'Organization context required for analytics.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        days_param = request.query_params.get('days', 30)
        try:
            days = int(days_param)
        except (TypeError, ValueError):
            days = 30
        days = max(1, min(days, 365))

        cutoff = timezone.now() - timedelta(days=days)

        # ── Aggregate KPIs using cached counters on Campaign ──
        # Sum cached counters across all campaigns for instant metrics
        campaign_agg = Campaign.objects.filter(organization=org).aggregate(
            emails_sent=Sum('sent_count'),
            opened=Sum('open_count'),
            replied=Sum('reply_count'),
            clicked=Sum('clicked_count'),
            bounced=Sum('bounced_count'),
        )
        
        emails_sent = campaign_agg['emails_sent'] or 0
        opened = campaign_agg['opened'] or 0
        replied = campaign_agg['replied'] or 0
        clicked = campaign_agg['clicked'] or 0
        bounced = campaign_agg['bounced'] or 0

        total_leads = Lead.objects.filter(organization=org).count()
        active_campaigns = Campaign.objects.filter(organization=org, status='ACTIVE').count()

        open_rate = round((opened / emails_sent * 100) if emails_sent > 0 else 0, 1)
        reply_rate = round((replied / emails_sent * 100) if emails_sent > 0 else 0, 1)
        click_rate = round((clicked / emails_sent * 100) if emails_sent > 0 else 0, 1)
        bounce_rate = round((bounced / emails_sent * 100) if emails_sent > 0 else 0, 1)

        # ── Time-series: daily aggregates within the window ──
        # Still need to query CampaignLead for time-series breakdown
        all_cls = CampaignLead.objects.filter(organization=org, created_at__gte=cutoff)

        sent_statuses = ['ACTIVE', 'FINISHED', 'REPLIED', 'BOUNCED']
        sent_by_day = dict(
            all_cls.filter(status__in=sent_statuses)
            .annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(count=Count('id'))
            .values_list('day', 'count')
        )
        opened_by_day = dict(
            all_cls.filter(last_opened_at__isnull=False)
            .annotate(day=TruncDate('last_opened_at'))
            .values('day')
            .annotate(count=Count('id'))
            .values_list('day', 'count')
        )
        replied_by_day = dict(
            all_cls.filter(last_replied_at__isnull=False)
            .annotate(day=TruncDate('last_replied_at'))
            .values('day')
            .annotate(count=Count('id'))
            .values_list('day', 'count')
        )

        labels = []
        sent_series = []
        opened_series = []
        replied_series = []
        today = timezone.now().date()
        for i in range(days):
            d = today - timedelta(days=days - 1 - i)
            labels.append(d.isoformat())
            sent_series.append(sent_by_day.get(d, 0))
            opened_series.append(opened_by_day.get(d, 0))
            replied_series.append(replied_by_day.get(d, 0))

        # ── Per-campaign breakdown: use cached counters directly ──
        campaign_stats = []
        for c in Campaign.objects.filter(organization=org).order_by('-created_at')[:20]:
            campaign_stats.append({
                'id': str(c.id),
                'name': c.name,
                'status': c.status,
                'enrolled': c.leads_count,
                'sent': c.sent_count,
                'opened': c.open_count,
                'replied': c.reply_count,
                'bounced': c.bounced_count,
            })

        # ── Recent activity (real data) ──
        recent = []
        for cl in (
            CampaignLead.objects
            .filter(organization=org)
            .select_related('lead', 'campaign')
            .order_by('-updated_at')[:10]
        ):
        
            action = cl.status.lower()
            lead_name = cl.lead.email if cl.lead else 'Unknown'
            recent.append({
                'type': f'lead_{action}',
                'description': f'{lead_name} — {action} in {cl.campaign.name}',
                'time': cl.updated_at.isoformat() if cl.updated_at else '',
            })

        return Response({
            'total_leads': total_leads,
            'active_campaigns': active_campaigns,
            'emails_sent': emails_sent,
            'opened': opened,
            'replied': replied,
            'clicked': clicked,
            'bounced': bounced,
            'open_rate': open_rate,
            'reply_rate': reply_rate,
            'click_rate': click_rate,
            'bounce_rate': bounce_rate,
            'time_series': {
                'labels': labels,
                'sent': sent_series,
                'opened': opened_series,
                'replied': replied_series,
            },
            'campaign_stats': campaign_stats,
            'recent_activity': recent,
        })


class AIGenerateView(APIView):
    """
    POST /api/v1/campaigns/ai-generate/
    Generate email content using the configured LLM provider for the campaign builder.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        prompt = (request.data.get('prompt') or '').strip()
        current_subject = request.data.get('subject', '')
        current_body = request.data.get('body', '')
        messages = request.data.get('messages', [])

        if not prompt and not messages:
            return Response({'error': 'prompt is required'}, status=status.HTTP_400_BAD_REQUEST)

        # Backward-compatible fallback: when Gemini key is missing, return a
        # deterministic local draft regardless of external provider env state.
        if not (getattr(django_settings, 'GEMINI_API_KEY', '') or '').strip():
            generated = self._build_fallback_content(request)
            return Response(
                {
                    'assistant_message': 'Using fallback draft because AI API key is not configured.',
                    'subject': current_subject or 'Quick idea for {{company}}',
                    'body': current_body or (
                        "Hi {{firstName}},\n\n"
                        "I noticed your work at {{company}} and wanted to share a short idea that might help.\n"
                        "Would you be open to a quick 10-minute chat this week?\n\n"
                        "Best,\n"
                        "Your Name"
                    ),
                    'generated': generated,
                    'provider': 'fallback',
                    'model': 'template',
                    'fallback': True,
                },
                status=status.HTTP_200_OK,
            )

        from .ai import generate_email_chat_completion

        try:
            result = generate_email_chat_completion(
                prompt=prompt,
                current_subject=current_subject,
                current_body=current_body,
                messages=messages,
            )
            generated = f"SUBJECT: {result.get('subject', '')}\nBODY: {result.get('body', '')}"
            result.setdefault('generated', generated)
            result.setdefault('fallback', False)
            return Response(result, status=status.HTTP_200_OK)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response(
                {
                    'error': 'AI generation failed',
                    'detail': str(exc),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

    def _build_fallback_content(self, request):
        subject = request.data.get('subject') or 'Quick idea for {{company}}'
        body = request.data.get('body') or (
            "Hi {{firstName}},\n\n"
            "I noticed your work at {{company}} and wanted to share a short idea that might help.\n"
            "Would you be open to a quick 10-minute chat this week?\n\n"
            "Best,\n"
            "Your Name"
        )
        return f"SUBJECT: {subject}\nBODY: {body}"
    
from django.http import HttpResponse
from django.middleware.csrf import get_token
from leads.models import Lead
from .utils import verify_unsubscribe_token


def _unsubscribe_page(title, message, extra_html=''):
    return (
        '<!DOCTYPE html>'
        '<html lang="en">'
        '<head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{title} | LeadOrbit</title>'
        '<style>body{margin:0;font-family:Inter,system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Ubuntu,sans-serif;background:#f8fafc;color:#111827;}'
        '.container{max-width:720px;margin:72px auto;padding:32px;background:#ffffff;border:1px solid #e5e7eb;border-radius:24px;box-shadow:0 20px 80px rgba(15,23,42,.08);}'
        'h1{margin-top:0;font-size:2rem;color:#0f172a;}p{font-size:1rem;line-height:1.7;color:#475569;}'
        'button{margin-top:12px;border:0;border-radius:999px;background:#1d4ed8;color:#fff;font-weight:700;padding:12px 20px;cursor:pointer;}'
        '</style>'
        '</head>'
        f'<body><div class="container"><h1>{title}</h1><p>{message}</p>{extra_html}</div></body>'
        '</html>'
    )


def unsubscribe_view(request, lead_id, token):
    """Public unsubscribe endpoint for GDPR/CAN-SPAM compliance."""
    verified = verify_unsubscribe_token(token)

    if not verified or str(verified) != str(lead_id):
        return HttpResponse(
            "Invalid unsubscribe link",
            status=400,
        )

    try:
        lead = Lead.objects.get(id=lead_id)
    except Lead.DoesNotExist:
        return HttpResponse(
            "Lead not found",
            status=404,
        )

    if request.method != 'POST':
        csrf_token = get_token(request)
        form = (
            f'<form method="post" action="{request.path}">'
            f'<input type="hidden" name="csrfmiddlewaretoken" value="{csrf_token}">'
            '<button type="submit">Confirm unsubscribe</button>'
            '</form>'
        )
        html = _unsubscribe_page(
            'Confirm unsubscribe',
            'Please confirm that you want to unsubscribe from future emails sent through LeadOrbit.',
            form,
        )
        return HttpResponse(html, content_type='text/html')

    lead.global_unsubscribe = True
    lead.save(update_fields=["global_unsubscribe"])

    html = _unsubscribe_page(
        'Unsubscribed',
        'You have been unsubscribed from all future emails sent through LeadOrbit.',
        '<p>If you received this link by mistake, no further action is needed.</p>',
    )

    return HttpResponse(html, content_type='text/html')

# --- New ClickTrackingView (Issue #259) ---
class ClickTrackingView(APIView):
    """
    Unauthenticated endpoint to track email link clicks and redirect to the destination.
    """
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        signed_token = request.GET.get('t')
        dest_url = request.GET.get('dest')

        if not signed_token or not dest_url:
            return HttpResponseBadRequest("Missing tracking parameters.")

        signer = Signer()
        try:
            # Decode and verify the token signature
            unsigned_payload = signer.unsign(signed_token)
            campaign_lead_id, step_id = unsigned_payload.split(':')
        except (BadSignature, ValueError):
            return HttpResponseBadRequest("Invalid or tampered tracking token.")

        # Analytics ko update karna
        try:
            lead = CampaignLead.objects.get(id=campaign_lead_id)
            lead.last_clicked_at = timezone.now()
            lead.save(update_fields=['last_clicked_at'])

            # Optional: Agar conditionally aage badhana hai sequence ko
            if lead.current_step and lead.current_step.channel_type == 'CONDITION_CLICK':
                from .tasks import _execute_condition_click_step
                _execute_condition_click_step(lead, lead.current_step, now=timezone.now())

        except CampaignLead.DoesNotExist:
            pass # Failsafe: Continue to redirect even if the lead was deleted

        # Original Destination par redirect karna
        decoded_dest = urllib.parse.unquote(dest_url)
        return HttpResponseRedirect(decoded_dest)
# ------------------------------------------