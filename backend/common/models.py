# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Shared abstract base models plus the site-wide admin content (v2):
a ``SiteConfig`` singleton (logo + pre-login landing text) and a generic
``Page`` model that powers the footer CMS (Impressum, Datenschutz and any
free pages). Content is authored HTML (WYSIWYG editor, #49) and sanitized
server-side on write through the shared allowlist (basicbar_integrations.html_sanitize
.clean_html) — that is the sanitization boundary, so bodies are stored as
already-clean HTML. Editable only by staff (see accounts.permissions
.IsAdmin)."""
from typing import ClassVar

from django.db import models


class TimeStampedModel(models.Model):
    """Adds created/updated timestamps; base for most domain models."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class SiteConfig(models.Model):
    """Singleton (pk=1) for site branding and the pre-login landing text."""

    landing_text = models.TextField(blank=True, default="")
    # Sanitized HTML shown to participants on every room's closing screen
    # (#24, editor-unify #49); rooms may add their own below this. Cleaned
    # server-side on write and rendered directly for the participant page.
    closing_info = models.TextField(blank=True, default="")
    # FileField (not ImageField) so an SVG logo is allowed.
    logo = models.FileField(upload_to="branding/", blank=True, null=True)
    # AI privacy notice (#80): a short operator-authored sentence saying
    # whether a local or external model processes uploaded material. Shown as
    # a one-time, dismissible banner while AI is available. Translatable
    # (de/en); the link points at the operator's privacy policy.
    ai_notice = models.TextField(blank=True, default="")
    ai_notice_url = models.URLField(blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return "Website-Einstellungen"


class Page(TimeStampedModel):
    """A free content page reachable at ``/pages/<slug>`` and, when enabled,
    linked in the footer. Impressum and Datenschutz are just seeded rows."""

    slug = models.SlugField(max_length=64, unique=True)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True, default="")
    is_published = models.BooleanField(default=True)
    show_in_footer = models.BooleanField(default=True)
    footer_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering: ClassVar = ["footer_order", "title"]

    def __str__(self):
        return self.title
