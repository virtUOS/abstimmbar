# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Language-map (de/en) representation for modeltranslation fields (#33 MR2).

The SSE hub broadcasts one payload to all participants, so content cannot be
resolved to a single language server-side. Translatable fields are exposed as
{"de": …, "en": …} maps and resolved client-side. resolve_translated_text is
for the few places that still need a server-side string (CSV, AI prompts)."""
from django.conf import settings
from rest_framework import serializers

LANGS = tuple(code for code, _ in settings.LANGUAGES)


def translated_map(obj, base):
    """{lang: value} for a modeltranslation base field (empty langs -> "")."""
    return {lang: (getattr(obj, f"{base}_{lang}", "") or "") for lang in LANGS}


def resolve_translated_text(value):
    """A {lang: text} map (or plain str) -> active-language string with fallback."""
    if not isinstance(value, dict):
        return value or ""
    from django.utils import translation
    active = (translation.get_language() or settings.MODELTRANSLATION_DEFAULT_LANGUAGE).split("-")[0]
    for lang in (active, *settings.MODELTRANSLATION_FALLBACK_LANGUAGES):
        if value.get(lang):
            return value[lang]
    return next((t for t in value.values() if t), "")


class TranslatedMapMixin:
    """Represent translatable base fields as {de, en} maps.

    Read: to_representation replaces each ``translated_fields`` base field
    with its map. Write: to_internal_value accepts a map (or, for backward
    compatibility, a plain string, which is written to the canonical
    language only) and stores the per-language columns directly in
    ``validated_data`` — never the bare accessor, since the active request
    language may differ from the content-canonical language (#33 MR2).

    ``translated_optional_fields`` names bases whose canonical-language
    requirement is enforced downstream instead (e.g. a serializer that
    fills in a timestamped default for a blank title in ``validate()``) —
    the mixin skips its own required check for those so it doesn't reject
    the request before that logic gets a chance to run."""

    translated_fields: tuple = ()
    translated_optional_fields: tuple = ()

    def get_fields(self):
        fields = super().get_fields()
        # Base translatable fields are handled manually; make them non-strict.
        for base in self.translated_fields:
            if base in fields:
                fields[base].required = False
                if hasattr(fields[base], "allow_blank"):
                    fields[base].allow_blank = True
        return fields

    def to_representation(self, instance):
        data = super().to_representation(instance)
        for base in self.translated_fields:
            if base in data:
                data[base] = translated_map(instance, base)
        return data

    def _coerce_map(self, value):
        if isinstance(value, dict):
            return {lang: str(value.get(lang) or "").strip() for lang in LANGS}
        # legacy plain string -> canonical language only
        m = {lang: "" for lang in LANGS}
        m[settings.MODELTRANSLATION_DEFAULT_LANGUAGE] = str(value or "").strip()
        return m

    def to_internal_value(self, data):
        # Pull translatable maps out before DRF validates the (now optional) base.
        pending = {}
        if isinstance(data, dict):
            data = data.copy()
            for base in self.translated_fields:
                if base in data:
                    pending[base] = self._coerce_map(data.pop(base))
        attrs = super().to_internal_value(data)
        default = settings.MODELTRANSLATION_DEFAULT_LANGUAGE
        errors = {}
        for base, m in pending.items():
            # A fully blank map on an update is a no-op: the pre-map contract
            # was "blank on update keeps the old value" (in every language),
            # so don't write anything for this field at all — writing None
            # per language here would silently clear translations that
            # weren't actually touched by the request. (On create there is no
            # old value to preserve, so a blank map still flows through to
            # the canonical-required check / a downstream default-filling
            # validate() below.)
            if self.instance is not None and not any(m.values()):
                continue
            model_field = self.Meta.model._meta.get_field(base)
            # A serializer-level validate_<base> (e.g. HTML sanitizing) would
            # normally run over the (now-absent) bare field; since we pop the
            # key before delegating to super(), DRF never sees it and never
            # calls that hook — so run it ourselves, per language. Likewise,
            # max_length is never enforced by the (skipped) base field either
            # — without checking it here, an over-long value would either
            # silently truncate or fail at the DB instead of coming back as a
            # clean validation error (unbounded TextFields have no
            # max_length, so they're skipped).
            validator = getattr(self, f"validate_{base}", None)
            max_length = getattr(model_field, "max_length", None)
            for lang in LANGS:
                value = m[lang] or None
                if value is not None:
                    if max_length is not None and len(value) > max_length:
                        errors[base] = (
                            f"Ensure this field has no more than "
                            f"{max_length} characters."
                        )
                        continue
                    if validator is not None:
                        value = validator(value)
                # blank -> None so unique translation columns don't collide
                attrs[f"{base}_{lang}"] = value
            if base in self.translated_optional_fields:
                continue
            required = not (model_field.blank or model_field.null or model_field.has_default())
            if required and not m[default]:
                errors[base] = "A value in the default language is required."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs
