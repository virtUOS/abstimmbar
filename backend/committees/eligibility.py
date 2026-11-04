# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Who may vote on an agenda item (§ 5.4): seats, their holders, presence."""
from django.db.models import Min

from rooms.models import Question, QuestionSet

from .models import Ballot, BallotItem, CommitteeMember, MeetingInvite, MeetingSubstitution


def agenda(meeting: QuestionSet) -> list[Question]:
    """Agenda items in model order (position, id)."""
    return list(meeting.questions.all())


def numbers(meeting: QuestionSet) -> dict[int, int]:
    """Question pk → 1-based item number."""
    return {q.pk: n for n, q in enumerate(agenda(meeting), start=1)}


# A substitution's `from_question` or a removal's `removed_after` can point
# at an item that is no longer on this agenda (moved to another set while
# the meeting was a draft). Such a reference counts as "from the start of
# the meeting": the substitution covers every item, the removal applies to
# every item. Never a KeyError for the whole meeting.
_OFF_AGENDA = (-1,)


def course(meeting: QuestionSet) -> dict[int, tuple]:
    """Question pk → sort key in the meeting's actual course.

    Items already voted on come first, in the order their first vote was
    opened (a reset re-vote keeps its place; an en bloc item shares the
    bundle's moment). Items not yet voted on follow in agenda order. So a
    chair calling TOPs out of order, or a resolution added later to an
    earlier TOP, is judged by when it happens, not where it stands: who left
    after TOP 5 stays gone, a deputy "from TOP 4" keeps the seat."""
    agenda_numbers = numbers(meeting)
    first: dict[int, object] = {}
    rows = list(
        Ballot.objects.filter(question__question_set_id=meeting.pk)
        .values("question_id").annotate(at=Min("opened_at"))
        .values_list("question_id", "at")
    ) + list(
        BallotItem.objects.filter(question__question_set_id=meeting.pk)
        .values("question_id").annotate(at=Min("ballot__opened_at"))
        .values_list("question_id", "at")
    )
    for pk, at in rows:
        if pk not in first or at < first[pk]:
            first[pk] = at
    return {
        pk: (0, first[pk], n) if pk in first else (1, n)
        for pk, n in agenda_numbers.items()
    }


def _holder(seat, substitution, course, key) -> CommitteeMember:
    if substitution is None:
        return seat
    start = substitution.from_question_id
    if start is None or course.get(start, _OFF_AGENDA) <= key:
        return substitution.deputy
    return seat


def _present(invite, course, key) -> bool:
    if invite is None or invite.entered_at is None:
        return False
    if invite.removed_at is None:
        return True
    # Removed after an item: still present up to and including that item.
    after = invite.removed_after_id
    return after is not None and course.get(after, _OFF_AGENDA) >= key


def seat_holder(
    meeting: QuestionSet, seat: CommitteeMember, question: Question,
) -> CommitteeMember:
    """The deputy if a substitution covers `question` (whole meeting, or
    from an item not after it); otherwise the seat's member."""
    substitution = (
        MeetingSubstitution.objects.select_related("deputy")
        .filter(meeting=meeting, absent=seat).first()
    )
    order = course(meeting)
    return _holder(seat, substitution, order, order[question.pk])


def is_present_for(
    invite: MeetingInvite | None, meeting: QuestionSet, question: Question,
) -> bool:
    """Entered and not removed for `question` (removed without an item, or
    after an earlier one)."""
    order = course(meeting)
    return _present(invite, order, order[question.pk])


def eligible_voters(meeting: QuestionSet, question: Question) -> list[CommitteeMember]:
    """Present holders of all seats (voting members of non-observer groups),
    sorted by group and name. Each holder's ``group`` is set to the seat's
    group in memory (never saved)."""
    order = course(meeting)
    key = order[question.pk]
    seats = (
        CommitteeMember.objects.filter(
            room_id=meeting.room_id, role=CommitteeMember.Role.VOTING,
            group__is_observer=False,
        ).select_related("group")
    )
    substitutions = {
        s.absent_id: s
        for s in MeetingSubstitution.objects.filter(meeting=meeting).select_related("deputy")
    }
    invites = {i.member_id: i for i in meeting.invites.all()}
    voters = []
    for seat in seats:
        holder = _holder(seat, substitutions.get(seat.pk), order, key)
        if _present(invites.get(holder.pk), order, key):
            holder.group = seat.group
            voters.append(holder)
    voters.sort(key=lambda m: (m.group.position, m.group_id, m.name, m.pk))
    return voters
