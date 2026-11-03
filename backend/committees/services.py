# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Committee helpers: room access, templates, member lists, meeting lifecycle."""
import re

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from rooms.models import Question, QuestionSet, Room

from .models import (
    CommitteeGroup,
    CommitteeMember,
    GroupTemplate,
    MeetingInvite,
    MeetingSubstitution,
)

_NAME_EMAIL = re.compile(r"^(?P<name>.*?)\s*<(?P<email>[^<>]*)>$")
_SPLIT = re.compile(r"[\n\r,;]")


def managed_committee_rooms(user):
    """Committee rooms the user manages (owner/co-owner; staff: all)."""
    rooms = Room.objects.filter(kind=Room.Kind.COMMITTEE)
    if user.is_staff:
        return rooms
    return rooms.filter(Q(owners=user) | Q(owner=user)).distinct()


@transaction.atomic
def apply_template(room: Room, template: GroupTemplate) -> list[CommitteeGroup]:
    if room.committee_groups.filter(is_observer=False).exists():
        raise ValidationError("Groups already exist.")
    created = []
    for position, name in enumerate(template.groups, start=1):
        created.append(CommitteeGroup.objects.create(
            room=room, position=position,
            name_de=(name.get("de") or "").strip() or None,
            name_en=(name.get("en") or "").strip() or None,
        ))
    return created


def parse_member_list(text: str) -> tuple[list[tuple[str, str]], list[dict]]:
    """Parse pasted members: separators newline/comma/semicolon, formats
    ``Name <mail>`` and ``mail`` (name = part before the @). Empty segments
    are dropped silently."""
    entries: list[tuple[str, str]] = []
    skipped: list[dict] = []
    seen: set[str] = set()
    for segment in _SPLIT.split(text or ""):
        segment = segment.strip()
        if not segment:
            continue
        match = _NAME_EMAIL.match(segment)
        if match:
            name, email = match.group("name").strip(), match.group("email").strip()
        else:
            name, email = "", segment
        try:
            validate_email(email)
        except ValidationError:
            skipped.append({"line": segment, "reason": "invalid_email"})
            continue
        key = email.lower()
        if key in seen:
            skipped.append({"line": segment, "reason": "duplicate"})
            continue
        seen.add(key)
        entries.append((name or email.split("@", 1)[0], email))
    return entries, skipped


# --- Meetings ------------------------------------------------------------------

State = QuestionSet.MeetingState


def _check_not_ended(meeting: QuestionSet):
    if meeting.meeting_state == State.ENDED:
        raise ValidationError("The meeting has ended.")


def _check_question(meeting: QuestionSet, question: Question | None):
    if question is not None and question.question_set_id != meeting.pk:
        raise ValidationError("The item does not belong to this meeting.")


def suggest_deputy(meeting: QuestionSet, absent: CommitteeMember) -> CommitteeMember | None:
    """Next free deputy of the absent member's group: by rank (unranked
    last), then name."""
    used = MeetingSubstitution.objects.filter(meeting=meeting).values("deputy_id")
    return (
        CommitteeMember.objects.filter(
            group_id=absent.group_id, role=CommitteeMember.Role.DEPUTY,
        )
        .exclude(pk__in=used)
        .order_by(F("deputy_rank").asc(nulls_last=True), "name", "id")
        .first()
    )


def add_substitution(
    meeting: QuestionSet, absent: CommitteeMember, deputy: CommitteeMember,
    from_question: Question | None = None,
) -> MeetingSubstitution:
    """Record that `deputy` votes for `absent` (from `from_question` on, or the
    whole meeting). Duplicate absent/deputy raises IntegrityError (unique
    constraints). In a running meeting the deputy gets a link right away."""
    _check_not_ended(meeting)
    if absent.room_id != meeting.room_id or deputy.room_id != meeting.room_id:
        raise ValidationError("The member does not belong to this room.")
    if absent.group.is_observer:
        raise ValidationError("Observers cannot be substituted.")
    if absent.role != CommitteeMember.Role.VOTING:
        raise ValidationError("Only voting members can be substituted.")
    if deputy.group_id != absent.group_id:
        raise ValidationError("The substitute must belong to the same group.")
    if deputy.role != CommitteeMember.Role.DEPUTY:
        raise ValidationError("Only deputies can substitute.")
    _check_question(meeting, from_question)
    substitution = MeetingSubstitution.objects.create(
        meeting=meeting, absent=absent, deputy=deputy, from_question=from_question,
    )
    if meeting.meeting_state == State.STARTED:
        ensure_invites(meeting)
    return substitution


