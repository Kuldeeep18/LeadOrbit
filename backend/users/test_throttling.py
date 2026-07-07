from tenants.security import RateLimitMiddleware
from django.core.cache import cache
from rest_framework.test import APITestCase
from rest_framework import status


class SignupThrottleTests(APITestCase):
    """
    Covers issue #18: signup endpoint must throttle unauthenticated
    requests by IP, separately from other throttle scopes.
    """

    def setUp(self):
        cache.clear()
        RateLimitMiddleware._requests.clear()
        self.addCleanup(cache.clear)
        self.addCleanup(RateLimitMiddleware._requests.clear)

    def _register_payload(self, suffix):
        return {
            'email': f'throttle_signup_{suffix}@example.com',
            'password': 'StrongPass123!',
            'organization_name': f'Throttle Org {suffix}',
        }

    def test_signup_allowed_within_limit(self):
        """First request under the signup limit should not be throttled."""
        response = self.client.post(
            '/api/v1/auth/register/',
            self._register_payload('ok'),
            format='json',
        )
        self.assertNotEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_signup_blocked_after_limit(self):
        """
        Signup scope is configured at 5/min. The 6th request in the same
        window must be throttled regardless of payload validity.
        """
        last_response = None
        for i in range(6):
            last_response = self.client.post(
                '/api/v1/auth/register/',
                self._register_payload(f'block{i}'),
                format='json',
            )
        self.assertEqual(last_response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_login_throttle_is_independent_of_signup_throttle(self):
        """
        Exhausting the signup limit must not affect the login endpoint's
        separate throttle scope (proves scoping works, not just a shared
        global limiter).
        """
        for i in range(6):
            self.client.post(
                '/api/v1/auth/register/',
                self._register_payload(f'iso{i}'),
                format='json',
            )
        login_response = self.client.post(
            '/api/v1/token/',
            {'email': 'nonexistent@example.com', 'password': 'wrong'},
            format='json',
        )
        # Should be 401 (bad credentials), not 429 — proves separate scope.
        self.assertEqual(login_response.status_code, status.HTTP_401_UNAUTHORIZED)


class LoginThrottleTests(APITestCase):
    """
    Covers issue #18: login endpoint must throttle unauthenticated
    requests by IP to mitigate brute-force attempts.
    """

    def setUp(self):
        cache.clear()
        RateLimitMiddleware._requests.clear()
        self.addCleanup(cache.clear)
        self.addCleanup(RateLimitMiddleware._requests.clear)

    def test_login_allowed_within_limit(self):
        response = self.client.post(
            '/api/v1/token/',
            {'email': 'nobody@example.com', 'password': 'wrong'},
            format='json',
        )
        self.assertNotEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_login_blocked_after_limit(self):
        """
        Login scope is configured at 10/min. The 11th request in the same
        window must be throttled regardless of credential validity.
        """
        last_response = None
        for _ in range(11):
            last_response = self.client.post(
                '/api/v1/token/',
                {'email': 'nobody@example.com', 'password': 'wrong'},
                format='json',
            )
        self.assertEqual(last_response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)