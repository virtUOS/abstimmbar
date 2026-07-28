# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Editor-unify (#49): convert authored Markdown fields to sanitized HTML.
Room.description, Room.closing_info, QuestionSet.description — both language
columns each. One-off; not losslessly reversible (RunPython.noop reverse)."""
from django.db import migrations

from ._mdhtml import convert_fields


def forwards(apps, schema_editor):
    convert_fields(apps, "rooms", "Room", ("description", "closing_info"))
    convert_fields(apps, "rooms", "QuestionSet", ("description",))


class Migration(migrations.Migration):
    dependencies = [("rooms", "0025_backfill_language")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
