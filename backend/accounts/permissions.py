# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Shared DRF permissions."""
from rest_framework.permissions import BasePermission


class IsAdmin(BasePermission):
    """Site administrators only — Django staff or superusers. Staff is
    granted via the OIDC admin group (see accounts.oidc)."""

    def has_permission(self, request, view):
        user = request.user
        return bool(
            user and user.is_authenticated and (user.is_staff or user.is_superuser)
        )
