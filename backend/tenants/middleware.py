import threading
from django.db import models
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

class TenantManagerMixin(models.Manager):
    """
    Custom manager that automatically filters all queries by the active tenant.
    """
    def get_queryset(self):
        tenant = get_current_tenant()
        if tenant:
            return super().get_queryset().filter(organization=tenant)
        return super().get_queryset()
