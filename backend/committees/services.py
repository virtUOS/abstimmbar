# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Committee helpers: room access, templates, member lists, meeting lifecycle."""
import re

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.conf import settings
from django.db.models import F, Max, Q
from django.utils.html import escape
from django.utils import timezone

from rooms.models import AnswerOption, Question, QuestionSet, Room, Section

from . import eligibility, versions
from .presence import presence
from .models import (
    Ballot,
    CommitteeGroup,
    CommitteeMember,
    GroupTemplate,
    MeetingControl,
    MeetingInvite,
    MeetingSubstitution,
    MotionVersion,
    TopNote,
)

_NAME_EMAIL = re.compile(r"^(?P<name>.*?)\s*<(?P<email>[^<>]*)>$")
# EmailField column length (Django's validator alone would allow 320).
MAX_EMAIL_LENGTH = 254


def _notify(meeting: QuestionSet) -> None:
    """Push fresh snapshots to the meeting's streams after commit."""
    from .live import notify  # live imports this module

    notify(meeting)


def managed_committee_rooms(user):
    """Committee rooms the user manages (owner/co-owner; staff: all)."""
    rooms = Room.objects.filter(kind=Room.Kind.COMMITTEE)
    if user.is_staff:
        return rooms
    return rooms.filter(Q(owners=user) | Q(owner=user)).distinct()


KNOWN_PEOPLE_MIN_QUERY = 2
KNOWN_PEOPLE_LIMIT = 10


def known_people(user, room: Room, query: str) -> list[dict]:
    """Autocomplete for adding members to ``room``: people from the user's own
    rooms only — members of committee rooms they own or co-own, and the
    co-owners of any of their rooms (themselves included). Never other
    accounts, also not for staff. Matches name or e-mail; people without an
    e-mail address or already in ``room`` are left out."""
    query = query.strip()
    if len(query) < KNOWN_PEOPLE_MIN_QUERY:
        return []
    own_rooms = Room.objects.filter(Q(owners=user) | Q(owner=user))
    taken = {
        email.lower()
        for email in room.committee_members.exclude(email="").values_list("email", flat=True)
    }
    found: dict[str, dict] = {}
    members = (
        CommitteeMember.objects.filter(room__in=own_rooms)
        .exclude(room=room).exclude(email="")
        .filter(Q(name__icontains=query) | Q(email__icontains=query))
        .order_by("name")
    )
    for member in members[:KNOWN_PEOPLE_LIMIT * 3]:
        found.setdefault(member.email.lower(), {"name": member.name, "email": member.email})
    matches_name = (
        Q(first_name__icontains=query) | Q(last_name__icontains=query)
        | Q(username__icontains=query) | Q(email__icontains=query)
    )
    owners = (
        get_user_model().objects.filter(rooms__in=own_rooms).exclude(email="")
        .filter(matches_name).distinct()
    )
    for owner in owners[:KNOWN_PEOPLE_LIMIT * 3]:
        found.setdefault(owner.email.lower(), {
            "name": owner.get_full_name() or owner.username, "email": owner.email,
        })
    people = [person for key, person in found.items() if key not in taken]
    people.sort(key=lambda person: person["name"].lower())
    return people[:KNOWN_PEOPLE_LIMIT]


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


def _split_outside(text: str, separators: str) -> list[str]:
    """Split `text` on any of `separators`, except inside ``"…"`` or ``<…>``."""
    pieces: list[str] = []
    current: list[str] = []
    in_quote = in_angle = False
    for char in text:
        if char == '"' and not in_angle:
            in_quote = not in_quote
        elif char == "<" and not in_quote:
            in_angle = True
        elif char == ">" and not in_quote:
            in_angle = False
        elif char in separators and not in_quote and not in_angle:
            pieces.append("".join(current))
            current = []
            continue
        current.append(char)
    pieces.append("".join(current))
    return pieces


