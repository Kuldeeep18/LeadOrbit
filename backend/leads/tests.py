from django.db import connection
from rest_framework import status
from rest_framework.test import APITestCase

from campaigns.models import Campaign, SequenceStep, CampaignLead
from leads.models import Lead
from leads.tasks import import_leads_from_csv
from tenants.models import Organization
from users.models import User


class LeadImportTests(APITestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name='Import Org')

    def test_import_handles_bom_spaces_and_semicolon_delimiter(self):
        csv_data = (
            "\ufeffEmail Address;First Name;Last Name;Company Name;LinkedIn Url;Phone Number\n"
            "alice@example.com;Alice;Smith;Acme;https://linkedin.com/in/alice;+123456789\n"
        )

        import_leads_from_csv(csv_data, str(self.organization.id))

        lead = Lead.objects.get(organization=self.organization, email='alice@example.com')
        self.assertEqual(lead.first_name, 'Alice')
        self.assertEqual(lead.last_name, 'Smith')
        self.assertEqual(lead.company, 'Acme')
        self.assertEqual(lead.linkedin_url, 'https://linkedin.com/in/alice')
        self.assertEqual(lead.phone, '+123456789')

    def test_sensitive_lead_fields_are_encrypted_at_rest(self):
        lead = Lead.objects.create(
            organization=self.organization,
            email='secure@example.com',
            first_name='Secure',
            last_name='Lead',
            company='Acme',
            phone='+123456789',
            linkedin_url='https://linkedin.com/in/secure',
            custom_data={'notes': 'private', 'source': 'referral'},
        )

        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT first_name, last_name, company, phone, linkedin_url, custom_data FROM {Lead._meta.db_table} WHERE email = %s",
                [lead.email],
            )
            row = cursor.fetchone()

        self.assertIsNotNone(row)
        raw_first_name, raw_last_name, raw_company, raw_phone, raw_linkedin, raw_custom_data = row

        self.assertNotEqual(raw_first_name, 'Secure')
        self.assertNotEqual(raw_last_name, 'Lead')
        self.assertNotEqual(raw_company, 'Acme')
        self.assertNotEqual(raw_phone, '+123456789')
        self.assertNotEqual(raw_linkedin, 'https://linkedin.com/in/secure')
        self.assertNotIn('private', raw_custom_data)

        lead.refresh_from_db()
        self.assertEqual(lead.first_name, 'Secure')
        self.assertEqual(lead.last_name, 'Lead')
        self.assertEqual(lead.company, 'Acme')
        self.assertEqual(lead.phone, '+123456789')
        self.assertEqual(lead.linkedin_url, 'https://linkedin.com/in/secure')
        self.assertEqual(lead.custom_data['notes'], 'private')
        self.assertEqual(lead.custom_data['source'], 'referral')

    def test_imported_leads_auto_enroll_into_active_nurture_campaigns(self):
        campaign = Campaign.objects.create(
            organization=self.organization,
            name='Nurture Loop',
            status='ACTIVE',
            settings={
                'steps': [{'type': 'WAIT', 'delay_value': 1, 'delay_unit': 'days'}],
                'automation': {'auto_enroll_new_leads': True},
            },
        )
        SequenceStep.objects.create(
            organization=self.organization,
            campaign=campaign,
            step_order=1,
            channel_type='WAIT',
            delay_minutes=1440,
        )

        csv_data = (
            "Email,First Name,Company\n"
            "nurture@example.com,Nora,Acme\n"
        )

        import_leads_from_csv(csv_data, str(self.organization.id))

        lead = Lead.objects.get(organization=self.organization, email='nurture@example.com')
        self.assertTrue(
            CampaignLead.objects.filter(
                campaign=campaign,
                lead=lead,
            ).exists()
        )


