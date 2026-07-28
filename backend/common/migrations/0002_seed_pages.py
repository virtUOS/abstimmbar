# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Seed Impressum and Datenschutz as draft footer pages.

Both start unpublished so an incomplete legal notice never shows publicly;
an admin reviews, fills in the specifics and publishes. The Datenschutz body
is only the surrounding prose — the inventory of collected data is generated
automatically from common.data_collection and appended in the frontend.
"""
from django.db import migrations

IMPRESSUM = """\
## Impressum

**Angaben gemäß § 5 DDG / § 18 MStV**

*(Bitte durch die Angaben Ihrer Einrichtung ersetzen.)*

Universität Osnabrück
Musterstraße 1, 49074 Osnabrück

Vertreten durch: …
Kontakt: … · E-Mail: …

Verantwortlich für den Inhalt nach § 18 Abs. 2 MStV: …
"""

DATENSCHUTZ = """\
## Datenschutzerklärung

Der Schutz Ihrer personenbezogenen Daten ist uns wichtig. Nachfolgend
informieren wir Sie über die Verarbeitung im Rahmen dieses Dienstes.

**Verantwortliche Stelle:** *(bitte ergänzen)*

**Welche Daten wir verarbeiten:** Eine Übersicht der erhobenen Datenkategorien
finden Sie in der Tabelle unten (sie wird automatisch aus dem System erzeugt
und bleibt so aktuell).

**Ihre Rechte:** Auskunft, Berichtigung, Löschung, Einschränkung, Widerspruch
sowie Beschwerde bei der Aufsichtsbehörde. *(Kontaktangaben bitte ergänzen.)*
"""

SEED = [
    ("impressum", "Impressum", IMPRESSUM, 100),
    ("datenschutz", "Datenschutz", DATENSCHUTZ, 101),
]


def seed(apps, schema_editor):
    Page = apps.get_model("common", "Page")
    for slug, title, body, order in SEED:
        Page.objects.get_or_create(
            slug=slug,
            defaults={
                "title": title,
                "body": body,
                "is_published": False,
                "show_in_footer": True,
                "footer_order": order,
            },
        )


def unseed(apps, schema_editor):
    Page = apps.get_model("common", "Page")
    Page.objects.filter(slug__in=[slug for slug, *_ in SEED]).delete()


class Migration(migrations.Migration):
    dependencies = [("common", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
