# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.contrib import admin

from .models import GroupTemplate, SealLink


@admin.register(GroupTemplate)
class GroupTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "position")
    ordering = ("position",)


@admin.register(SealLink)
class SealLinkAdmin(admin.ModelAdmin):
    """Read-only: the chain is written by the ballot lifecycle only."""

    list_display = ("reference", "kind", "seq", "room", "created_at", "deleted_at")
    list_filter = ("kind",)
    search_fields = ("reference", "hash")

    def get_readonly_fields(self, request, obj=None):
        return [f.name for f in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
