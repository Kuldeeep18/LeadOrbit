import logging

from django.conf import settings as django_settings
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from leads.models import Lead
from users.permissions import IsOrgManager
from .models import Campaign, CampaignLead, EmailTemplate, SequenceStep, ConnectedEmailAccount
from .serializers import (
    CampaignSerializer,
    EmailTemplateSerializer,
    SequenceStepSerializer,
)
from .tasks import process_active_leads, process_active_leads_once

logger = logging.getLogger(__name__)


class CampaignViewSet(viewsets.ModelViewSet):
    serializer_class = CampaignSerializer
    queryset = Campaign.objects.all()
    manager_actions = frozenset({
        'create', 'update', 'partial_update', 'destroy', 'enroll', 'launch',
        'pause', 'resume', 'remove_leads'
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
        
        campaign.refresh_from_db()
        
        return Response(
            {
                "message": f"Successfully enrolled {enrolled_count} leads.",
                "total_enrolled": campaign.leads_count,
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'], url_path='remove-leads')
    def remove_leads(self, request, pk=None):
        campaign = self.get_object()
        lead_ids = request.data.get('lead_ids', [])
        
        deleted_count, _ = CampaignLead.objects.filter(
            campaign=campaign,
            lead__id__in=lead_ids,
            organization=request.user.organization
        ).delete()

        campaign.refresh_from_db()

        return Response(
            {
                "message": f"Successfully removed {deleted_count} leads.",
                "total_enrolled": campaign.leads_count,
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'])
    def launch(self, request, pk=None):
        campaign = self.get_object()

        if campaign.connected_account_id:
            try:
                account = ConnectedEmailAccount._default_manager.get(id=campaign.connected_account_id)
            except ConnectedEmailAccount.DoesNotExist:
                return Response(
                    {"error": "Connected email account not found. Please reconnect your sender account in Settings."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if account.organization_id != request.user.organization_id:
                return Response(
                    {"error": "Selected sender account belongs to another organization."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            user_email = (request.user.email or '').lower()
            owned_by_user = (
                account.connected_by_id == request.user.id
                or account.connected_by_id is None
                or (account.email_address or '').lower() == user_email
            )
            if not owned_by_user:
                return Response(
                    {"error": "Selected sender account belongs to another user. Choose your own connected email account before launch."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if campaign.leads_count == 0:
            return Response(
                {"error": "No leads enrolled. Add leads before launching."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if campaign.status != 'ACTIVE':
            campaign.status = 'ACTIVE'
            campaign.save(update_fields=['status'])

        if django_settings.CELERY_TASK_ALWAYS_EAGER:
            process_active_leads_once()
        else:
            process_active_leads.delay()

        return Response(
            {"message": "Campaign launched. Processing queue triggered."},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        campaign = self.get_object()
        campaign.status = 'PAUSED'
        campaign.save()
        return Response({'status': 'Campaign paused'})

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        campaign = self.get_object()
        campaign.status = 'ACTIVE'
        campaign.save()
        return Response({'status': 'Campaign resumed'})


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
    queryset = EmailTemplate.objects.all()
    serializer_class = EmailTemplateSerializer

    def get_queryset(self):
        return EmailTemplate.objects.filter(organization=self.request.user.organization)

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)


class WebhookView(APIView):
    permission_classes = [AllowAny]

    @staticmethod
    def _extract_bounce_details(payload):
        # This is a placeholder. The full implementation is complex and depends on the email provider.
        # A real implementation would parse the payload to extract bounce details.
        return {}

    def post(self, request, *args, **kwargs):
        # This is a placeholder. The full implementation would handle various webhook events.
        logger.info(f"Received webhook: {request.data.get('event')}")
        return Response({"status": "received"}, status=status.HTTP_200_OK)


class DashboardAnalyticsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        # This is a placeholder. A full implementation would aggregate and return analytics data.
        return Response({"message": "Analytics data goes here."}, status=status.HTTP_200_OK)