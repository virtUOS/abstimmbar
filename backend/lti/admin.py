# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.contrib import admin

from .models import LtiContextLink


@admin.register(LtiContextLink)
class LtiContextLinkAdmin(admin.ModelAdmin):
    list_display = ("platform", "context_id", "room")
