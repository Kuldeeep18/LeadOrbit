import threading
from urllib.parse import urlsplit

from django.conf import settings
from django.db import models
from django.http import HttpResponseBadRequest
from django.utils.deprecation import MiddlewareMixin

_thread_locals = threading.local()

def get_current_tenant():
    return getattr(_thread_locals, 'tenant', None)

class TenantMiddleware(MiddlewareMixin):
    """
    Middleware that reads the preferred organization from the User's session/token
    and sets it globally for the request thread so TenantModels can auto-filter.
    """
    def process_request(self, request):
        _thread_locals.tenant = None
        if hasattr(request, 'user') and request.user.is_authenticated:
            _thread_locals.tenant = request.user.organization

    def process_response(self, request, response):
        if hasattr(_thread_locals, 'tenant'):
            del _thread_locals.tenant
        return response

class CustomDomainMiddleware(MiddlewareMixin):
    """Route branded tracking hostnames to the existing click-tracking endpoint."""

    def process_request(self, request):
        host = (request.get_host() or '').split(':', 1)[0].lower()
        if not host:
            return None

        tenant = get_current_tenant()
        if tenant is None and hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
            tenant = request.user.organization

        if tenant is None:
            return None

        custom_domain = getattr(tenant, 'custom_tracking_domain', None) or ''
        if not custom_domain:
            return None

        if host != custom_domain.lower():
            return None

        if getattr(settings, 'CUSTOM_TRACKING_DOMAIN_VALIDATION', True):
            from .models import Organization
            try:
                from dns import resolver
            except ImportError:
                return None

            if not getattr(settings, 'CUSTOM_TRACKING_DOMAIN_SKIP_DNS_CHECK', False):
                try:
                    answers = resolver.resolve(custom_domain, 'CNAME')
                except Exception:
                    return HttpResponseBadRequest('Custom tracking domain is not configured correctly.')
                if not answers:
                    return HttpResponseBadRequest('Custom tracking domain is not configured correctly.')

        path = request.path
        if path.startswith('/api/v1/clicks/track/') or path.startswith('/api/v1/clicks/track'):
            return None

        request.path = '/api/v1/clicks/track/'
        request.path_info = '/api/v1/clicks/track/'
        request.resolver_match = None
        return None

class TenantManagerMixin(models.Manager):
    """
    Custom manager that automatically filters all queries by the active tenant.
    """
    def get_queryset(self):
        tenant = get_current_tenant()
        if tenant:
            return super().get_queryset().filter(organization=tenant)
        return super().get_queryset()
