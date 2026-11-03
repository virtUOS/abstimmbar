# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Translatable group/template names (django-modeltranslation)."""
from modeltranslation.translator import TranslationOptions, register

from .models import CommitteeGroup, GroupTemplate


@register(GroupTemplate)
class GroupTemplateTranslationOptions(TranslationOptions):
    fields = ("name",)


@register(CommitteeGroup)
class CommitteeGroupTranslationOptions(TranslationOptions):
    fields = ("name",)