def remove_substitution(substitution: MeetingSubstitution):
    """Undo a substitution; in a running meeting the absent member gets
    their link (back). The deputy's link stays (never deleted)."""
    meeting = substitution.meeting
    _check_not_ended(meeting)
    substitution.delete()
    if meeting.meeting_state == State.STARTED:
        ensure_invites(meeting)


def participants(meeting: QuestionSet) -> list[CommitteeMember]:
    """Voting members and observers, minus those substituted for the whole
    meeting, plus every deputy put in by a substitution."""
    subs = MeetingSubstitution.objects.filter(meeting=meeting)
    fully_absent = subs.filter(from_question__isnull=True).values("absent_id")
    return list(
        CommitteeMember.objects.filter(room_id=meeting.room_id)
        .filter(
            (
                (Q(role=CommitteeMember.Role.VOTING) | Q(group__is_observer=True))
                & ~Q(pk__in=fully_absent)
            )
            | Q(pk__in=subs.values("deputy_id")),
        )
        .select_related("group")
        .order_by("group__position", "group_id", "name", "id"),
    )


@transaction.atomic
def ensure_invites(meeting: QuestionSet) -> list[MeetingInvite]:
    """Create the missing invites for all participants; never deletes."""
    have = set(meeting.invites.values_list("member_id", flat=True))
    for member in participants(meeting):
        if member.pk not in have:
            MeetingInvite.objects.get_or_create(meeting=meeting, member=member)
    return list(meeting.invites.select_related("member__group").order_by("id"))


def _transition(meeting: QuestionSet, expected: str, state: str, message: str):
    """Move `meeting` (the caller's instance, updated in place) from
    `expected` to `state` under a row lock."""
    current = (
        QuestionSet.objects.select_for_update()
        .values_list("meeting_state", flat=True).get(pk=meeting.pk)
    )
    if current != expected:
        meeting.meeting_state = current
        raise ValidationError(message)
    meeting.meeting_state = state
    meeting.save(update_fields=["meeting_state", "updated_at"])


@transaction.atomic
def start_meeting(meeting: QuestionSet) -> QuestionSet:
    _transition(meeting, State.DRAFT, State.STARTED, "The meeting has already started.")
    ensure_invites(meeting)
    return meeting


@transaction.atomic
def end_meeting(meeting: QuestionSet) -> QuestionSet:
    _transition(meeting, State.STARTED, State.ENDED, "Only a running meeting can be ended.")
    return meeting


def remove_invite(invite: MeetingInvite, after_question: Question | None = None):
    _check_not_ended(invite.meeting)
    _check_question(invite.meeting, after_question)
    invite.removed_at = timezone.now()
    invite.removed_after = after_question
    invite.save(update_fields=["removed_at", "removed_after"])
    return invite


def readmit_invite(invite: MeetingInvite):
    _check_not_ended(invite.meeting)
    invite.removed_at = None
    invite.removed_after = None
    invite.save(update_fields=["removed_at", "removed_after"])
    return invite


def invite_state(invite: MeetingInvite) -> str:
    """State of an existing invite (see resolve_invite)."""
    meeting = invite.meeting
    if meeting.meeting_state == State.ENDED:
        return "ended"
    if MeetingSubstitution.objects.filter(
        meeting=meeting, absent_id=invite.member_id, from_question__isnull=True,
    ).exists():
        return "replaced"
    if invite.removed_at is not None:
        return "removed"
    return "waiting" if meeting.meeting_state == State.DRAFT else "active"


def resolve_invite(token: str) -> tuple[MeetingInvite | None, str]:
    """Look up a personal link: unknown → ended → replaced → removed →
    waiting (draft) / active (started)."""
    invite = (
        MeetingInvite.objects.select_related("meeting", "member").filter(token=token).first()
        if token else None
    )
    if invite is None:
        return None, "unknown"
    return invite, invite_state(invite)
