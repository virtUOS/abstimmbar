# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Merge the two rooms/0010 migrations that landed from parallel branches
(set-ux license_holder + show_logo_in_presentation). No schema change — it
only reunites the migration graph so ``migrate`` has a single leaf again."""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('rooms', '0010_questionset_license_holder_alter_questionset_license'),
        ('rooms', '0010_room_show_logo_in_presentation'),
    ]

    operations = []
