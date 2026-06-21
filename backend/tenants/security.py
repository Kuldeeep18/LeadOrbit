"""
Security middleware for rate limiting and request hardening.
"""
import time
import logging
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin
import redis
from django.conf import settings

logger = logging.getLogger(__name__)

class RateLimitMiddleware(MiddlewareMixin):
    """
    Simple in-memory rate limiter for API endpoints.
    Limits each IP to a max number of requests per window.
    """
    def _get_redis_client(self):
        return redis.from_url(settings.REDIS_URL)
    
    RATE_LIMITS = {
    "/api/v1/auth/login/": (10, 60),
    "/api/v1/auth/register/": (5, 60),
    }
    DEFAULT_LIMIT = (100, 60)
    # { ip_address: [timestamp1, timestamp2, ...] }
    _requests = {}
    MAX_REQUESTS = 100  # per window
    WINDOW_SECONDS = 60

    def process_request(self, request):
        if not request.path.startswith('/api/'):
            return None

        ip = self._get_client_ip(request)

        limit, window = self.RATE_LIMITS.get(
            request.path,
            self.DEFAULT_LIMIT
        )

        key = f"ratelimit:{request.path}:{ip}"

        try:
            client = self._get_redis_client()
            count = client.incr(key)

            if count == 1:
                client.expire(key, window)

            if count > limit:
                return JsonResponse(
                    {"error": "Too many requests"},
                    status=429
                )

        except Exception:
            logger.warning(
                "Redis unavailable, using fallback",
                exc_info=True,
            )

            now = time.time()

            if ip in self._requests:
                self._requests[ip] = [
                    t for t in self._requests[ip]
                    if now - t < window
                ]
            else:
                self._requests[ip] = []

            if len(self._requests[ip]) >= limit:
                return JsonResponse(
                    {"error": "Too many requests"},
                 status=429
                )

            self._requests[ip].append(now)

        return None

    def _get_client_ip(self, request):
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded:
            return x_forwarded.split(',')[0].strip()
        return request.META.get('REMOTE_ADDR', '0.0.0.0')


class SecurityHeadersMiddleware(MiddlewareMixin):
    """
    Adds standard security headers to all responses.
    """
    def process_response(self, request, response):
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'DENY'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        return response