def _segments(text: str) -> list[str]:
    """Newline always and ``;`` (outside quotes) separate entries; ``,`` only between entries,
    so ``Rolf, Rüdiger <r@x.org>`` stays one entry: comma pieces without an
    address are held back and joined to a following ``Name <mail>`` piece
    (as its name); otherwise they stand alone."""
    segments: list[str] = []
    chunks = [
        chunk for line in re.split(r"[\n\r]", text)
        for chunk in _split_outside(line, ";")
    ]
    for chunk in chunks:
        pending: list[str] = []
        for piece in _split_outside(chunk, ","):
            if not piece.strip():
                continue
            if "@" not in piece and "<" not in piece:
                pending.append(piece)
                continue
            head = piece.split("<", 1)[0]
            if "<" in piece and "@" not in head and pending:
                segments.append(",".join([*pending, piece]))
            else:
                segments.extend(pending)
                segments.append(piece)
            pending = []
        segments.extend(pending)
    return segments


def parse_member_list(text: str) -> tuple[list[tuple[str, str]], list[dict]]:
    """Parse pasted members: separators newline/semicolon/comma (a comma inside
    ``"…"`` or in a ``Last, First <mail>`` name does not separate), formats
    ``Name <mail>``, ``"Name" <mail>`` and ``mail`` (name = part before the
    @). Empty segments are dropped silently."""
    entries: list[tuple[str, str]] = []
    skipped: list[dict] = []
    seen: set[str] = set()
    for segment in _segments(text or ""):
        segment = segment.strip()
        if not segment:
            continue
        match = _NAME_EMAIL.match(segment)
        if match:
            name = match.group("name").strip().strip('"').strip()
            email = match.group("email").strip()
        else:
            name, email = "", segment
        try:
            if len(email) > MAX_EMAIL_LENGTH:
                raise ValidationError("Address too long.")
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


def check_not_ended(meeting: QuestionSet):
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
    check_not_ended(meeting)
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
    _notify(meeting)
    return substitution


def remove_substitution(substitution: MeetingSubstitution):
    """Undo a substitution; in a running meeting the absent member gets
    their link (back). The deputy's link stays (never deleted)."""
    meeting = substitution.meeting
    check_not_ended(meeting)
    substitution.delete()
    if meeting.meeting_state == State.STARTED:
        ensure_invites(meeting)
    _notify(meeting)


def _seat_q(meeting: QuestionSet) -> Q:
    """Members who hold a seat in this meeting at all: voting members,
    observers, and deputies put in by a substitution. Shared by
    `participants` and `invite_state` so the two cannot drift."""
    deputies = MeetingSubstitution.objects.filter(meeting=meeting).values("deputy_id")
    return (
        Q(role=CommitteeMember.Role.VOTING)
        | Q(group__is_observer=True)
        | Q(pk__in=deputies)
    )


def _fully_absent_ids(meeting: QuestionSet):
    return MeetingSubstitution.objects.filter(
        meeting=meeting, from_question__isnull=True,
    ).values("absent_id")


def participants(meeting: QuestionSet) -> list[CommitteeMember]:
    """Voting members and observers, minus those substituted for the whole
    meeting, plus every deputy put in by a substitution."""
    return list(
        CommitteeMember.objects.filter(room_id=meeting.room_id)
        .filter(_seat_q(meeting))
        .exclude(pk__in=_fully_absent_ids(meeting))
        .select_related("group")
        .order_by("group__position", "group_id", "name", "id"),
    )


