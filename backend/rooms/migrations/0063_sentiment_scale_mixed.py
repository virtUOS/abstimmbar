# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""#291: the sentiment preset gains „gemischt" (praise and criticism in one
answer). Questions still on the exact former preset get the new scale;
custom scales stay untouched. Stored verdicts remain valid (a subset)."""
from django.db import migrations

OLD = ["positiv", "neutral", "negativ"]
NEW = ["positiv", "neutral", "negativ", "gemischt"]


def forwards(apps, schema_editor):
    Question = apps.get_model("rooms", "Question")
    for q in Question.objects.filter(kind="open_text").only("pk", "evaluation_categories"):
        if [str(c).casefold() for c in q.evaluation_categories or []] == OLD:
            q.evaluation_categories = NEW
            q.save(update_fields=["evaluation_categories"])


def backwards(apps, schema_editor):
    Question = apps.get_model("rooms", "Question")
    for q in Question.objects.filter(kind="open_text").only("pk", "evaluation_categories"):
        if [str(c).casefold() for c in q.evaluation_categories or []] == NEW:
            q.evaluation_categories = OLD
            q.save(update_fields=["evaluation_categories"])


class Migration(migrations.Migration):
    dependencies = [("rooms", "0062_generationjob_imported_count")]

    operations = [migrations.RunPython(forwards, backwards)]
