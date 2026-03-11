from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from leads.models import Lead

from .models import Campaign, CampaignLead, SequenceStep
from .serializers import CampaignSerializer, SequenceStepSerializer

class CampaignViewSet(viewsets.ModelViewSet):
    serializer_class = CampaignSerializer
    queryset = Campaign.objects.all()

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
                
        return Response({"message": f"Successfully enrolled {enrolled_count} leads."}, status=status.HTTP_200_OK)

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

        enrolled_count = campaign.enrolled_leads.count()
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

class SequenceStepViewSet(viewsets.ModelViewSet):
    serializer_class = SequenceStepSerializer
    queryset = SequenceStep.objects.all()

    def get_queryset(self):
        return SequenceStep.objects.filter(organization=self.request.user.organization)

    def perform_create(self, serializer):
        campaign_id = self.kwargs.get('campaign_pk')
        campaign = Campaign.objects.get(id=campaign_id, organization=self.request.user.organization)
        serializer.save(campaign=campaign, organization=self.request.user.organization)

from rest_framework.views import APIView
from django.utils import timezone

class WebhookView(APIView):
    """
    Receives webhooks from email service provider (e.g. SendGrid/Mailgun)
    to track opens, clicks, bounces.
    """
    permission_classes = [AllowAny] # Webhooks need to be publicly accessible
    
    def post(self, request, *args, **kwargs):
        event_type = (request.data.get('event') or '').strip().lower()
        lead_email = request.data.get('email')
        message_id = request.data.get('message_id') or request.data.get('messageId')
        
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
                        cl.save(update_fields=['status'])
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
                pass
                
        return Response({"status": "received"}, status=status.HTTP_200_OK)

class DashboardAnalyticsView(APIView):
    """
    Returns high-level aggregated metrics for the analytics page.
    Accepts ?days=N query param (default 30).
    """
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        from django.utils import timezone
        from datetime import timedelta
        from django.db.models import Count, Q
        from django.db.models.functions import TruncDate

        days = min(int(request.query_params.get('days', 30)), 365)
        cutoff = timezone.now() - timedelta(days=days)

        # ── Aggregate KPIs from CampaignLead ──
        all_cls = CampaignLead._default_manager.all()

        sent_statuses = ['ACTIVE', 'FINISHED', 'REPLIED', 'BOUNCED']
        emails_sent = all_cls.filter(status__in=sent_statuses).count()
        opened = all_cls.filter(last_opened_at__isnull=False).count()
        replied = all_cls.filter(status='REPLIED').count()
        clicked = all_cls.filter(last_clicked_at__isnull=False).count()
        bounced = all_cls.filter(status='BOUNCED').count()

        total_leads = Lead._default_manager.all().count()
        active_campaigns = Campaign._default_manager.filter(status='ACTIVE').count()

        open_rate = round((opened / emails_sent * 100) if emails_sent > 0 else 0, 1)
        reply_rate = round((replied / emails_sent * 100) if emails_sent > 0 else 0, 1)
        click_rate = round((clicked / emails_sent * 100) if emails_sent > 0 else 0, 1)
        bounce_rate = round((bounced / emails_sent * 100) if emails_sent > 0 else 0, 1)

        # ── Time-series: daily aggregates within the window ──
        ts_qs = all_cls.filter(created_at__gte=cutoff)

        sent_by_day = dict(
            ts_qs.filter(status__in=sent_statuses)
            .annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(count=Count('id'))
            .values_list('day', 'count')
        )
        opened_by_day = dict(
            ts_qs.filter(last_opened_at__isnull=False)
            .annotate(day=TruncDate('last_opened_at'))
            .values('day')
            .annotate(count=Count('id'))
            .values_list('day', 'count')
        )
        replied_by_day = dict(
            ts_qs.filter(last_replied_at__isnull=False)
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

        # ── Per-campaign breakdown ──
        campaign_stats = []
        for c in Campaign._default_manager.all().order_by('-created_at')[:20]:
            cls = CampaignLead._default_manager.filter(campaign=c)
            c_sent = cls.filter(status__in=sent_statuses).count()
            c_opened = cls.filter(last_opened_at__isnull=False).count()
            c_replied = cls.filter(status='REPLIED').count()
            c_bounced = cls.filter(status='BOUNCED').count()
            campaign_stats.append({
                'id': str(c.id),
                'name': c.name,
                'status': c.status,
                'enrolled': cls.count(),
                'sent': c_sent,
                'opened': c_opened,
                'replied': c_replied,
                'bounced': c_bounced,
            })

        # ── Recent activity (real data) ──
        recent = []
        for cl in all_cls.order_by('-updated_at')[:10]:
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
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        prompt = (request.data.get('prompt') or '').strip()
        current_subject = request.data.get('subject', '')
        current_body = request.data.get('body', '')
        messages = request.data.get('messages', [])

        if not prompt and not messages:
            return Response({'error': 'prompt is required'}, status=status.HTTP_400_BAD_REQUEST)

        from .ai import generate_email_chat_completion

        try:
            result = generate_email_chat_completion(
                prompt=prompt,
                current_subject=current_subject,
                current_body=current_body,
                messages=messages,
            )
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
