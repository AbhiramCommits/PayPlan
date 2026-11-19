from rest_framework.permissions import BasePermission


def user_has_support_role(user) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    return user.groups.filter(name="support").exists()


class IsSupportRole(BasePermission):
    message = "Support role required."

    def has_permission(self, request, view):
        return user_has_support_role(request.user)
