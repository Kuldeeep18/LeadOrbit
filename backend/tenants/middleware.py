import logging
import re
import threading

from django.conf import settings
from django.db import connection, models
from django.utils.deprecation import MiddlewareMixin


_thread_locals = threading.local()
logger = logging.getLogger(__name__)


# Matches the primary table name in SELECT/DELETE (after FROM) and UPDATE (after UPDATE).
# Uses Django's standard double-quoted identifier style, e.g. FROM "leads_lead".
_PRIMARY_TABLE_RE = re.compile(r'(?:FROM|UPDATE)\s+"(\w+)"', re.IGNORECASE)

def get_current_tenant():
    return getattr(_thread_locals, 'tenant', None)


# Module-level cache; populated lazily once the app registry is ready.
_TENANT_TABLES: frozenset | None = None


def _get_tenant_table_names() -> frozenset:
    """
    Returns the frozenset of DB table names for all concrete TenantModel subclasses.
    Evaluated once after the app registry is ready to avoid circular imports at
    module load time.
    """
    global _TENANT_TABLES
    if _TENANT_TABLES is None:
        from django.apps import apps
        from tenants.models import TenantModel
        _TENANT_TABLES = frozenset(
            m._meta.db_table
            for m in apps.get_models()
            if issubclass(m, TenantModel) and not m._meta.abstract
        )
    return _TENANT_TABLES


def _make_tenant_isolation_checker(request_path: str):
    """
    Returns a Django execute_wrapper callable that logs a WARNING whenever a
    SELECT, UPDATE, or DELETE is executed against a tenant-scoped table without
    an organization_id filter in the WHERE clause.

    Note: organization_id always appears in the SELECT column list, so we
    specifically check the WHERE clause portion of the SQL to avoid false negatives.

    Intended for installation only when settings.DEBUG is True.
    """
    tenant_tables = _get_tenant_table_names()

    def _checker(execute, sql, params, many, context):
        upper = sql.lstrip().upper()

        if not upper.startswith(('SELECT', 'UPDATE', 'DELETE')):
            return execute(sql, params, many, context)

        match = _PRIMARY_TABLE_RE.search(sql)
        if not match:
            return execute(sql, params, many, context)

        table = match.group(1)
        if table not in tenant_tables:
            return execute(sql, params, many, context)

        # Check for organization_id specifically in the WHERE clause.
        # A plain `'organization_id' in sql` check gives false negatives because
        # the column name also appears in the SELECT list of every tenant query.
        upper_sql = sql.upper()
        where_idx = upper_sql.find('WHERE')
        has_org_filter = where_idx != -1 and 'ORGANIZATION_ID' in upper_sql[where_idx:]

        if not has_org_filter:
            logger.warning(
                "[TenantIsolation] Unscoped query on '%s' detected "
                "(missing organization_id filter). "
                "Path: %s | SQL: %s",
                table, request_path, sql,
            )

        return execute(sql, params, many, context)

    return _checker


class TenantMiddleware(MiddlewareMixin):
    """
    Middleware that reads the preferred organization from the User's session/token
    and sets it globally for the request thread so TenantModels can auto-filter.

    In DEBUG mode, also installs a per-request query validator that logs a WARNING
    whenever a TenantModel table is queried without an organization_id filter,
    helping catch accidental cross-tenant data leaks during development.
    """
    def process_request(self, request):
        _thread_locals.tenant = None
        if hasattr(request, 'user') and request.user.is_authenticated:
            _thread_locals.tenant = request.user.organization

        if settings.DEBUG:
            checker = _make_tenant_isolation_checker(request.path)
            _thread_locals.isolation_checker = checker
            connection.execute_wrappers.append(checker)

    def process_response(self, request, response):
        if settings.DEBUG:
            checker = getattr(_thread_locals, 'isolation_checker', None)
            if checker is not None:
                try:
                    connection.execute_wrappers.remove(checker)
                except ValueError:
                    pass
                del _thread_locals.isolation_checker

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
