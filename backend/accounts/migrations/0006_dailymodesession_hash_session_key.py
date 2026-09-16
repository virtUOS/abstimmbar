# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Store a one-way hash of the session key instead of the raw key.

The raw Django ``session_key`` is a live authentication credential; duplicating
it into the stats table (0005) meant a leak of that table could re-authenticate
sessions. Only uniqueness is needed for the per-day count, so we replace the
column with a SHA-256 hash. Existing rows are hashed in place (a no-op on an
empty table) so historical counts are preserved while the raw keys are dropped.
"""
import hashlib

from django.db import migrations, models


def hash_existing_keys(apps, schema_editor):
    DailyModeSession = apps.get_model("accounts", "DailyModeSession")
    for row in DailyModeSession.objects.all().iterator():
        row.session_hash = hashlib.sha256(row.session_key.encode()).hexdigest()
        row.save(update_fields=["session_hash"])


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0005_dailymodesession"),
    ]

    operations = [
        # Drop the old constraint first so its column can be removed later.
        migrations.AlterUniqueTogether(
            name="dailymodesession",
            unique_together=set(),
        ),
        migrations.AddField(
            model_name="dailymodesession",
            name="session_hash",
            field=models.CharField(default="", max_length=64),
            preserve_default=False,
        ),
        migrations.RunPython(hash_existing_keys, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="dailymodesession",
            name="session_key",
        ),
        migrations.AlterUniqueTogether(
            name="dailymodesession",
            unique_together={("session_hash", "date")},
        ),
    ]
