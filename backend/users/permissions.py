from rest_framework.permissions import BasePermission

from .models import User


def get_effective_role(user):
    role = getattr(user, 'role', None)
    if role == User.ROLE_LEGACY_USER:
        return User.ROLE_MEMBER
    return role


class RolePermission(BasePermission):
    allowed_roles = frozenset()
    message = 'You do not have permission to perform this action.'

    def has_permission(self, request, view):
        user = getattr(request, 'user', None)
        if not user or not user.is_authenticated:
            return False
        return get_effective_role(user) in self.allowed_roles


class IsOrgAdmin(RolePermission):
    allowed_roles = frozenset({User.ROLE_ADMIN})
    message = 'Only organization admins can perform this action.'


class IsOrgManager(RolePermission):
    allowed_roles = frozenset({User.ROLE_ADMIN, User.ROLE_MANAGER})
    message = 'Only organization admins or managers can perform this action.'