@transaction.atomic
def ensure_invites(meeting: QuestionSet) -> list[MeetingInvite]:
    """Create the missing invites for all participants; never deletes."""
    have = set(meeting.invites.values_list("member_id", flat=True))
    created = False
    for member in participants(meeting):
        if member.pk not in have:
            _, new = MeetingInvite.objects.get_or_create(meeting=meeting, member=member)
            created = created or new
    if created and meeting.meeting_state == State.STARTED:
        _notify(meeting)  # attendance changed
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
def start_meeting(meeting: QuestionSet, trial: bool = False) -> QuestionSet:
    # A meeting without anything to vote on is not a committee session in
    # Abstimmbar's sense (we are no committee management system).
    if not meeting.questions.exists():
        raise ValidationError(
            "Add at least one agenda item with a vote before starting.",
            code="empty_agenda",
        )
    _transition(meeting, State.DRAFT, State.STARTED, "The meeting has already started.")
    snapshot = None
    if trial:
        snapshot = {
            "questions": {
                str(pk): pos for pk, pos in meeting.questions.values_list("pk", "position")
            },
            "sections": {
                str(pk): pos for pk, pos in meeting.sections.values_list("pk", "position")
            },
        }
    MeetingControl.objects.update_or_create(
        meeting_id=meeting.pk,
        defaults={"started_at": timezone.now(), "trial": trial, "trial_snapshot": snapshot},
    )
    ensure_invites(meeting)
    # Members whose ballot page is already open (connected while the meeting
    # was a draft) have entered: the stream's enter() was a no-op then.
    connected = [
        pk for pk in meeting.invites.filter(entered_at__isnull=True).values_list("pk", flat=True)
        if presence.status(pk)[0]
    ]
    MeetingInvite.objects.filter(pk__in=connected).update(entered_at=timezone.now())
    versions.freeze_all(meeting)
    _notify(meeting)
    return meeting


@transaction.atomic
def end_meeting(meeting: QuestionSet) -> QuestionSet:
    from . import ballots  # ballots imports this module

    ballots.abort_stale(meeting)
    # Under the meeting row lock that open_ballot takes as well.
    QuestionSet.objects.select_for_update().values_list("pk", flat=True).get(pk=meeting.pk)
    if Ballot.objects.filter(
        question__question_set_id=meeting.pk, status=Ballot.Status.OPEN,
    ).exists():
        raise ValidationError("A vote is still open.", code="vote_open")
    if MeetingControl.objects.filter(meeting_id=meeting.pk, trial=True).exists():
        return _reset_trial(meeting)
    _transition(meeting, State.STARTED, State.ENDED, "Only a running meeting can be ended.")
    MeetingControl.objects.update_or_create(
        meeting_id=meeting.pk, defaults={"ended_at": timezone.now()},
    )
    _notify(meeting)
    return meeting


def _restore_agenda(meeting: QuestionSet, snapshot: dict | None) -> None:
    """Put the agenda back to its state at the start of the test run:
    delete items and TOPs added since, restore positions and the texts
    (items and options) from version 1, frozen at the start."""
    if snapshot is None:
        return
    q_pos = {int(k): v for k, v in snapshot.get("questions", {}).items()}
    s_pos = {int(k): v for k, v in snapshot.get("sections", {}).items()}
    added = meeting.questions.exclude(pk__in=q_pos)
    MeetingSubstitution.objects.filter(meeting_id=meeting.pk, from_question__in=added).update(
        from_question=None,
    )
    added.delete()
    meeting.sections.exclude(pk__in=s_pos).delete()
    for pk, position in meeting.sections.values_list("pk", "position"):
        if position != s_pos[pk]:
            Section.objects.filter(pk=pk).update(position=s_pos[pk])
    first = {
        v.question_id: v
        for v in MotionVersion.objects.filter(question__question_set_id=meeting.pk, number=1)
    }
    for question in meeting.questions.all():
        fields = []
        if question.position != q_pos[question.pk]:
            question.position = q_pos[question.pk]
            fields.append("position")
        version = first.get(question.pk)
        if version is not None:
            if (question.text_de or "") != version.text_de:
                question.text_de = version.text_de
                fields.append("text_de")
            if (question.text_en or "") != version.text_en:
                question.text_en = version.text_en
                fields.append("text_en")
            _restore_options(question, version.options)
        if fields:
            # Plain update: no question-saved hooks (no new versions).
            Question.objects.filter(pk=question.pk).update(
                **{f: getattr(question, f) for f in fields},
            )


