import csv
import io

from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from campaigns.models import Campaign, CampaignLead, SequenceStep
from leads.models import Lead
from tenants.models import Organization
from users.models import User


class CampaignExportLeadTests(APITestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Acme')
        self.user = User.objects.create_user(
            email='owner@acme.test',
            password='StrongPass123!',
            organization=self.organization,
            role='ADMIN',
        )
        self.client.force_authenticate(self.user)

    def test_export_leads_returns_campaign_metrics_as_csv(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='CSV export',
            status='ACTIVE',
        )
        step = SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=3,
            channel_type='EMAIL',
        )
        lead = Lead.objects.create(
            organization=self.organization,
            email='export@acme.test',
            first_name='Export',
            last_name='Lead',
        )
        CampaignLead.objects.create(
            organization=self.organization,
            campaign=campaign,
            lead=lead,
            current_step=step,
            status='REPLIED',
            last_sent_message_id='message-123',
            last_opened_at=timezone.now(),
            last_clicked_at=timezone.now(),
            last_replied_at=timezone.now(),
        )

        response = self.client.get(f'/api/v1/campaigns/{campaign.id}/export_leads/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('campaign_leads.csv', response['Content-Disposition'])

        content = b''.join(response.streaming_content).decode()
        rows = list(csv.reader(io.StringIO(content)))
        self.assertEqual(rows[0], [
            'email', 'first_name', 'last_name', 'status',
            'current_step_order', 'last_sent', 'opens', 'clicks', 'replies',
        ])
        self.assertEqual(rows[1], [
            'export@acme.test', 'Export', 'Lead', 'REPLIED', '3',
            'message-123', '1', '1', '1',
        ])

    def test_export_leads_does_not_expose_other_organizations(self):
        other_org = Organization.objects.create(name='Other')
        campaign = Campaign.objects.create(
            organization=other_org,
            name='Other campaign',
            status='ACTIVE',
        )

        response = self.client.get(f'/api/v1/campaigns/{campaign.id}/export_leads/')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
