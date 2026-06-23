from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Campaign, CampaignLead, EmailTemplate
from .serializers import CampaignSerializer, EmailTemplateSerializer, CampaignLeadSerializer




class CampaignViewSet(viewsets.ModelViewSet):
    queryset = Campaign.objects.all()
    serializer_class = CampaignSerializer

    def get_queryset(self):
        return self.queryset.filter(organization=self.request.user.organization)

    @action(detail=True, methods=['post'])
    def launch(self, request, pk=None):
        campaign = self.get_object()
        campaign.status = 'ACTIVE'
        campaign.save()
        return Response({'status': 'Campaign launched'})

    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        campaign = self.get_object()
        campaign.status = 'PAUSED'
        campaign.save()
        return Response({'status': 'Campaign paused'})

    @action(detail=True, methods=['post'])
    def add_leads(self, request, pk=None):
        campaign = self.get_object()
        leads = request.data.get('leads', [])
        for lead_id in leads:
            CampaignLead.objects.get_or_create(campaign=campaign, lead_id=lead_id, organization=request.user.organization)
        return Response({'status': 'Leads added'})

    @action(detail=True, methods=['post'])
    def remove_leads(self, request, pk=None):
        campaign = self.get_object()
        leads = request.data.get('leads', [])
        CampaignLead.objects.filter(campaign=campaign, lead_id__in=leads).delete()
        return Response({'status': 'Leads removed'})

class EmailTemplateViewSet(viewsets.ModelViewSet):
    queryset = EmailTemplate.objects.all()
    serializer_class = EmailTemplateSerializer

    def get_queryset(self):
        return self.queryset.filter(organization=self.request.user.organization)