# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
from django.db import migrations, models


def clear_stale_admin_default(apps, schema_editor):
    # Existing admins carried the old, for-them-unswitchable default
    # easy_mode=True; reset to None so their role default (pro) applies and
    # they can now toggle. Non-staff are left untouched.
    User = apps.get_model("accounts", "User")
    User.objects.filter(is_staff=True, easy_mode=True).update(easy_mode=None)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_user_easy_mode")]
    operations = [
        migrations.AlterField(
            model_name="user",
            name="easy_mode",
            field=models.BooleanField(null=True, blank=True, default=None),
        ),
        migrations.RunPython(clear_stale_admin_default, migrations.RunPython.noop),
    ]