class LeadIsolationAPITests(APITestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name='Org A')
        self.org_b = Organization.objects.create(name='Org B')
        self.user_a = User.objects.create_user(
            email='orga@example.com',
            password='StrongPass123!',
            organization=self.org_a,
            role='ADMIN',
        )
        self.user_b = User.objects.create_user(
            email='orgb@example.com',
            password='StrongPass123!',
            organization=self.org_b,
            role='ADMIN',
        )

        self.lead_a = Lead.objects.create(
            organization=self.org_a,
            email='a-lead@example.com',
            first_name='Lead',
            last_name='A',
        )
        self.lead_b = Lead.objects.create(
            organization=self.org_b,
            email='b-lead@example.com',
            first_name='Lead',
            last_name='B',
        )

    def test_list_leads_returns_only_current_users_organization(self):
        self.client.force_authenticate(self.user_a)
        response = self.client.get('/api/v1/leads/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        emails = {item['email'] for item in response.data}
        self.assertIn(self.lead_a.email, emails)
        self.assertNotIn(self.lead_b.email, emails)

    def test_create_lead_attaches_to_current_users_organization(self):
        self.client.force_authenticate(self.user_b)
        response = self.client.post(
            '/api/v1/leads/',
            {
                'email': 'new-orgb-lead@example.com',
                'first_name': 'New',
                'last_name': 'Lead',
                'company': 'OrgB Co',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        created = Lead.objects.get(email='new-orgb-lead@example.com')
        self.assertEqual(created.organization_id, self.org_b.id)

    def test_delete_all_removes_only_current_users_organization_leads(self):
        self.client.force_authenticate(self.user_a)
        response = self.client.delete('/api/v1/leads/delete-all/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(Lead.objects.filter(id=self.lead_a.id).exists())
        self.assertTrue(Lead.objects.filter(id=self.lead_b.id).exists())

    def test_sync_crm_records_creates_updates_and_keeps_tenant_isolation(self):
        shared_email = 'sync@example.com'
        org_a_lead = Lead.objects.create(
            organization=self.org_a,
            email=shared_email,
            first_name='Original',
            company='Old Co',
            custom_data={'owner': 'sales'},
        )
        org_b_lead = Lead.objects.create(
            organization=self.org_b,
            email=shared_email,
            first_name='Other Org',
            company='Other Co',
        )

        self.client.force_authenticate(self.user_a)
        response = self.client.post(
            '/api/v1/leads/sync-crm/',
            {
                'source': 'hubspot',
                'records': [
                    {
                        'email': shared_email,
                        'first_name': 'Updated',
                        'company': 'New Co',
                        'external_id': 'hubspot-123',
                        'custom_data': {'lifecycle_stage': 'lead'},
                    },
                    {
                        'email': 'new-sync@example.com',
                        'first_name': 'New',
                        'last_name': 'Lead',
                        'phone': '9876543210',
                        'global_unsubscribe': False,
                        'external_id': 'hubspot-456',
                    },
                    {
                        'first_name': 'Missing Email',
                    },
                ],
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['created'], 1)
        self.assertEqual(response.data['updated'], 1)
        self.assertEqual(response.data['skipped'], 1)
        self.assertEqual(len(response.data['errors']), 1)
        self.assertEqual(response.data['errors'][0]['index'], 2)

        org_a_lead.refresh_from_db()
        org_b_lead.refresh_from_db()

        self.assertEqual(org_a_lead.first_name, 'Updated')
        self.assertEqual(org_a_lead.company, 'New Co')
        self.assertEqual(org_a_lead.crm_source, 'hubspot')
        self.assertEqual(org_a_lead.crm_external_id, 'hubspot-123')
        self.assertIsNotNone(org_a_lead.crm_synced_at)
        self.assertEqual(org_a_lead.custom_data['owner'], 'sales')
        self.assertEqual(org_a_lead.custom_data['lifecycle_stage'], 'lead')

        self.assertEqual(org_b_lead.first_name, 'Other Org')
        self.assertEqual(org_b_lead.company, 'Other Co')
        self.assertIsNone(org_b_lead.crm_source)
