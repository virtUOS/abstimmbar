# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Title helpers: readable defaults and uniqueness (v2 review feedback).

Room titles are unique per user, set titles per room — enforced at the
API layer (existing duplicates are deliberately left alone). Copies and
imports get a numbered suffix instead of an error.
"""
from django.utils import timezone

MONTHS_DE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]

MAX_TITLE_LENGTH = 200


def default_title(prefix):
    """E.g. "Unbenanntes Fragenset vom 7. Juli 2026, 12:30"."""
    now = timezone.localtime()
    return (
        f"{prefix} vom {now.day}. {MONTHS_DE[now.month - 1]} {now.year}, "
        f"{now:%H:%M}"
    )


def unique_title(base, exists):
    """Return ``base`` or ``base (2)``, ``base (3)``, … until ``exists``
    (a callable taking a candidate title) no longer matches."""
    title = base[:MAX_TITLE_LENGTH]
    counter = 2
    while exists(title):
        suffix = f" ({counter})"
        title = base[: MAX_TITLE_LENGTH - len(suffix)] + suffix
        counter += 1
    return title
