from unittest.mock import patch
from django.test import TestCase, override_settings
from django.core.exceptions import ValidationError
from tenants.models import Organization
from django.conf import settings
from rest_framework.test import APIClient
from campaigns.tasks import rewrite_email_links
from campaigns.gmail_service import build_unsubscribe_url

class MockDnsRdata:
    def __init__(self, target):
        self.target_text = target

    @property
    def target(self):
        class _Target:
            def to_text(self_inner):
                return self.target_text
        return _Target()

@override_settings(BACKEND_BASE_URL='https://leadorbit.onrender.com')
class CustomDomainModelTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Acme Corp")
        
    @patch('dns.resolver.Resolver.resolve')
    def test_valid_cname_configuration(self, mock_resolve):
        # Mocking dns.resolver to return a valid CNAME pointing to our target
        mock_resolve.return_value = [MockDnsRdata('leadorbit.onrender.com.')]
        
        self.org.custom_tracking_domain = 'track.acme.test'
        # Should not raise exception
        self.org.clean()
        self.org.save()
        self.assertEqual(self.org.custom_tracking_domain, 'track.acme.test')

    @patch('dns.resolver.Resolver.resolve')
    def test_invalid_cname_configuration(self, mock_resolve):
        mock_resolve.return_value = [MockDnsRdata('wrong.target.com.')]
        
        self.org.custom_tracking_domain = 'track.acme.test'
        with self.assertRaises(ValidationError) as ctx:
            self.org.clean()
        self.assertIn("CNAME record must point to", str(ctx.exception))

    @patch('dns.resolver.Resolver.resolve')
    def test_dns_validation_failures(self, mock_resolve):
        import dns.resolver
        mock_resolve.side_effect = dns.resolver.NXDOMAIN
        
        self.org.custom_tracking_domain = 'notexist.acme.test'
        with self.assertRaises(ValidationError) as ctx:
            self.org.clean()
        self.assertIn("Domain does not exist", str(ctx.exception))


from django.test import RequestFactory

@override_settings(DEBUG=False, ALLOWED_HOSTS=['track.acme.test', 'localhost', '127.0.0.1'])
class CustomDomainMiddlewareTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.factory = RequestFactory()
        self.org = Organization.objects.create(name="Acme Corp", custom_tracking_domain='track.acme.test')
        from backend.middleware import CustomDomainMiddleware
        self.middleware = CustomDomainMiddleware(lambda req: getattr(req, '_fake_response', None))

    def test_middleware_hostname_routing_tracking_endpoint(self):
        request = self.factory.get('/api/v1/clicks/track/', HTTP_HOST='track.acme.test')
        request._fake_response = "OK"
        response = self.middleware(request)
        self.assertEqual(response, "OK") # Allowed through

    def test_tenant_isolation_non_tracking_endpoint(self):
        request = self.factory.get('/api/v1/organizations/', HTTP_HOST='track.acme.test')
        response = self.middleware(request)
        self.assertEqual(response.status_code, 404)

    def test_default_tracking_fallback(self):
        request = self.factory.get('/api/v1/organizations/', HTTP_HOST='localhost')
        request._fake_response = "OK"
        response = self.middleware(request)
        self.assertEqual(response, "OK") # Allowed through


class CustomDomainURLGenerationTests(TestCase):
    def setUp(self):
        self.org_custom = Organization.objects.create(name="Custom Org", custom_tracking_domain='track.custom.test')
        self.org_default = Organization.objects.create(name="Default Org")
        
        # Need mock campaign/lead to test rewrite_email_links, or just use string checking
        from campaigns.models import Campaign, SequenceStep, CampaignLead
        from leads.models import Lead
        
        self.campaign = Campaign.objects.create(organization=self.org_custom, name="Test", status="ACTIVE", sent_count=0, bounced_count=0)
        self.step = SequenceStep.objects.create(organization=self.org_custom, campaign=self.campaign, step_order=1, channel_type="EMAIL")
        self.lead = Lead.objects.create(organization=self.org_custom, email="test@test.com")
        self.clead = CampaignLead.objects.create(
            organization=self.org_custom, campaign=self.campaign, lead=self.lead, current_step=self.step
        )

    def test_rewrite_email_links_with_custom_domain(self):
        html = '<a href="https://google.com">Google</a>'
        rewritten = rewrite_email_links(html, self.clead.id, self.step.id, organization=self.org_custom)
        self.assertIn('https://track.custom.test/api/v1/clicks/track/?t=', rewritten)

    def test_rewrite_email_links_default_fallback(self):
        html = '<a href="https://google.com">Google</a>'
        rewritten = rewrite_email_links(html, self.clead.id, self.step.id, organization=self.org_default)
        self.assertIn('/api/v1/clicks/track/', rewritten)
        self.assertNotIn('track.custom.test', rewritten)

    def test_build_unsubscribe_url_with_custom_domain(self):
        url = build_unsubscribe_url(self.lead, organization=self.org_custom)
        self.assertIn('https://track.custom.test/api/v1/unsubscribe/', url)
