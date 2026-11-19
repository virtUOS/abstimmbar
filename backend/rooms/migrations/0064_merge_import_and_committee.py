# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Merge-up of release/1.0 (v1.1.0, #323: GenerationJob.source/skipped/
import_format) into main's 2.0 line (committee room, #292 imported_count,
#291 sentiment scale). No operations."""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("rooms", "0059_generationjob_source_skipped"),
        ("rooms", "0063_sentiment_scale_mixed"),
    ]

    operations = []
