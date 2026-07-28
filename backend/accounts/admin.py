# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class AppUserAdmin(UserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "is_staff", "subject")
    fieldsets = UserAdmin.fieldsets + (
        ("OIDC", {"fields": ("subject", "claims", "language")}),
    )
    readonly_fields = ("subject", "claims")
