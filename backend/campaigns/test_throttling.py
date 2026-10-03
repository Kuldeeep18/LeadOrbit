from django.core.cache import cache
from rest_framework.test import APITestCase
from rest_framework import status
from tenants.security import RateLimitMiddleware


class AuthenticatedThrottleTestCase(APITestCase):
    """
    Shared setup: registers a fresh user + organization via the real API
    (not direct model creation) and authenticates the test client, so
    these tests stay valid even if model fields change later.
    """

    def setUp(self):
        cache.clear()
        RateLimitMiddleware._requests.clear()
        self.addCleanup(cache.clear)
        self.addCleanup(RateLimitMiddleware._requests.clear)
        register_response = self.client.post(
            '/api/v1/auth/register/',
            {
                'email': 'campaign_throttle_user@example.com',
                'password': 'StrongPass123!',
                'organization_name': 'Campaign Throttle Org',
            },
            format='json',
        )
        self.assertEqual(
            register_response.status_code,
            status.HTTP_201_CREATED,
            msg=f'Setup registration failed: {register_response.content}',
        )
        access_token = register_response.data['access']
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')


class CampaignLaunchThrottleTests(AuthenticatedThrottleTestCase):
    """
    Covers issue #18: campaign launch endpoint must throttle per
    authenticated user, independent of business-logic outcomes
    (e.g. "no leads enrolled" 400 responses still count toward the limit).
    """

    def setUp(self):
        super().setUp()
        create_response = self.client.post(
            '/api/v1/campaigns/',
            {'name': 'Throttle Test Campaign'},
            format='json',
        )
        self.assertEqual(
            create_response.status_code,
            status.HTTP_201_CREATED,
            msg=f'Setup campaign creation failed: {create_response.content}',
        )
        self.campaign_id = create_response.data['id']

    def test_launch_allowed_within_limit(self):
        response = self.client.post(f'/api/v1/campaigns/{self.campaign_id}/launch/')
        self.assertNotEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_launch_blocked_after_limit(self):
        """
        Campaign launch scope is configured at 20/min. The 21st request
        must be throttled even though earlier requests may return 400
        (no leads enrolled) rather than 200.
        """
        last_response = None
        for _ in range(21):
            last_response = self.client.post(f'/api/v1/campaigns/{self.campaign_id}/launch/')
        self.assertEqual(last_response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_other_campaign_actions_not_throttled_by_launch_scope(self):
        """
        Exhausting the launch limit must not affect unrelated actions
        (enroll, pause, metrics) on the same viewset.
        """
        for _ in range(21):
            self.client.post(f'/api/v1/campaigns/{self.campaign_id}/launch/')
        metrics_response = self.client.get(f'/api/v1/campaigns/{self.campaign_id}/metrics/')
        self.assertNotEqual(metrics_response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


class AIDraftThrottleTests(AuthenticatedThrottleTestCase):
    """
    Covers issue #18: AI draft generation endpoint must throttle per
    authenticated user to protect AI provider spend/quota, including
    when falling back to the local deterministic draft (no API key set).
    """

    def test_ai_generate_allowed_within_limit(self):
        response = self.client.post(
            '/api/v1/campaigns/ai-generate/',
            {'prompt': 'Write a short intro email'},
            format='json',
        )
        self.assertNotEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    def test_ai_generate_blocked_after_limit(self):
        """
        AI draft scope is configured at 15/min. The 16th request must
        be throttled.
        """
        last_response = None
        for _ in range(16):
            last_response = self.client.post(
                '/api/v1/campaigns/ai-generate/',
                {'prompt': 'Write a short intro email'},
                format='json',
            )
        self.assertEqual(last_response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)