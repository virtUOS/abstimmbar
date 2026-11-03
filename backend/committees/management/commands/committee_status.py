"""Print committee activity as JSON; exit 1 while secret ballots are open.

Use before a deploy: ``manage.py committee_status || echo "do not restart"``.
"""

import json
import sys

from django.core.management.base import BaseCommand

from committees.status import activity


class Command(BaseCommand):
    help = "Print running meetings / open secret ballots as JSON (exit 1 if any secret ballot is open)."

    def handle(self, *args, **options):
        data = activity()
        self.stdout.write(json.dumps(data))
        if data["secret_ballots_open"] > 0:
            sys.exit(1)
