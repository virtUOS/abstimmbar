# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Serializers for the site-content admin (SiteConfig + Page), plus reusable
serializer mixins shared across apps."""
from typing import ClassVar

from basicbar_integrations.html_sanitize import clean_html
from basicbar_integrations.translation_sync import (
    modeltranslation_values,
    record_synced,
    stale_map,
)
from rest_framework import serializers

from common.i18n_fields import LANGS, TranslatedMapMixin

from .models import Page, SiteConfig


class TranslationSyncMixin:
    """Stale-translation reporting for a set of translatable base fields
    (#91, ``basicbar_integrations.translation_sync``).

    The host model must have a ``translation_sync = models.JSONField(...)``
    column (see ``Question.translation_sync``); this mixin reads/writes it.
    Set ``translation_sync_fields`` on the serializer to the base field names
    to track (e.g. ``("text",)`` — these are django-modeltranslation bases,
    so ``<field>_<lang>`` columns must exist).

    Adds:
    - ``translation_stale`` (read-only): ``{field: [stale language codes]}``,
      omitting fields that are not stale; ``{}`` when nothing is stale.
    - ``synced_fields`` (write-only, optional): field names to record as
      back in sync, using the values just written. Recording happens after
      the instance is saved, so the hash reflects what was actually stored;
      unknown field names (not in ``translation_sync_fields``) are ignored.

    These two are injected via ``get_fields()`` rather than declared as plain
    class attributes: DRF's ``SerializerMetaclass`` only harvests declared
    ``Field`` instances from a class's own body (or another *Serializer*
    subclass's ``_declared_fields``), not from an ordinary mixin — a
    class-attribute ``Field`` here would be invisible to it and
    ``ModelSerializer.get_fields()`` would then try (and fail) to build them
    as model fields. Consequently they must NOT be listed in the host
    serializer's ``Meta.fields``; adding them here is what exposes them.
    """

    translation_sync_fields: tuple = ()

    def get_fields(self):
        fields = super().get_fields()
        fields["translation_stale"] = serializers.SerializerMethodField()
        fields["synced_fields"] = serializers.ListField(
            child=serializers.CharField(), required=False, write_only=True
        )
        return fields

    def get_translation_stale(self, instance):
        fields_values = {
            field: modeltranslation_values(instance, field, LANGS)
            for field in self.translation_sync_fields
        }
        return stale_map(instance.translation_sync, fields_values)

    def _record_synced_fields(self, instance, synced_fields):
        recorded = False
        for field in synced_fields or []:
            if field not in self.translation_sync_fields:
                continue
            values = modeltranslation_values(instance, field, LANGS)
            instance.translation_sync = record_synced(instance.translation_sync, field, values)
            recorded = True
        if recorded:
            instance.save(update_fields=["translation_sync"])
        return instance

    def create(self, validated_data):
        synced_fields = validated_data.pop("synced_fields", None)
        instance = super().create(validated_data)
        return self._record_synced_fields(instance, synced_fields)

    def update(self, instance, validated_data):
        synced_fields = validated_data.pop("synced_fields", None)
        instance = super().update(instance, validated_data)
        return self._record_synced_fields(instance, synced_fields)


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

    translated_fields = ("landing_text", "closing_info", "ai_notice")

    logo = serializers.SerializerMethodField()
    # Read/write the internal notice page by its slug (null = none).
    ai_notice_page = serializers.SlugRelatedField(
        slug_field="slug", queryset=Page.objects.all(), allow_null=True, required=False,
    )

    class Meta:
        model = SiteConfig
        fields: ClassVar = [
            "landing_text", "closing_info", "logo",
            "ai_notice", "ai_notice_page", "ai_notice_url",
        ]

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
