# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Retention for the Easy/Pro sessions-per-day stats table.

``DailyModeSession`` gains roughly one row per browser session per day, so
without pruning it grows without bound. This command deletes rows older than
``--days`` (default 400, a little over a year so a full academic year of
history stays available). Meant to run from cron; see docs/deployment.md.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import DailyModeSession

DEFAULT_RETENTION_DAYS = 400


class Command(BaseCommand):
    help = "Delete DailyModeSession stats rows older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=DEFAULT_RETENTION_DAYS,
            help=(
                "Keep rows dated within the last N days; delete older ones "
                f"(default: {DEFAULT_RETENTION_DAYS})."
            ),
        )

    def handle(self, *args, **options):
        days = options["days"]
        cutoff = timezone.localdate() - timedelta(days=days)
        deleted, _ = DailyModeSession.objects.filter(date__lt=cutoff).delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Pruned {deleted} DailyModeSession row(s) older than {days} days "
                f"(before {cutoff})."
            )
        )
