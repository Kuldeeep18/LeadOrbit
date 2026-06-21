from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from leads.models import BlockedDomain, Lead, Tag
from tenants.middleware import TenantMiddleware, get_current_tenant
from tenants.models import Organization
from users.models import User


class TenantIsolationTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = TenantMiddleware()
        self.org_a = Organization.objects.create(name='Org A')
        self.org_b = Organization.objects.create(name='Org B')
        self.user_a = User.objects.create_user(
            email='a@example.com',
            password='StrongPass123!',
            organization=self.org_a,
            role=User.ROLE_ADMIN,
        )
        self.user_b = User.objects.create_user(
            email='b@example.com',
            password='StrongPass123!',
            organization=self.org_b,
            role=User.ROLE_ADMIN,
        )
        self._clear_tenant()

    def tearDown(self):
        self._clear_tenant()

    def _clear_tenant(self):
        from tenants import middleware as tenant_middleware

        tenant_middleware._thread_locals.__dict__.pop('tenant', None)

    def _set_tenant(self, user):
        request = self.factory.get('/')
        request.user = user
        self.middleware.process_request(request)
        return request

    def test_get_current_tenant_defaults_to_none(self):
        self.assertIsNone(get_current_tenant())

    def test_organization_can_be_created(self):
        organization = Organization.objects.create(name='New Org')
        self.assertEqual(organization.name, 'New Org')
        self.assertIsNotNone(organization.id)

    def test_organization_ids_are_unique_for_same_name(self):
        first = Organization.objects.create(name='Shared Name')
        second = Organization.objects.create(name='Shared Name')
        self.assertNotEqual(first.id, second.id)

    def test_middleware_sets_tenant_for_authenticated_user(self):
        request = self._set_tenant(self.user_a)
        self.assertEqual(get_current_tenant(), self.org_a)
        self.middleware.process_response(request, HttpResponse())
        self._clear_tenant()

    def test_middleware_ignores_anonymous_users(self):
        request = self.factory.get('/')
        request.user = AnonymousUser()
        self.middleware.process_request(request)
        self.assertIsNone(get_current_tenant())
        self.middleware.process_response(request, HttpResponse())

    def test_middleware_clears_tenant_after_response(self):
        request = self._set_tenant(self.user_a)
        self.assertEqual(get_current_tenant(), self.org_a)
        self.middleware.process_response(request, HttpResponse())
        self.assertIsNone(get_current_tenant())

    def test_lead_manager_returns_all_records_without_tenant(self):
        Lead.objects.create(organization=self.org_a, email='a-lead@example.com')
        Lead.objects.create(organization=self.org_b, email='b-lead@example.com')

        emails = {lead.email for lead in Lead.objects.all()}
        self.assertEqual(emails, {'a-lead@example.com', 'b-lead@example.com'})

    def test_lead_manager_filters_by_tenant_context(self):
        Lead.objects.create(organization=self.org_a, email='a-lead@example.com')
        Lead.objects.create(organization=self.org_b, email='b-lead@example.com')

        request = self._set_tenant(self.user_a)
        emails = {lead.email for lead in Lead.objects.all()}
        self.assertEqual(emails, {'a-lead@example.com'})
        self.middleware.process_response(request, HttpResponse())

    def test_tenant_model_save_requires_tenant_or_explicit_organization(self):
        with self.assertRaises(ValueError):
            Lead.objects.create(email='missing-org@example.com')

    def test_tenant_model_save_uses_current_tenant_when_organization_missing(self):
        request = self._set_tenant(self.user_a)
        lead = Lead.objects.create(email='tenant-assigned@example.com')
        self.assertEqual(lead.organization, self.org_a)
        self.middleware.process_response(request, HttpResponse())

    def test_tenant_scoped_models_stay_isolated_across_organizations(self):
        request = self._set_tenant(self.user_a)
        Tag.objects.create(organization=self.org_a, name='Hot')
        Tag.objects.create(organization=self.org_b, name='Cold')

        tags = {tag.name for tag in Tag.objects.all()}
        self.assertEqual(tags, {'Hot'})
        self.middleware.process_response(request, HttpResponse())

    def test_blocked_domains_remain_organization_scoped(self):
        request = self._set_tenant(self.user_a)
        BlockedDomain.objects.create(organization=self.org_a, domain='a.test')
        BlockedDomain.objects.create(organization=self.org_b, domain='b.test')

        domains = {domain.domain for domain in BlockedDomain.objects.all()}
        self.assertEqual(domains, {'a.test'})
        self.middleware.process_response(request, HttpResponse())
