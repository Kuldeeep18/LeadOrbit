"""
Security middleware for rate limiting and request hardening.
"""
import time
import logging
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)

class RateLimitMiddleware(MiddlewareMixin):
    """
    Simple in-memory rate limiter for API endpoints.
    Limits each IP to a max number of requests per window.
    """
    # { ip_address: [timestamp1, timestamp2, ...] }
    _requests = {}
    MAX_REQUESTS = 100  # per window
    WINDOW_SECONDS = 60

    def process_request(self, request):
        if not request.path.startswith('/api/'):
            return None

        ip = self._get_client_ip(request)
        now = time.time()

        # Clean old entries
        if ip in self._requests:
            self._requests[ip] = [t for t in self._requests[ip] if now - t < self.WINDOW_SECONDS]
        else:
            self._requests[ip] = []

        if len(self._requests[ip]) >= self.MAX_REQUESTS:
            logger.warning(f"Rate limit exceeded for IP: {ip}")
            return JsonResponse(
                {'error': 'Too many requests. Please slow down.'},
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
