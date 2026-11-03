"""Extension points for apps that build on rooms (e.g. committees).

``rooms`` never imports from those apps; they register callables here in
their ``AppConfig.ready()``.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Question

# Each check returns a human-readable reason if the question's content
# (text, kind, options, named_vote) must not be changed right now, else None.
question_lock_checks: list[Callable[[Question], str | None]] = []

# Called after a question and its options were saved through the API.
after_question_saved: list[Callable[[Question], None]] = []


def question_lock_reason(question) -> str | None:
    """First non-None answer of the registered lock checks."""
    for check in question_lock_checks:
        reason = check(question)
        if reason:
            return reason
    return None


def run_after_question_saved(question) -> None:
    for callback in after_question_saved:
        callback(question)
