# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Who may vote on an agenda item (§ 5.4): seats, their holders, presence."""
from rooms.models import Question, QuestionSet

from .models import CommitteeMember, MeetingInvite, MeetingSubstitution


def agenda(meeting: QuestionSet) -> list[Question]:
    """Agenda items in model order (position, id)."""
    return list(meeting.questions.all())


def number_of(meeting: QuestionSet, question: Question) -> int:
    """1-based item number of `question` on the meeting's agenda."""
    return [q.pk for q in agenda(meeting)].index(question.pk) + 1


def _numbers(meeting: QuestionSet) -> dict[int, int]:
    return {q.pk: n for n, q in enumerate(agenda(meeting), start=1)}


def _holder(seat, substitution, numbers, number) -> CommitteeMember:
    if substitution is None:
        return seat
    start = substitution.from_question_id
    if start is None or numbers[start] <= number:
        return substitution.deputy
    return seat


def _present(invite, numbers, number) -> bool:
    if invite is None or invite.entered_at is None:
        return False
    if invite.removed_at is None:
        return True
    # Removed after an item: still present up to and including that item.
    after = invite.removed_after_id
    return after is not None and numbers[after] >= number


def seat_holder(
    meeting: QuestionSet, seat: CommitteeMember, question: Question,
) -> CommitteeMember:
    """The deputy if a substitution covers `question` (whole meeting, or
    from an item not after it); otherwise the seat's member."""
    substitution = (
        MeetingSubstitution.objects.select_related("deputy")
        .filter(meeting=meeting, absent=seat).first()
    )
    numbers = _numbers(meeting)
    return _holder(seat, substitution, numbers, numbers[question.pk])


def is_present_for(
    invite: MeetingInvite | None, meeting: QuestionSet, question: Question,
) -> bool:
    """Entered and not removed for `question` (removed without an item, or
    after an earlier one)."""
    numbers = _numbers(meeting)
    return _present(invite, numbers, numbers[question.pk])


def eligible_voters(meeting: QuestionSet, question: Question) -> list[CommitteeMember]:
    """Present holders of all seats (voting members of non-observer groups),
    sorted by group and name. Each holder's ``group`` is set to the seat's
    group in memory (never saved)."""
    numbers = _numbers(meeting)
    number = numbers[question.pk]
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
        holder = _holder(seat, substitutions.get(seat.pk), numbers, number)
        if _present(invites.get(holder.pk), numbers, number):
            holder.group = seat.group
            voters.append(holder)
    voters.sort(key=lambda m: (m.group.position, m.group_id, m.name, m.pk))
    return voters
