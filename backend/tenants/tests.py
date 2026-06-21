import json
from unittest.mock import patch

from django.http import JsonResponse
from django.test import RequestFactory, TestCase

from tenants.security import RateLimitMiddleware


class FakeRedisClient:
    def __init__(self):
        self.counts = {}
        self.expiries = {}
        self.ttl_value = 60

    def incr(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        return self.counts[key]

    def expire(self, key, seconds):
        self.expiries[key] = seconds
        return True

    def ttl(self, key):
        return self.ttl_value


class RateLimitMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        RateLimitMiddleware._requests = {}
        RateLimitMiddleware._redis_client = None
        RateLimitMiddleware._redis_client_checked = False

    def _build_request(self, path='/api/v1/leads/', ip='203.0.113.10'):
        request = self.factory.get(path)
        request.META['REMOTE_ADDR'] = ip
        return request

    def test_non_api_requests_are_ignored(self):
        middleware = RateLimitMiddleware(lambda request: JsonResponse({'ok': True}))

        response = middleware.process_request(self._build_request(path='/admin/'))

        self.assertIsNone(response)

    def test_login_endpoint_uses_stricter_redis_limit(self):
        middleware = RateLimitMiddleware(lambda request: JsonResponse({'ok': True}))
        fake_client = FakeRedisClient()
        request = self._build_request(path='/api/v1/auth/login/')

        with patch.object(RateLimitMiddleware, 'LOGIN_MAX_REQUESTS', 2), patch.object(
            RateLimitMiddleware,
            '_get_redis_client',
            return_value=fake_client,
        ):
            self.assertIsNone(middleware.process_request(request))
            self.assertIsNone(middleware.process_request(request))
            response = middleware.process_request(request)

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(json.loads(response.content.decode())['retry_after_seconds'], 60)
        self.assertIn('rate-limit:login:203.0.113.10', fake_client.expiries)

    def test_local_fallback_expires_old_entries(self):
        middleware = RateLimitMiddleware(lambda request: JsonResponse({'ok': True}))
        request = self._build_request()

        with patch.object(RateLimitMiddleware, 'DEFAULT_MAX_REQUESTS', 2), patch.object(
            RateLimitMiddleware,
            '_get_redis_client',
            return_value=None,
        ), patch('tenants.security.time.time', side_effect=[100.0, 110.0, 171.0, 172.0]):
            self.assertIsNone(middleware.process_request(request))
            self.assertIsNone(middleware.process_request(request))

            # The first two timestamps have aged out of the window by the third request.
            response = middleware.process_request(request)

        self.assertIsNone(response)
        self.assertEqual(len(RateLimitMiddleware._requests['default:203.0.113.10']), 1)
