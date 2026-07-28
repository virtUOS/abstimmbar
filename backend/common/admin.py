# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from typing import ClassVar

from django.contrib import admin

from .models import Page, SiteConfig


@admin.register(SiteConfig)
class SiteConfigAdmin(admin.ModelAdmin):
    list_display = ("__str__", "updated_at")


@admin.register(Page)
class PageAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_published", "show_in_footer", "footer_order")
    list_editable = ("is_published", "show_in_footer", "footer_order")
    prepopulated_fields: ClassVar = {"slug": ("title",)}
