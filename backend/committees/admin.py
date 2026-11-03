# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.contrib import admin

from .models import GroupTemplate


@admin.register(GroupTemplate)
class GroupTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "position")
    ordering = ("position",)
