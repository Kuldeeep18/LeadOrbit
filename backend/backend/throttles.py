"""
Custom DRF throttle classes for sensitive endpoints.

Each class maps to a named "scope" whose rate is configured centrally in
settings.py under REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"], so limits can
be tuned without touching view code.
"""
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class LoginRateThrottle(AnonRateThrottle):
    """
    Throttles login attempts by client IP, always — even if a stale or
    unrelated Bearer token is attached to the request. Login should stay
    IP-limited regardless of auth state, since the whole point is to
    protect the endpoint itself against brute-force attempts.
    """
    scope = 'login'

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }


class SignupRateThrottle(AnonRateThrottle):
    """
    Throttles account/organization signups by client IP, always — same
    reasoning as LoginRateThrottle above.
    """
    scope = 'signup'

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request),
        }


class CampaignLaunchThrottle(UserRateThrottle):
    """Throttles campaign launches per authenticated user."""
    scope = 'campaign_launch'


class AIDraftThrottle(UserRateThrottle):
    """Throttles AI draft generation per authenticated user to protect AI spend/quota."""
    scope = 'ai_draft'