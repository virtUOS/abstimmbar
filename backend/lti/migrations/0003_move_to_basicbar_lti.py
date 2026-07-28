# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Umzug zu basicbar-lti (Basicbar Phase 5).

LtiToolKey/LtiPlatform/LtiUserLink leben jetzt im Paket basicbar_lti. Die
Zeilen werden PK-erhaltend (inkl. Zeitstempel) per SQL in die Paket-Tabellen
kopiert, der Kontext-Link-FK wird umgehängt, die alten Tabellen fallen weg.
Auf frischen Datenbanken sind die alten Tabellen leer — die Kopie ist dann
ein No-op. Läuft als ganz normales ``manage.py migrate``.
"""

import django.db.models.deletion
from django.db import migrations, models

_COPIES = [
    (
        "basicbar_lti_ltitoolkey",
        "lti_ltitoolkey",
        "id, private_key, public_key, created_at",
    ),
    (
        "basicbar_lti_ltiplatform",
        "lti_ltiplatform",
        "id, created_at, updated_at, name, issuer, client_id, auth_login_url, "
        "auth_token_url, key_set_url, key_set, deployment_ids, is_active, "
        "link_by_email",
    ),
    (
        "basicbar_lti_ltiuserlink",
        "lti_ltiuserlink",
        "id, created_at, updated_at, sub, platform_id, user_id",
    ),
]


def copy_rows(apps, schema_editor):
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        for target, source, columns in _COPIES:
            cursor.execute(
                f"INSERT INTO {target} ({columns}) SELECT {columns} FROM {source}"
            )
            if connection.vendor == "postgresql":
                # bigserial-Sequenzen hinter die kopierten IDs setzen.
                cursor.execute(
                    f"SELECT setval(pg_get_serial_sequence('{target}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {target}), 1))"
                )


class Migration(migrations.Migration):

    dependencies = [
        ("basicbar_lti", "0001_initial"),
        ("lti", "0002_ltiplatform_link_by_email_ltiuserlink"),
    ]

    operations = [
        migrations.RunPython(copy_rows, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="lticontextlink",
            name="platform",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="context_links",
                to="basicbar_lti.ltiplatform",
            ),
        ),
        migrations.DeleteModel(name="LtiUserLink"),
        migrations.DeleteModel(name="LtiPlatform"),
        migrations.DeleteModel(name="LtiToolKey"),
    ]
