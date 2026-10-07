# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Bilingual mindmap seeds: plain-string ``text``/``description`` of the
predefined branches become ``{de, en}`` maps (canonical language =
CONTENT_DEFAULT_LANGUAGE). Already-bilingual seeds are left alone."""

from django.conf import settings
from django.db import migrations


def _as_map(value, canonical, langs):
    if isinstance(value, dict):
        return {lang: str(value.get(lang) or "") for lang in langs}
    result = dict.fromkeys(langs, "")
    result[canonical] = str(value or "")
    return result


def _convert(nodes, canonical, langs):
    if not isinstance(nodes, list):
        return nodes
    result = []
    for node in nodes:
        if not isinstance(node, dict):
            result.append(node)
            continue
        result.append({
            **node,
            "text": _as_map(node.get("text"), canonical, langs),
            "description": _as_map(node.get("description"), canonical, langs),
            "children": _convert(node.get("children") or [], canonical, langs),
        })
    return result


def forwards(apps, schema_editor):
    Question = apps.get_model("rooms", "Question")
    canonical = settings.MODELTRANSLATION_DEFAULT_LANGUAGE
    langs = [code for code, _ in settings.LANGUAGES]
    for question in Question.objects.exclude(mindmap_seed=[]).only("pk", "mindmap_seed"):
        converted = _convert(question.mindmap_seed, canonical, langs)
        if converted != question.mindmap_seed:
            Question.objects.filter(pk=question.pk).update(mindmap_seed=converted)


class Migration(migrations.Migration):
    dependencies = [("rooms", "0051_mindmap")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
