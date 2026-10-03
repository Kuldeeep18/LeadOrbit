import time
import json
from django.core.cache import cache
from django.http import JsonResponse
from django.utils.deprecation import MiddlewareMixin


class RateLimitMiddleware(MiddlewareMixin):
    """
    Rate limiting middleware for API endpoints.
    """
    _requests = {}
    MAX_REQUESTS = 100  # per window
    WINDOW_SECONDS = 60
    
    # ─── Login-specific rate limiting ──────────────────────────────
    LOGIN_IP_MAX = 10  # Max login attempts per IP
    LOGIN_EMAIL_MAX = 5  # Max failed attempts before lockout
    LOCKOUT_SECONDS = 900  # 15 minutes

    def process_request(self, request):
        if not request.path.startswith('/api/'):
            return None
        
        ip = request.META.get('REMOTE_ADDR')
        
        # ─── Login-specific rate limiting ──────────────────────────────
        if request.path == '/api/v1/token/' and request.method == 'POST':
            # Get email from request body
            try:
                body = json.loads(request.body)
                email = body.get('email')
            except:
                email = None
            
            # IP-based rate limiting for login
            ip_key = f"login_attempts_ip_{ip}"
            ip_attempts = cache.get(ip_key, 0)
            if ip_attempts >= self.LOGIN_IP_MAX:
                return JsonResponse(
                    {'error': 'Too many login attempts from this IP. Try again later.'},
                    status=429
                )
            
            # Email-based lockout
            if email:
                lock_key = f"account_locked_{email}"
                if cache.get(lock_key):
                    return JsonResponse(
                        {'error': 'Account temporarily locked. Reset your password or try again later.'},
                        status=403
                    )
        
        # ─── Global rate limiting for all API endpoints ────────────────
        now = time.time()
        request_history = self._requests.setdefault(ip, [])
        request_history = [t for t in request_history if now - t < self.WINDOW_SECONDS]
        
        if len(request_history) >= self.MAX_REQUESTS:
            return JsonResponse(
                {'error': f'Rate limit exceeded. Maximum {self.MAX_REQUESTS} requests per {self.WINDOW_SECONDS} seconds.'},
                status=429
            )
        
        request_history.append(now)
        self._requests[ip] = request_history
        return None


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

        