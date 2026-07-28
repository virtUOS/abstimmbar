# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Editor/rooms: ensure every room's owner is also in its owners M2M
(restore invariant broken by legacy 0018 backfill). One-off, idempotent."""
from django.db import migrations

from ._owner_membership import ensure_owner_membership


def forwards(apps, schema_editor):
    ensure_owner_membership(apps.get_model("rooms", "Room"))


class Migration(migrations.Migration):
    dependencies = [("rooms", "0026_markdown_to_html")]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
