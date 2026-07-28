# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Serializers for the site-content admin (SiteConfig + Page)."""
from typing import ClassVar

from basicbar_integrations.html_sanitize import clean_html
from rest_framework import serializers

from common.i18n_fields import TranslatedMapMixin

from .models import Page, SiteConfig


class PageLinkSerializer(TranslatedMapMixin, serializers.ModelSerializer):
    """Slim footer link (no body). ``title`` is authored in de+en (#33 MR2)
    and returned as a {"de": ..., "en": ...} map — even though it is just a
    nav label, the frontend resolves it like every other translated field."""

    translated_fields = ("title",)

    class Meta:
        model = Page
        fields: ClassVar = ["slug", "title"]


class PageDetailSerializer(TranslatedMapMixin, serializers.ModelSerializer):
    """Public page view. title/body are authored in de+en (#33 MR2); each is
    represented as a {"de": ..., "en": ...} map, resolved client-side."""

    translated_fields = ("title", "body")

    class Meta:
        model = Page
        fields: ClassVar = ["slug", "title", "body", "updated_at"]


class PageManageSerializer(TranslatedMapMixin, serializers.ModelSerializer):
    """Admin CRUD. ``footer_order`` is set via the reorder action."""

    translated_fields = ("title", "body")

    class Meta:
        model = Page
        fields: ClassVar = [
            "id", "slug", "title", "body",
            "is_published", "show_in_footer", "footer_order", "updated_at",
        ]
        read_only_fields: ClassVar = ["footer_order", "updated_at"]

    def validate_body(self, value):
        return clean_html(value)


class SiteConfigSerializer(TranslatedMapMixin, serializers.ModelSerializer):
    """Admin read/write of the landing text; the logo goes through the
    dedicated multipart endpoint, so it is read-only here.
    landing_text/closing_info are authored in de+en (#33 MR2); each is
    represented as a {"de": ..., "en": ...} map, resolved client-side."""

    translated_fields = ("landing_text", "closing_info")

    logo = serializers.SerializerMethodField()

    class Meta:
        model = SiteConfig
        fields: ClassVar = ["landing_text", "closing_info", "logo"]

    def validate_landing_text(self, value):
        return clean_html(value)

    def validate_closing_info(self, value):
        return clean_html(value)

    def get_logo(self, obj):
        if not obj.logo:
            return None
        request = self.context.get("request")
        url = obj.logo.url
        return request.build_absolute_uri(url) if request else url
