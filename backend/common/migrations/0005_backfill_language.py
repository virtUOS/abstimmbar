# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Backfill the canonical-language columns (#33 MR2), analogous to
rooms/migrations/0025_backfill_language.py: SiteConfig (singleton) + Page."""
from django.conf import settings
from django.db import migrations


def backfill(apps, schema_editor):
    default = settings.MODELTRANSLATION_DEFAULT_LANGUAGE
    for model_name, base_fields in [
        ("SiteConfig", ["landing_text", "closing_info"]),
        ("Page", ["title", "body"]),
    ]:
        Model = apps.get_model("common", model_name)
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
        ("common", "0004_page_body_de_page_body_en_page_title_de_and_more"),
    ]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