def _restore_options(question: Question, frozen: list[dict]) -> None:
    """Options as in a version: added ones go, deleted ones come back
    (same id), texts and order as frozen."""
    existing = {o.pk: o for o in question.options.all()}
    ids = [o["id"] for o in frozen]
    for pk, option in existing.items():
        if pk not in ids:
            option.delete()  # added during the test run
    for index, old in enumerate(frozen):
        option = existing.get(old["id"])
        if option is None:
            AnswerOption.objects.create(
                pk=old["id"], question=question, position=index,
                text_de=old["text_de"], text_en=old["text_en"],
            )
        elif (
            (option.text_de or "") != old["text_de"]
            or (option.text_en or "") != old["text_en"]
            or option.position != index
        ):
            AnswerOption.objects.filter(pk=option.pk).update(
                text_de=old["text_de"], text_en=old["text_en"], position=index,
            )


def _reset_trial(meeting: QuestionSet) -> QuestionSet:
    """End of a test run: wipe ballots, motion versions, attendance and the
    control state, and restore the agenda as it was at the start;
    substitutions stay."""
    from . import ballots  # ballots imports this module

    _transition(meeting, State.STARTED, State.DRAFT, "Only a running meeting can be ended.")
    ballot_ids = list(
        Ballot.objects.filter(question__question_set_id=meeting.pk)
        .values_list("pk", flat=True),
    )
    Ballot.objects.filter(pk__in=ballot_ids).delete()  # seats, votes, texts, items cascade
    # Before the restore: removals may point at items added in the test run.
    MeetingInvite.objects.filter(meeting_id=meeting.pk).update(
        entered_at=None, removed_at=None, removed_after=None,
    )
    snapshot = (
        MeetingControl.objects.filter(meeting_id=meeting.pk)
        .values_list("trial_snapshot", flat=True).first()
    )
    _restore_agenda(meeting, snapshot)
    MotionVersion.objects.filter(question__question_set_id=meeting.pk).delete()
    TopNote.objects.filter(meeting=meeting).delete()
    for pk in ballot_ids:
        transaction.on_commit(lambda pk=pk: ballots.secret_tally.discard(pk))
    MeetingControl.objects.filter(meeting_id=meeting.pk).update(
        started_at=None, ended_at=None, current_question=None, current_section=None,
        trial=False, trial_snapshot=None,
    )
    _notify(meeting)
    return meeting


def remove_invite(invite: MeetingInvite, after_question: Question | None = None):
    check_not_ended(invite.meeting)
    _check_question(invite.meeting, after_question)
    invite.removed_at = timezone.now()
    invite.removed_after = after_question
    invite.save(update_fields=["removed_at", "removed_after"])
    _notify(invite.meeting)
    return invite


def readmit_invite(invite: MeetingInvite):
    check_not_ended(invite.meeting)
    invite.removed_at = None
    invite.removed_after = None
    invite.save(update_fields=["removed_at", "removed_after"])
    _notify(invite.meeting)
    return invite


def invite_state(invite: MeetingInvite, question: Question | None = None) -> str:
    """State of an existing invite (see resolve_invite); a removal "after
    an item" is judged at `question` (default: the item currently shown)."""
    meeting = invite.meeting
    if meeting.meeting_state == State.ENDED:
        return "ended"
    if _fully_absent_ids(meeting).filter(absent_id=invite.member_id).exists():
        return "replaced"
    if not CommitteeMember.objects.filter(
        _seat_q(meeting), pk=invite.member_id, room_id=meeting.room_id,
    ).exists():
        return "inactive"
    if _removed_for(invite, question):
        return "removed"
    return "waiting" if meeting.meeting_state == State.DRAFT else "active"


def _removed_for(invite: MeetingInvite, question: Question | None) -> bool:
    """Whether a removal applies at `question` (default: the item currently
    shown). Removed without an item: always. Removed after an item: only
    once the meeting is past it (eligibility.course) — up to and including
    that item (and while no item is shown) the member is still there. An
    item that left the agenda counts as removal from the start (§ 5.4,
    see eligibility._present)."""
    if invite.removed_at is None:
        return False
    after = invite.removed_after_id
    if after is None:
        return True
    order = eligibility.course(invite.meeting)
    if after not in order:
        return True
    if question is not None:
        current = question.pk
    else:
        current = (
            MeetingControl.objects.filter(meeting_id=invite.meeting_id)
            .values_list("current_question_id", flat=True).first()
        )
    if current is None or current not in order:
        return False
    return order[current] > order[after]


