# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""#88: the word cloud's per-person cap now carries the single-vs-multiple
meaning (1 = a single answer). Existing single-answer word clouds stored
allow_multiple=False with wordcloud_max_answers=0; map them to 1 so they keep
their single-answer behaviour and read correctly in the editor. Multi-answer
word clouds keep their cap (0 = unlimited)."""
from django.db import migrations


def single_to_one(apps, schema_editor):
    Question = apps.get_model("rooms", "Question")
    Question.objects.filter(
        kind="word_cloud", allow_multiple=False
    ).update(wordcloud_max_answers=1)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("rooms", "0042_question_wordcloud_batch_submit_and_more"),
    ]
    operations = [migrations.RunPython(single_to_one, noop)]
