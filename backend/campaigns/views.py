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
            # Dev mode: run a few immediate passes so zero-delay sequences progress instantly.
            for _ in range(10):
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
    Returns high-level aggregated metrics for the dashboard.
    """
    def get(self, request, *args, **kwargs):
        # Enforce tenant isolation
        org = request.user.organization
        
        total_leads = Lead.objects.filter(organization=org).count()
        active_campaigns = Campaign.objects.filter(organization=org, status='ACTIVE').count()
        
        # Simplified metrics for MVP
        emails_sent = CampaignLead.objects.filter(
            campaign__organization=org, 
            status__in=['ACTIVE', 'FINISHED', 'REPLIED', 'BOUNCED']
        ).count()
        
        replied = CampaignLead.objects.filter(campaign__organization=org, status='REPLIED').count()
        reply_rate = round((replied / emails_sent * 100) if emails_sent > 0 else 0, 1)
        
        return Response({
            "total_leads": total_leads,
            "active_campaigns": active_campaigns,
            "emails_sent": emails_sent,
            "reply_rate": reply_rate,
            "recent_activity": [
                {
                    "type": "campaign_created",
                    "description": "Welcome sequence was created",
                    "time": "2 hours ago"
                }
            ]
        })


class AIGenerateView(APIView):
    """
    POST /api/v1/campaigns/ai-generate/
    Generate email content using Gemini API for the campaign builder.
    """
    def post(self, request, *args, **kwargs):
        prompt = request.data.get('prompt', '')
        if not prompt:
            return Response({'error': 'prompt is required'}, status=status.HTTP_400_BAD_REQUEST)

        from django.conf import settings as django_settings
        import google.generativeai as genai

        api_key = django_settings.GEMINI_API_KEY
        fallback = self._build_fallback_content(request)
        if not api_key:
            return Response({'generated': fallback, 'fallback': True, 'reason': 'missing_api_key'})

        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-2.0-flash')
            response = model.generate_content(prompt)
            return Response({'generated': response.text})
        except Exception as e:
            return Response(
                {
                    'generated': fallback,
                    'fallback': True,
                    'reason': str(e),
                },
                status=status.HTTP_200_OK,
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
