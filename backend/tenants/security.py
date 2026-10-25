"""
Security middleware for rate limiting and request hardening.
"""
import ipaddress
import logging
import threading
import time

from django.conf import settings
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


def _parse_ip(value):
    try:
        return ipaddress.ip_address((value or '').strip().strip('[]'))
    except ValueError:
        return None


# Set by Cloudflare's edge, which overwrites any client-supplied value. Render
# sits behind Cloudflare, and so does the Docker stack when it runs through a
# Cloudflare Tunnel; deploy/Caddyfile strips both headers from direct traffic.
TRUSTED_CLIENT_IP_HEADERS = ('HTTP_CF_CONNECTING_IP', 'HTTP_TRUE_CLIENT_IP')


def get_client_ip(request):
    """
    Best-effort client IP for rate limiting.

    Without a Cloudflare header, use the right-most public address in
    X-Forwarded-For: proxies append the address they saw, while left-most
    entries are client-supplied and trivially spoofed.
    """
    for header in TRUSTED_CLIENT_IP_HEADERS:
        ip = _parse_ip(request.META.get(header))
        if ip:
            return str(ip)

    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    for raw in reversed(forwarded.split(',')):
        ip = _parse_ip(raw)
        if ip and ip.is_global:
            return str(ip)
    return request.META.get('REMOTE_ADDR', '0.0.0.0')


class RateLimitMiddleware(MiddlewareMixin):
    """
    Simple in-memory, per-process rate limiter for API endpoints.
    Limits each client IP to API_RATE_LIMIT_PER_MINUTE requests per minute
    (0 disables it).
    """
    WINDOW_SECONDS = 60
    # { ip_address: [timestamp1, timestamp2, ...] }
    _requests = {}
    _lock = threading.Lock()
    _last_sweep = 0.0

    def process_request(self, request):
        if not request.path.startswith('/api/'):
            return None

        max_requests = int(getattr(settings, 'API_RATE_LIMIT_PER_MINUTE', 100) or 0)
        if max_requests <= 0:
            return None

        ip = get_client_ip(request)
        now = time.time()
        with self._lock:
            self._sweep_idle_clients(now)
            recent = [t for t in self._requests.get(ip, []) if now - t < self.WINDOW_SECONDS]
            if len(recent) >= max_requests:
                self._requests[ip] = recent
                limited = True
            else:
                recent.append(now)
                self._requests[ip] = recent
                limited = False

        if limited:
            logger.warning("Rate limit exceeded for IP: %s", ip)
            return JsonResponse(
                {'error': 'Too many requests. Please slow down.'},
                status=429,
            )
        return None

    @classmethod
    def _sweep_idle_clients(cls, now):
        """Forget clients that have been quiet for a full window so memory stays bounded."""
        if now - cls._last_sweep < cls.WINDOW_SECONDS:
            return
        cls._last_sweep = now
        for ip in [ip for ip, stamps in cls._requests.items() if not stamps or now - stamps[-1] >= cls.WINDOW_SECONDS]:
            del cls._requests[ip]


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
