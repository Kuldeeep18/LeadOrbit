from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITestCase

from leads.models import BlockedDomain, Lead, Tag, LeadTag, LeadImportJob
from leads.tasks import import_leads_from_csv
from tenants.models import Organization
from users.models import User


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_user(org, email='user@example.com', password='StrongPass123!'):
    return User.objects.create_user(
        email=email,
        password=password,
        organization=org,
        role=User.ROLE_ADMIN,
    )


def _make_lead(org, email, **kwargs):
    return Lead.objects.create(organization=org, email=email, **kwargs)


def _make_tag(org, name, color='#6366f1'):
    return Tag.objects.create(organization=org, name=name, color=color)


# ── Existing tests (preserved) ─────────────────────────────────────────────────

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

    def test_import_stores_non_standard_headers_as_custom_variables(self):
        csv_data = (
            "email,first_name,Industry,Meeting Time,Lead Source\n"
            "bob@example.com,Bob,SaaS,10:30 AM,Referral\n"
        )

        import_leads_from_csv(csv_data, str(self.organization.id))

        lead = Lead.objects.get(organization=self.organization, email='bob@example.com')
        self.assertEqual(
            lead.custom_variables,
            {
                'industry': 'SaaS',
                'meeting_time': '10:30 AM',
                'lead_source': 'Referral',
            },
        )

    def test_import_records_validation_errors_in_history_job(self):
        job = LeadImportJob.objects.create(
            organization=self.organization,
            filename='audited-import.csv',
        )
        csv_data = (
            "email,first_name,Industry\n"
            "valid@example.com,Valid,SaaS\n"
            "invalid-email,Bad,Ops\n"
            ",Missing,Ops\n"
        )

        import_leads_from_csv(csv_data, str(self.organization.id), str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.total_rows, 3)
        self.assertEqual(job.imported_count, 1)
        self.assertEqual(job.failed_count, 2)
        self.assertEqual(len(job.error_log), 2)
        self.assertTrue(Lead.objects.filter(organization=self.organization, email='valid@example.com').exists())
        self.assertEqual(job.error_log[0]['error'], 'Invalid email format')
        self.assertEqual(job.error_log[1]['error'], 'Missing email address')

    def test_import_tracks_successful_duplicate_and_invalid_counts(self):
        job = LeadImportJob.objects.create(
            organization=self.organization,
            filename='summary-import.csv',
        )
        Lead.objects.create(organization=self.organization, email='existing@example.com', first_name='Old')
        csv_data = (
            "email,first_name\n"
            "new@example.com,New\n"
            "existing@example.com,Existing\n"
            "invalid-email,Invalid\n"
            ",Missing\n"
        )

        import_leads_from_csv(csv_data, str(self.organization.id), str(job.id))

        job.refresh_from_db()
        self.assertEqual(job.total_rows, 4)
        self.assertEqual(job.successful_count, 1)
        self.assertEqual(job.duplicate_count, 1)
        self.assertEqual(job.invalid_count, 1)
        self.assertEqual(job.failed_count, 1)
        self.assertEqual(job.imported_count, 2)


