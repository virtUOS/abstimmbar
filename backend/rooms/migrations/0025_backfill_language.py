# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Backfill the canonical-language columns (#33 MR2).

modeltranslation keeps the bare column in sync with the *default* language
going forward, but existing rows have ``*_<default>`` = NULL until this
migration copies the base value over.
"""
from django.conf import settings
from django.db import migrations


def backfill(apps, schema_editor):
    default = settings.MODELTRANSLATION_DEFAULT_LANGUAGE
    for model_name, base_fields in [
        ("Room", ["title", "description", "closing_info"]),
        ("QuestionSet", ["title", "description"]),
        ("Section", ["title"]),
        ("Question", ["text"]),
        ("AnswerOption", ["text"]),
    ]:
        Model = apps.get_model("rooms", model_name)
        for obj in Model.objects.all().iterator():
            update = {}
            for base in base_fields:
                col = f"{base}_{default}"
                if not getattr(obj, col, None) and getattr(obj, base, None):
                    update[col] = getattr(obj, base)
            if update:
                for k, v in update.items():
                    setattr(obj, k, v)
                obj.save(update_fields=list(update))


class Migration(migrations.Migration):
    dependencies = [
        ("rooms", "0024_answeroption_text_de_answeroption_text_en_and_more"),
    ]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
