# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.apps import AppConfig


class CommitteesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "committees"

    def ready(self):
        import committees.signals  # noqa: F401
        from rooms import hooks

        from . import versions

        if versions.sync not in hooks.after_question_saved:
            hooks.after_question_saved.append(versions.sync)
        if versions.lock_reason not in hooks.question_lock_checks:
            hooks.question_lock_checks.append(versions.lock_reason)
