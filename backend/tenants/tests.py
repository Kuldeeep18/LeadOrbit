from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from tenants.security import RateLimitMiddleware, get_client_ip


class ClientIpTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_uses_cloudflare_header_on_render(self):
        # Header shape Render (behind Cloudflare) actually sends.
        request = self.factory.get(
            '/api/v1/',
            HTTP_TRUE_CLIENT_IP='81.97.145.24',
            HTTP_X_FORWARDED_FOR='81.97.145.24, 172.71.195.88, 10.226.252.196',
            REMOTE_ADDR='10.226.252.196',
        )
        self.assertEqual(get_client_ip(request), '81.97.145.24')

    def test_ignores_spoofed_left_most_forwarded_for_entry(self):
        request = self.factory.get(
            '/api/v1/',
            HTTP_X_FORWARDED_FOR='1.2.3.4, 81.97.145.24, 172.18.0.5',
            REMOTE_ADDR='172.18.0.6',
        )
        self.assertEqual(get_client_ip(request), '81.97.145.24')

    def test_falls_back_to_remote_addr(self):
        request = self.factory.get('/api/v1/', REMOTE_ADDR='203.0.113.9')
        self.assertEqual(get_client_ip(request), '203.0.113.9')


class RateLimitMiddlewareTests(TestCase):
    def setUp(self):
        RateLimitMiddleware._requests.clear()

    def tearDown(self):
        RateLimitMiddleware._requests.clear()

    @override_settings(API_RATE_LIMIT_PER_MINUTE=2)
    def test_limits_each_client_separately(self):
        for _ in range(2):
            self.assertNotEqual(self.client.get('/api/v1/', HTTP_CF_CONNECTING_IP='81.97.145.24').status_code, 429)

        self.assertEqual(self.client.get('/api/v1/', HTTP_CF_CONNECTING_IP='81.97.145.24').status_code, 429)
        self.assertNotEqual(self.client.get('/api/v1/', HTTP_CF_CONNECTING_IP='81.97.145.25').status_code, 429)

    @override_settings(API_RATE_LIMIT_PER_MINUTE=0)
    def test_zero_disables_the_limit(self):
        for _ in range(5):
            self.assertNotEqual(self.client.get('/api/v1/').status_code, 429)
