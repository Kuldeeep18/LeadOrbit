from rest_framework import status
from rest_framework.test import APITestCase

from leads.models import Lead, LeadTag, Tag
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

    def test_list_leads_supports_search_across_core_fields(self):
        search_lead = Lead.objects.create(
            organization=self.org_a,
            email='alice@example.com',
            first_name='Alice',
            last_name='Stone',
            company='Acme Labs',
        )
        Lead.objects.create(
            organization=self.org_b,
            email='alice@other-org.com',
            first_name='Alice',
            last_name='Stone',
            company='Acme Labs',
        )

        self.client.force_authenticate(self.user_a)

        for query in ['alice', 'stone', 'acme', 'alice@example.com']:
            with self.subTest(query=query):
                response = self.client.get('/api/v1/leads/', {'search': query})
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                emails = {item['email'] for item in response.data}
                self.assertIn(search_lead.email, emails)
                self.assertNotIn('alice@other-org.com', emails)

    def test_list_leads_supports_tag_filtering_with_tenant_isolation(self):
        vip_tag = Tag.objects.create(
            organization=self.org_a,
            name='VIP',
        )
        LeadTag.objects.create(
            organization=self.org_a,
            lead=self.lead_a,
            tag=vip_tag,
        )
        lead_without_tag = Lead.objects.create(
            organization=self.org_a,
            email='untagged@example.com',
            first_name='No',
            last_name='Tag',
        )

        org_b_tag = Tag.objects.create(
            organization=self.org_b,
            name='VIP',
        )
        Lead.objects.create(
            organization=self.org_b,
            email='other-org-vip@example.com',
            first_name='Other',
            last_name='Org',
        )
        LeadTag.objects.create(
            organization=self.org_b,
            lead=self.lead_b,
            tag=org_b_tag,
        )

        self.client.force_authenticate(self.user_a)
        response = self.client.get('/api/v1/leads/', {'tag': str(vip_tag.id)})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        emails = {item['email'] for item in response.data}
        self.assertIn(self.lead_a.email, emails)
        self.assertNotIn(lead_without_tag.email, emails)
        self.assertNotIn('other-org-vip@example.com', emails)
