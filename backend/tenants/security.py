"""
Security middleware for rate limiting and request hardening.
"""
import logging
import time

try:
    import redis
except ImportError:  # pragma: no cover - local fallback handles this case
    redis = None

from django.conf import settings as django_settings
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class RateLimitMiddleware(MiddlewareMixin):
    """
    API rate limiter backed by Redis when available.

    Falls back to a per-process in-memory store when Redis is unavailable so
    local development still works without hard failures.
    """

    _requests = {}
    _redis_client = None
    _redis_client_checked = False

    DEFAULT_MAX_REQUESTS = 100
    LOGIN_MAX_REQUESTS = 20
    REGISTER_MAX_REQUESTS = 10
    WINDOW_SECONDS = 60
    REDIS_URL_SETTING = 'RATE_LIMIT_REDIS_URL'

    def process_request(self, request):
        if not request.path.startswith('/api/'):
            return None

        ip = self._get_client_ip(request)
        limit_name, max_requests = self._get_limit_for_path(request.path)
        allowed, retry_after = self._is_request_allowed(limit_name, ip, max_requests)
        if not allowed:
            logger.warning(f"Rate limit exceeded for IP: {ip}")
            payload = {'error': 'Too many requests. Please slow down.'}
            if retry_after is not None:
                payload['retry_after_seconds'] = retry_after
            response = JsonResponse(payload, status=429)
            if retry_after is not None:
                response['Retry-After'] = str(retry_after)
            return response

        return None

    def _get_limit_for_path(self, path):
        normalized_path = path.rstrip('/') or '/'
        if normalized_path == '/api/v1/auth/login':
            return 'login', self.LOGIN_MAX_REQUESTS
        if normalized_path == '/api/v1/auth/register':
            return 'register', self.REGISTER_MAX_REQUESTS
        return 'default', self.DEFAULT_MAX_REQUESTS

    def _is_request_allowed(self, limit_name, ip, max_requests):
        redis_client = self._get_redis_client()
        if redis_client is not None:
            return self._check_redis_limit(redis_client, limit_name, ip, max_requests)
        return self._check_local_limit(limit_name, ip, max_requests)

    def _get_redis_client(self):
        if self._redis_client_checked:
            return self._redis_client

        self._redis_client_checked = True

        if redis is None:
            logger.info('Redis library is unavailable; using local rate limiting fallback.')
            return None

        redis_url = (
            getattr(django_settings, self.REDIS_URL_SETTING, '')
            or getattr(django_settings, 'REDIS_URL', '')
            or getattr(django_settings, 'CELERY_BROKER_URL', '')
        )
        if not redis_url.startswith(('redis://', 'rediss://')):
            logger.info('No Redis URL configured for rate limiting; using local fallback.')
            return None

        try:
            client = redis.Redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
            )
            client.ping()
            self._redis_client = client
            return client
        except Exception as exc:  # pragma: no cover - depends on the runtime env
            logger.warning('Redis rate limiter unavailable, using local fallback: %s', exc)
            self._redis_client = None
            return None

    def _check_redis_limit(self, client, limit_name, ip, max_requests):
        key = f'rate-limit:{limit_name}:{ip}'
        count = client.incr(key)
        if count == 1:
            client.expire(key, self.WINDOW_SECONDS)
        if count > max_requests:
            ttl = client.ttl(key)
            retry_after = ttl if isinstance(ttl, int) and ttl > 0 else self.WINDOW_SECONDS
            return False, retry_after
        return True, None

    def _check_local_limit(self, limit_name, ip, max_requests):
        now = time.time()
        key = f'{limit_name}:{ip}'
        timestamps = self._requests.get(key, [])
        cutoff = now - self.WINDOW_SECONDS
        timestamps = [timestamp for timestamp in timestamps if timestamp >= cutoff]

        if len(timestamps) >= max_requests:
            self._requests[key] = timestamps
            retry_after = int(max(1, self.WINDOW_SECONDS - (now - timestamps[0])))
            return False, retry_after

        timestamps.append(now)
        self._requests[key] = timestamps
        return True, None

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
