from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import Campaign, CampaignLead
from .serializers import CampaignSerializer
from users.permissions import IsOrgManagerOrAdmin, IsOrgAdmin
from .utils import MERGE_TAG_FIELD_MAP, get_all_step_merge_tags

class CampaignViewSet(viewsets.ModelViewSet):
    queryset = Campaign.objects.all()
    serializer_class = CampaignSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Campaign.objects.filter(organization=self.request.user.organization)

    def get_permissions(self):
        if self.action in ['create', 'update', 'partial_update']:
            self.permission_classes = [IsAuthenticated, IsOrgManagerOrAdmin]
        elif self.action == 'destroy':
            self.permission_classes = [IsAuthenticated, IsOrgAdmin]
        else:
            self.permission_classes = [IsAuthenticated]
        return super().get_permissions()

    def perform_create(self, serializer):
        serializer.save(organization=self.request.user.organization)

    @action(detail=True, methods=['get'], url_path='validate-launch')
    def validate_launch(self, request, pk=None):
        campaign = self.get_object()
        tags = get_all_step_merge_tags(campaign)
        lead_fields = [MERGE_TAG_FIELD_MAP.get(t, t) for t in tags]

        enrolled_leads = campaign.enrolled_leads.select_related('lead')
        missing_by_field = {}
        incomplete_lead_ids = set()

        for field in lead_fields:
            missing = [
                clead.lead.id for clead in enrolled_leads
                if getattr(clead.lead, field, None) in (None, '')
            ]
            if missing:
                missing_by_field[field] = missing
                incomplete_lead_ids.update(missing)

        total_incomplete = len(incomplete_lead_ids)
        if total_incomplete > 0:
            return Response({
                'can_launch': False,
                'total_incomplete_leads': total_incomplete,
                'missing_fields': missing_by_field,
                'message': f"{total_incomplete} leads are missing data for merge tags."
            })
        return Response({'can_launch': True, 'message': 'All merge fields are present.'})