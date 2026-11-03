# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
from django.db import migrations

PROF = {"de": "Professor*innen", "en": "Professors"}
OTHERS = {"de": "Andere", "en": "Others"}

TEMPLATES = [
    (1, "Professor*innen / Andere", "Professors / Others", [PROF, OTHERS]),
    (2, "Vier Statusgruppen", "Four status groups", [
        PROF,
        {"de": "Wissenschaftliche Mitarbeitende", "en": "Academic staff"},
        {"de": "Studierende", "en": "Students"},
        {"de": "Mitarbeitende in Technik und Verwaltung",
         "en": "Technical and administrative staff"},
    ]),
    (3, "Mit Externen", "With external members", [
        PROF, OTHERS, {"de": "Externe", "en": "External members"},
    ]),
]


def seed(apps, schema_editor):
    GroupTemplate = apps.get_model("committees", "GroupTemplate")
    for position, de, en, groups in TEMPLATES:
        GroupTemplate.objects.create(
            name_de=de, name_en=en, groups=groups, position=position,
        )


def unseed(apps, schema_editor):
    apps.get_model("committees", "GroupTemplate").objects.filter(
        position__in=[1, 2, 3],
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("committees", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
