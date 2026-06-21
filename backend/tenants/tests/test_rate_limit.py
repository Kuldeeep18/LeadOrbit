from django.test import TestCase, RequestFactory
from tenants.security import RateLimitMiddleware


class RateLimitTests(TestCase):
    def setUp(self):
        RateLimitMiddleware._requests = {}
        self.factory = RequestFactory()
        self.middleware = RateLimitMiddleware(lambda request: None)

    def test_api_request_allowed(self):
        request = self.factory.get("/api/test/")
        response = self.middleware.process_request(request)

        self.assertIsNone(response)

    def test_rate_limit_blocks_after_threshold(self):
        # Use a very small limit for testing
        self.middleware.DEFAULT_LIMIT = (2, 60)

        request = self.factory.get("/api/test/")

        # First two requests should pass
        self.assertIsNone(self.middleware.process_request(request))
        self.assertIsNone(self.middleware.process_request(request))

        # Third request should be blocked
        response = self.middleware.process_request(request)

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 429)