# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Motion text versions: frozen wording of each agenda item."""
from django.db import transaction

from rooms.models import QuestionSet

from .models import Ballot, MotionVersion


def _snapshot(question) -> tuple[str, str, list[dict]]:
    # Explicit language columns: the bare accessors follow the UI language.
    options = [
        {"id": o.pk, "text_de": o.text_de or "", "text_en": o.text_en or ""}
        for o in question.options.order_by("position", "id")
    ]
    return question.text_de or "", question.text_en or "", options


def current(question) -> MotionVersion | None:
    return question.motion_versions.order_by("-number").first()


def _freeze(question) -> MotionVersion | None:
    """Add a version if none exists or the content differs from the newest."""
    text_de, text_en, options = _snapshot(question)
    latest = current(question)
    if (
        latest is not None
        and latest.text_de == text_de
        and latest.text_en == text_en
        and latest.options == options
    ):
        return None
    return MotionVersion.objects.create(
        question=question, number=(latest.number + 1) if latest else 1,
        text_de=text_de, text_en=text_en, options=options,
    )


@transaction.atomic
def freeze_all(meeting) -> None:
    """Version 1 for every agenda item that has none yet."""
    for question in meeting.questions.all():
        if not question.motion_versions.exists():
            _freeze(question)


def sync(question) -> MotionVersion | None:
    """``after_question_saved`` hook: record changes of a running meeting."""
    meeting = question.question_set
    if (
        meeting.type != QuestionSet.SetType.MEETING
        or meeting.meeting_state != QuestionSet.MeetingState.STARTED
    ):
        return None
    version = _freeze(question)
    if version is not None:
        from .live import notify  # live imports this module

        notify(meeting)  # members see the changed wording of the shown item
    return version


def lock_reason(question) -> str | None:
    """``question_lock_checks`` hook: no edits while a vote is open/counted
    (also for an item voted on en bloc with another)."""
    from .ballots import ballots_for  # ballots imports this module

    statuses = set(ballots_for(question).values_list("status", flat=True))
    if Ballot.Status.OPEN in statuses:
        return "A vote on this item is open."
    if Ballot.Status.CLOSED in statuses:
        return "This item has been voted on. Reset the vote to change it."
    return None
