# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Translatable site-config and info-page fields (#33 MR2)."""
from modeltranslation.translator import TranslationOptions, register

from .models import Page, SiteConfig


@register(SiteConfig)
class SiteConfigTranslationOptions(TranslationOptions):
    fields = ("landing_text", "closing_info", "ai_notice")


@register(Page)
class PageTranslationOptions(TranslationOptions):
    fields = ("title", "body")
