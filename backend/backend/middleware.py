import logging
from django.utils.deprecation import MiddlewareMixin
from django.http import HttpResponseNotFound
from django.conf import settings
from urllib.parse import urlparse
from tenants.models import Organization
from tenants.middleware import _thread_locals

logger = logging.getLogger(__name__)

class CustomDomainMiddleware(MiddlewareMixin):
    """
    Middleware that intercepts requests with custom domains in the Host header,
    identifies the associated Organization, and restricts access to ONLY
    the tracking endpoints, rewriting/routing them to existing handlers.
    """
    
    TRACKING_ENDPOINTS = (
        '/api/v1/clicks/track/',
        '/api/v1/webhooks/email/',
        '/api/v1/unsubscribe/',
    )

    def process_request(self, request):
        host = request.get_host().split(':')[0].lower()
        base_url = getattr(settings, 'BACKEND_BASE_URL', 'http://localhost:8000')
        parsed_base = urlparse(base_url)
        default_host = (parsed_base.hostname or 'localhost').lower()

        # If the request comes via the default host or localhost, skip custom domain processing
        if host == default_host or host == '127.0.0.1' or host == 'localhost':
            return None

        # Check if the host matches a custom tracking domain
        try:
            org = Organization.objects.get(custom_tracking_domain=host)
        except Organization.DoesNotExist:
            # If no matching organization exists, continue normal request processing.
            return None

        # Custom domain matched. Identify the correct tenant.
        _thread_locals.tenant = org

        # Enforce strict tenant isolation: A custom domain must ONLY access tracking resources.
        is_tracking_endpoint = False
        for endpoint in self.TRACKING_ENDPOINTS:
            if request.path.startswith(endpoint):
                is_tracking_endpoint = True
                break
        
        if not is_tracking_endpoint:
            logger.warning(f"Blocked non-tracking access on custom domain {host} for path {request.path}")
            return HttpResponseNotFound("Not Found")
            
        # The request will naturally proceed to the existing tracking handlers
        # preserving the request method and query parameters.
        return None
