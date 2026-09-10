# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""#86: Likert scale order flips from positive-first to negative-first (position
0 = low pole). Reverse the positions of every existing Likert question's
non-abstention options so they match the new convention; option ids (and thus
votes) are untouched. Abstention options keep their trailing position."""
from django.db import migrations


def reverse_scales(apps, schema_editor):
    Question = apps.get_model("rooms", "Question")
    AnswerOption = apps.get_model("rooms", "AnswerOption")
    for q in Question.objects.filter(kind="likert"):
        scale = list(
            AnswerOption.objects.filter(question=q, is_abstention=False).order_by("position")
        )
        n = len(scale)
        for new_pos, opt in enumerate(reversed(scale)):
            if opt.position != new_pos:
                opt.position = new_pos
                opt.save(update_fields=["position"])
        # Abstentions sit after the scale.
        for extra_pos, opt in enumerate(
            AnswerOption.objects.filter(question=q, is_abstention=True).order_by("position"),
            start=n,
        ):
            if opt.position != extra_pos:
                opt.position = extra_pos
                opt.save(update_fields=["position"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("rooms", "0043_wordcloud_single_to_max_one")]
    operations = [migrations.RunPython(reverse_scales, noop)]
