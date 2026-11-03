# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Snapshots of a running meeting for the SSE streams and the console.

Secrecy (§ 8): before a ballot is closed no payload carries counts, only
``voted``/``eligible`` per group; free texts never carry a name. Content is
shown in the canonical language only (PR 2; confirmation of translations
follows in PR 4)."""
from django.conf import settings
from django.utils import translation

from common.i18n_fields import resolve_translated_text, translated_map
from rooms.models import Question, QuestionSet

from . import ballots, eligibility, versions
from .models import Ballot, BallotText, CommitteeGroup, CommitteeMember, MeetingControl
from .presence import presence

CHOICE_KINDS = (Question.Kind.SINGLE_CHOICE, Question.Kind.MULTIPLE_CHOICE)


def _canonical(value) -> str:
    with translation.override(settings.MODELTRANSLATION_DEFAULT_LANGUAGE):
        return resolve_translated_text(value)


def group_name(group: CommitteeGroup) -> str:
    return _canonical(translated_map(group, "name"))


def _group_names(meeting: QuestionSet) -> dict[int, str]:
    return {
        g.pk: group_name(g)
        for g in CommitteeGroup.objects.filter(room_id=meeting.room_id)
    }


def _wording(question: Question) -> tuple[str, int | None, list[dict]]:
    """Text, version number and options — from the frozen version if any."""
    version = versions.current(question)
    if version is None:
        text = _canonical(translated_map(question, "text"))
        options = [
            {"id": o.pk, "text": _canonical(translated_map(o, "text"))}
            for o in question.options.order_by("position", "id")
        ]
        number = None
    else:
        text = _canonical({"de": version.text_de, "en": version.text_en})
        options = [
            {"id": o["id"], "text": _canonical({"de": o["text_de"], "en": o["text_en"]})}
            for o in version.options
        ]
        number = version.number
    if question.kind not in CHOICE_KINDS:
        options = []
    return text, number, options


def _shown_ballot(question: Question) -> Ballot | None:
    """The open or the most recently closed (not discarded) ballot."""
    return (
        question.ballots.exclude(status=Ballot.Status.DISCARDED)
        .order_by("-round").first()
    )


def _texts(ballot: Ballot, group_order: dict[int, int]) -> list[dict]:
    """Free texts without names: secret ones as written (shuffled at close),
    named ones sorted by group and text so the order reveals nobody."""
    if ballot.secret:
        texts = [
            {"group": t.group_id, "text": t.text}
            for t in BallotText.objects.filter(ballot=ballot).order_by("id")
        ]
    else:
        seat_groups = dict(ballot.seats.values_list("member_id", "group_id"))
        texts = sorted(
            (
                {"group": seat_groups.get(v.member_id), "text": v.answer.get("text")}
                for v in ballot.named_votes.all()
                if v.answer.get("text")
            ),
            key=lambda t: t["text"],
        )
    return sorted(texts, key=lambda t: group_order.get(t["group"], 0))


def _progress(ballot: Ballot, names: dict[int, str], order: dict[int, int]) -> dict:
    groups: dict[int, dict] = {}
    for group_id, voted in ballot.seats.values_list("group_id", "voted"):
        group = groups.setdefault(
            group_id, {"id": group_id, "name": names.get(group_id, ""), "voted": 0, "eligible": 0},
        )
        group["eligible"] += 1
        group["voted"] += int(voted)
    rows = sorted(groups.values(), key=lambda g: (order.get(g["id"], 0), g["id"]))
    return {
        "voted": sum(g["voted"] for g in rows),
        "eligible": sum(g["eligible"] for g in rows),
        "groups": rows,
    }


def _result(ballot: Ballot, names: dict[int, str]) -> dict | None:
    if ballot.status != Ballot.Status.CLOSED or not ballot.result:
        return None
    return {
        "groups": [
            {"id": g["group"], "name": names.get(g["group"], ""), "counts": g["counts"]}
            for g in ballot.result["groups"]
        ],
        "total": {"counts": ballot.result["total"]["counts"]},
    }


def _ballot_payload(ballot, question, names, order) -> dict:
    released = (
        question.kind == Question.Kind.OPEN_TEXT
        and ballot.status == Ballot.Status.CLOSED
        and ballot.texts_released
    )
    return {
        "id": ballot.pk,
        "status": ballot.status,
        "round": ballot.round,
        "progress": _progress(ballot, names, order),
        "result": _result(ballot, names),
        "texts": _texts(ballot, order) if released else None,
    }


def _context(meeting: QuestionSet):
    names = _group_names(meeting)
    order = dict(
        CommitteeGroup.objects.filter(room_id=meeting.room_id)
        .values_list("pk", "position"),
    )
    return names, order


def _current_question(meeting: QuestionSet) -> Question | None:
    control = MeetingControl.objects.select_related("current_question").filter(
        meeting=meeting,
    ).first()
    return control.current_question if control else None


def _public(meeting: QuestionSet, names, order) -> dict:
    payload = {
        "meeting": {
            "id": meeting.pk,
            "title": _canonical(translated_map(meeting, "title")),
            "state": meeting.meeting_state,
        },
        "item": None,
    }
    question = _current_question(meeting)
    if question is None:
        return payload
    text, number, options = _wording(question)
    ballot = _shown_ballot(question)
    payload["item"] = {
        "id": question.pk,
        "number": eligibility.number_of(meeting, question),
        "kind": question.kind,
        "text": text,
        "version": number,
        "changed": (number or 0) > 1,
        "named": question.named_vote,
        "options": options,
        "ballot": _ballot_payload(ballot, question, names, order) if ballot else None,
    }
    return payload


def public_payload(meeting: QuestionSet) -> dict:
    """What the beamer and every ballot page see."""
    ballots.abort_stale(meeting)
    meeting.refresh_from_db(fields=["meeting_state"])
    return _public(meeting, *_context(meeting))


def _items(meeting: QuestionSet) -> list[dict]:
    items = []
    for number, question in enumerate(eligibility.agenda(meeting), start=1):
        text, version, _ = _wording(question)
        statuses = list(question.ballots.values_list("status", flat=True))
        live = [s for s in statuses if s != Ballot.Status.DISCARDED]
        items.append({
            "id": question.pk,
            "number": number,
            "kind": question.kind,
            "text": text,
            "version": version,
            "named": question.named_vote,
            "ballot_status": (
                Ballot.Status.OPEN if Ballot.Status.OPEN in live
                else Ballot.Status.CLOSED if live else None
            ),
            "discarded": len(statuses) - len(live),
        })
    return items


def _attendance(meeting: QuestionSet, names, order) -> list[dict]:
    invites = sorted(
        meeting.invites.select_related("member__group"),
        key=lambda i: (order.get(i.member.group_id, 0), i.member.group_id, i.member.name, i.pk),
    )
    rows = []
    for invite in invites:
        member = invite.member
        connected, since = presence.status(invite.pk)
        rows.append({
            "invite": invite.pk,
            "name": member.name,
            "group": names.get(member.group_id, ""),
            "observer": member.group.is_observer,
            "deputy": member.role == CommitteeMember.Role.DEPUTY,
            "entered": invite.entered_at is not None,
            "removed": invite.removed_at is not None,
            "connected": connected,
            "disconnected_since": since.isoformat() if since else None,
        })
    return rows


def manager_payload(meeting: QuestionSet) -> dict:
    """The console: the public snapshot plus agenda, attendance, the open
    ballot and — once a free-text vote is closed — its texts regardless of
    their release (still without names)."""
    ballots.abort_stale(meeting)
    meeting.refresh_from_db(fields=["meeting_state"])
    names, order = _context(meeting)
    payload = _public(meeting, names, order)
    texts = None
    question = _current_question(meeting)
    if question is not None and question.kind == Question.Kind.OPEN_TEXT:
        ballot = _shown_ballot(question)
        if ballot is not None and ballot.status == Ballot.Status.CLOSED:
            texts = _texts(ballot, order)
    open_ballot = Ballot.objects.filter(
        question__question_set_id=meeting.pk, status=Ballot.Status.OPEN,
    ).values_list("pk", flat=True).first()
    payload.update(
        items=_items(meeting),
        attendance=_attendance(meeting, names, order),
        texts=texts,
        open_ballot=open_ballot,
    )
    return payload