class LeadIsolationAPITests(APITestCase):
    def setUp(self):
        self.org_a = Organization.objects.create(name='Org A')
        self.org_b = Organization.objects.create(name='Org B')
        self.user_a = User.objects.create_user(
            email='orga@example.com',
            password='StrongPass123!',
            organization=self.org_a,
            role=User.ROLE_ADMIN,
        )
        self.user_b = User.objects.create_user(
            email='orgb@example.com',
            password='StrongPass123!',
            organization=self.org_b,
            role=User.ROLE_ADMIN,
        )
        self.member_a = User.objects.create_user(
            email='member-a@example.com',
            password='StrongPass123!',
            organization=self.org_a,
            role=User.ROLE_MEMBER,
        )
        self.manager_a = User.objects.create_user(
            email='manager-a@example.com',
            password='StrongPass123!',
            organization=self.org_a,
            role=User.ROLE_MANAGER,
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

    def test_member_can_list_but_cannot_create_leads(self):
        self.client.force_authenticate(self.member_a)

        list_response = self.client.get('/api/v1/leads/')
        create_response = self.client.post(
            '/api/v1/leads/',
            {'email': 'blocked-member-create@example.com'},
            format='json',
        )

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertFalse(Lead.objects.filter(email='blocked-member-create@example.com').exists())

    def test_member_cannot_delete_all_leads(self):
        self.client.force_authenticate(self.member_a)

        response = self.client.delete('/api/v1/leads/delete-all/')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertTrue(Lead.objects.filter(id=self.lead_a.id).exists())

    def test_manager_can_create_and_delete_organization_leads(self):
        self.client.force_authenticate(self.manager_a)

        create_response = self.client.post(
            '/api/v1/leads/',
            {'email': 'manager-created@example.com'},
            format='json',
        )
        delete_response = self.client.delete('/api/v1/leads/delete-all/')

        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(delete_response.status_code, status.HTTP_200_OK)
        self.assertFalse(Lead.objects.filter(organization=self.org_a).exists())
        self.assertTrue(Lead.objects.filter(id=self.lead_b.id).exists())

    def test_blocked_domain_create_normalizes_domain_for_current_organization(self):
        self.client.force_authenticate(self.user_a)

        response = self.client.post(
            '/api/v1/blocked-domains/',
            {'domain': 'HTTPS://Competitor.COM/path'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        blocked_domain = BlockedDomain.objects.get(organization=self.org_a)
        self.assertEqual(blocked_domain.domain, 'competitor.com')

    def test_blocked_domain_list_is_scoped_to_current_organization(self):
        BlockedDomain.objects.create(organization=self.org_a, domain='orga.test')
        BlockedDomain.objects.create(organization=self.org_b, domain='orgb.test')
        self.client.force_authenticate(self.user_a)

        response = self.client.get('/api/v1/blocked-domains/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        domains = {item['domain'] for item in response.data}
        self.assertEqual(domains, {'orga.test'})

    def test_import_history_endpoint_is_scoped_and_paginated(self):
        LeadImportJob.objects.create(
            organization=self.org_a,
            filename='orga.csv',
            total_rows=2,
            imported_count=1,
            failed_count=1,
            error_log=[{'row': 3, 'email': 'bad@example.com', 'error': 'Invalid email format'}],
        )
        LeadImportJob.objects.create(
            organization=self.org_b,
            filename='orgb.csv',
            total_rows=1,
            imported_count=1,
            failed_count=0,
            error_log=[],
        )

        self.client.force_authenticate(self.user_a)
        response = self.client.get('/api/v1/lead-import-jobs/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('results', response.data)
        self.assertEqual(response.data['count'], 1)
        self.assertEqual(response.data['results'][0]['filename'], 'orga.csv')


# ── New tests for Issue #244 ───────────────────────────────────────────────────

class TagColorTests(APITestCase):
    """Tags should persist a custom hex color and expose it via the API."""

    def setUp(self):
        self.org = Organization.objects.create(name='Color Org')
        self.user = _make_user(self.org)

    def test_create_tag_with_default_color(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post('/api/v1/tags/', {'name': 'VIP'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['color'], '#6366f1')

    def test_create_tag_with_custom_color(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post(
            '/api/v1/tags/', {'name': 'Hot Lead', 'color': '#ef4444'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(resp.data['color'], '#ef4444')

    def test_update_tag_color(self):
        tag = _make_tag(self.org, 'Old Color', color='#000000')
        self.client.force_authenticate(self.user)
        resp = self.client.patch(
            f'/api/v1/tags/{tag.id}/', {'color': '#22c55e'}, format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        tag.refresh_from_db()
        self.assertEqual(tag.color, '#22c55e')

    def test_tag_list_includes_color(self):
        _make_tag(self.org, 'Enterprise', color='#f59e0b')
        self.client.force_authenticate(self.user)
        resp = self.client.get('/api/v1/tags/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        colors = {t['color'] for t in resp.data}
        self.assertIn('#f59e0b', colors)

    def test_tag_scoped_to_organization(self):
        other_org = Organization.objects.create(name='Other Org')
        _make_tag(other_org, 'Hidden Tag', color='#ff0000')
        self.client.force_authenticate(self.user)
        resp = self.client.get('/api/v1/tags/')
        names = {t['name'] for t in resp.data}
        self.assertNotIn('Hidden Tag', names)


class LeadTagAssignTests(APITestCase):
    """POST /api/v1/leads/{id}/tags/ should reconcile the lead's tag set."""

    def setUp(self):
        self.org = Organization.objects.create(name='Tag Assign Org')
        self.user = _make_user(self.org, email='tagger@example.com')
        self.lead = _make_lead(self.org, 'tagged@example.com')
        self.tag_a = _make_tag(self.org, 'Tier A', color='#3b82f6')
        self.tag_b = _make_tag(self.org, 'Tier B', color='#10b981')
        self.tag_c = _make_tag(self.org, 'Tier C', color='#f59e0b')

    def _url(self):
        return f'/api/v1/leads/{self.lead.id}/tags/'

    def test_assign_tags_to_lead(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post(
            self._url(),
            {'tag_ids': [str(self.tag_a.id), str(self.tag_b.id)]},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = {t['name'] for t in resp.data}
        self.assertEqual(names, {'Tier A', 'Tier B'})
        self.assertEqual(LeadTag.objects.filter(lead=self.lead).count(), 2)

    def test_reassign_tags_replaces_previous_set(self):
        # Pre-assign tag_a
        LeadTag.objects.create(lead=self.lead, tag=self.tag_a, organization=self.org)
        self.client.force_authenticate(self.user)
        # Now assign only tag_c — tag_a should be removed
        resp = self.client.post(
            self._url(),
            {'tag_ids': [str(self.tag_c.id)]},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = {t['name'] for t in resp.data}
        self.assertEqual(names, {'Tier C'})
        self.assertFalse(LeadTag.objects.filter(lead=self.lead, tag=self.tag_a).exists())

    def test_assign_empty_list_removes_all_tags(self):
        LeadTag.objects.create(lead=self.lead, tag=self.tag_a, organization=self.org)
        self.client.force_authenticate(self.user)
        resp = self.client.post(self._url(), {'tag_ids': []}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(LeadTag.objects.filter(lead=self.lead).count(), 0)

    def test_assign_tags_from_other_org_are_silently_ignored(self):
        other_org = Organization.objects.create(name='Other')
        foreign_tag = _make_tag(other_org, 'Foreign')
        self.client.force_authenticate(self.user)
        resp = self.client.post(
            self._url(),
            {'tag_ids': [str(foreign_tag.id)]},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(LeadTag.objects.filter(lead=self.lead).count(), 0)

    def test_assign_tags_invalid_body_returns_400(self):
        self.client.force_authenticate(self.user)
        resp = self.client.post(self._url(), {'tag_ids': 'not-a-list'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_lead_serializer_returns_tag_colors(self):
        LeadTag.objects.create(lead=self.lead, tag=self.tag_a, organization=self.org)
        self.client.force_authenticate(self.user)
        resp = self.client.get(f'/api/v1/leads/{self.lead.id}/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        tags = resp.data['tags']
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0]['color'], '#3b82f6')


class LeadFilterTests(APITestCase):
    """GET /api/v1/leads/ with filter query params (Issue #244)."""

    def setUp(self):
        self.org = Organization.objects.create(name='Filter Org')
        self.user = _make_user(self.org, email='filter@example.com')
        self.tag_vip = _make_tag(self.org, 'VIP', color='#6366f1')
        self.tag_cold = _make_tag(self.org, 'Cold', color='#64748b')

        self.lead_active = _make_lead(self.org, 'active@example.com', global_unsubscribe=False)
        self.lead_unsub = _make_lead(self.org, 'unsub@example.com', global_unsubscribe=True)
        self.lead_vip = _make_lead(self.org, 'vip@example.com', global_unsubscribe=False)
        self.lead_cold = _make_lead(self.org, 'cold@example.com', global_unsubscribe=False)

        LeadTag.objects.create(lead=self.lead_vip, tag=self.tag_vip, organization=self.org)
        LeadTag.objects.create(lead=self.lead_cold, tag=self.tag_cold, organization=self.org)

    def _get(self, **params):
        self.client.force_authenticate(self.user)
        return self.client.get('/api/v1/leads/', params)

    def test_filter_by_status_active(self):
        resp = self._get(status='active')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        emails = {l['email'] for l in resp.data}
        self.assertNotIn('unsub@example.com', emails)
        self.assertIn('active@example.com', emails)

    def test_filter_by_status_unsubscribed(self):
        resp = self._get(status='unsubscribed')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        emails = {l['email'] for l in resp.data}
        self.assertIn('unsub@example.com', emails)
        self.assertNotIn('active@example.com', emails)

    def test_filter_by_single_tag(self):
        resp = self._get(tags=str(self.tag_vip.id))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        emails = {l['email'] for l in resp.data}
        self.assertIn('vip@example.com', emails)
        self.assertNotIn('cold@example.com', emails)
        self.assertNotIn('active@example.com', emails)

    def test_filter_by_multiple_tags_returns_leads_with_all_tags(self):
        # Assign both tags to lead_vip so it qualifies for both
        LeadTag.objects.create(lead=self.lead_vip, tag=self.tag_cold, organization=self.org)
        resp = self._get(tags=f'{self.tag_vip.id},{self.tag_cold.id}')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        emails = {l['email'] for l in resp.data}
        # lead_vip has both tags — should appear
        self.assertIn('vip@example.com', emails)
        # lead_cold only has tag_cold — should NOT appear (missing tag_vip)
        self.assertNotIn('cold@example.com', emails)

    def test_filter_by_created_after(self):
        resp = self._get(created_after='1970-01-01')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        # All leads were created after 1970; all should be returned
        self.assertGreaterEqual(len(resp.data), 4)

    def test_filter_by_created_before_far_future(self):
        resp = self._get(created_before='2099-12-31')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(resp.data), 4)

    def test_combined_tag_and_status_filter(self):
        resp = self._get(tags=str(self.tag_vip.id), status='active')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        emails = {l['email'] for l in resp.data}
        self.assertIn('vip@example.com', emails)
        self.assertNotIn('unsub@example.com', emails)
        self.assertNotIn('cold@example.com', emails)

    def test_no_filter_returns_all_org_leads(self):
        resp = self._get()
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 4)

    def test_filter_does_not_leak_other_org_leads(self):
        other_org = Organization.objects.create(name='Spy Org')
        _make_lead(other_org, 'spy@example.com')
        resp = self._get()
        emails = {l['email'] for l in resp.data}
        self.assertNotIn('spy@example.com', emails)
