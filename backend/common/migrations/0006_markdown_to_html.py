# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Editor-unify (#49): convert authored Markdown fields to sanitized HTML.
SiteConfig.landing_text, SiteConfig.closing_info, Page.body — both language
columns each. One-off; not losslessly reversible (RunPython.noop reverse)."""
from django.db import migrations

from rooms.migrations._mdhtml import convert_fields


def forwards(apps, schema_editor):
    convert_fields(apps, "common", "SiteConfig", ("landing_text", "closing_info"))
    convert_fields(apps, "common", "Page", ("body",))


class Migration(migrations.Migration):
    dependencies = [
        ("common", "0005_backfill_language"),
        ("rooms", "0026_markdown_to_html"),
    ]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
