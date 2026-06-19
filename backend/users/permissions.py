from rest_framework.permissions import BasePermission

class IsOrgAdmin(BasePermission):
    """Allows access only to admin users."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'ADMIN'

class IsOrgManagerOrAdmin(BasePermission):
    """Allows access to managers and admins."""
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role in ('ADMIN', 'MANAGER')