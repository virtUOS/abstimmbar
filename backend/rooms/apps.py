# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.apps import AppConfig


class RoomsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "rooms"

    def ready(self):
        # Sweep jobs orphaned by a hard restart (crash/redeploy — a normal
        # uvicorn --reload also counts, correctly: the worker thread pool
        # dies with the process). Guarded against manage.py subcommands
        # (makemigrations/migrate/test/…) that load the app registry without
        # actually serving traffic — the backend runs via
        # `uvicorn config.asgi:application` (ADR-0003), never
        # `manage.py runserver`, so those subcommands are the only case to
        # exclude. Never allowed to crash app startup.
        import sys
        argv = sys.argv
        if len(argv) > 1 and argv[0].endswith("manage.py") and argv[1] != "runserver":
            return
        try:
            from . import generation
            generation.fail_orphaned_jobs()
        except Exception:
            pass