def resolve_invite(token: str) -> tuple[MeetingInvite | None, str]:
    """Look up a personal link: unknown → ended → replaced → inactive (no
    longer holds a seat) → removed → waiting (draft) / active (started)."""
    invite = (
        MeetingInvite.objects.select_related("meeting", "member").filter(token=token).first()
        if token else None
    )
    if invite is None:
        return None, "unknown"
    return invite, invite_state(invite)


MAX_NOTE_LENGTH = 2000


@transaction.atomic
def set_top_note(
    meeting: QuestionSet, *, section: Section | None = None,
    question: Question | None = None, text: str,
) -> TopNote | None:
    """The chair's plain-text note on a TOP (a section, or a question without
    a section); empty text deletes it. Only while the meeting is running."""
    current = (
        QuestionSet.objects.select_for_update()
        .values_list("meeting_state", flat=True).get(pk=meeting.pk)
    )
    meeting.meeting_state = current
    if current != State.STARTED:
        raise ValidationError("The meeting is not running.", code="not_started")
    if (section is None) == (question is None):
        raise ValidationError("A note targets exactly one TOP.", code="invalid")
    if not isinstance(text, str):
        raise ValidationError("Invalid note.", code="invalid")
    if len(text) > MAX_NOTE_LENGTH:
        raise ValidationError("The note is too long.", code="invalid")
    if (section is not None and section.question_set_id != meeting.pk) or (
        question is not None and question.question_set_id != meeting.pk
    ):
        raise ValidationError("The TOP does not belong to this meeting.", code="invalid")
    if question is not None and question.section_id is not None:
        raise ValidationError("The question belongs to a TOP; note the TOP.", code="invalid")
    target = {"section": section} if section is not None else {"question": question}
    existing = TopNote.objects.filter(meeting=meeting, **target)
    if not text.strip():
        existing.delete()
        note = None
    else:
        note, _created = TopNote.objects.update_or_create(
            meeting=meeting, **target, defaults={"text": text},
        )
    _notify(meeting)
    return note


@transaction.atomic
def add_resolution(
    meeting: QuestionSet, text: str, section: Section | None, named: bool,
) -> Question:
    """The chair adds a resolution to the running meeting.

    Inserted after the last vote of ``section`` (after its header when it is
    empty); without a section it becomes a new TOP at the end of the agenda.
    """
    # Same meeting row lock as open_ballot / _transition.
    current = (
        QuestionSet.objects.select_for_update()
        .values_list("meeting_state", flat=True).get(pk=meeting.pk)
    )
    meeting.meeting_state = current
    if current != State.STARTED:
        raise ValidationError("The meeting is not running.", code="not_started")
    text = (text or "").strip()
    if not text:
        raise ValidationError("The text must not be empty.", code="invalid")
    if len(text) > 1000:
        raise ValidationError("The text is too long.", code="invalid")
    if section is not None and section.question_set_id != meeting.pk:
        raise ValidationError("The TOP does not belong to this meeting.", code="invalid")

    if section is None:
        last = max(
            meeting.questions.aggregate(m=Max("position"))["m"] or 0,
            meeting.sections.aggregate(m=Max("position"))["m"] or 0,
        )
        position = last + 1
    else:
        last_q = meeting.questions.filter(section=section).aggregate(m=Max("position"))["m"]
        position = (last_q if last_q is not None else section.position) + 1
        meeting.questions.filter(position__gte=position).update(position=F("position") + 1)
        meeting.sections.filter(position__gte=position).update(position=F("position") + 1)

    lang = settings.MODELTRANSLATION_DEFAULT_LANGUAGE
    question = Question.objects.create(
        question_set=meeting, section=section, kind=Question.Kind.RESOLUTION,
        named_vote=named, position=position, **{f"text_{lang}": f"<p>{escape(text)}</p>"},
    )
    versions.sync(question)
    _notify(meeting)
    return question
