# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Snapshots of a running meeting for the SSE streams and the console.

Secrecy (§ 8): before a ballot is closed no payload carries counts, only
``voted``/``eligible`` per group; free texts never carry a name. Content is
shown in the canonical language (``text``); the other language appears as
``text_i18n`` only once the chair has confirmed the translation of that
wording (§ 7.6, ``translation_review``) — an unconfirmed translation never
leaves the server in a member-facing payload."""
from django.conf import settings
from django.utils import translation

from common.i18n_fields import resolve_translated_text, translated_map
from rooms.models import Question, QuestionSet

from . import agenda, ballots, eligibility, translation_review
from .models import (
    Ballot,
    BallotText,
    CommitteeGroup,
    CommitteeMember,
    MeetingControl,
    TranslationApproval,
)
from .presence import presence

CHOICE_KINDS = translation_review.CHOICE_KINDS


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


def _wording(question: Question, approval=...) -> dict:
    """Text, version, options and the confirmed translation — from the frozen
    version if any. ``translation`` is the review status (manager only)."""
    maps = translation_review.wording_maps(question)
    if approval is ...:
        approval = TranslationApproval.objects.filter(question=question).first()
    confirmed = translation_review.is_confirmed(maps, approval)
    return {
        "text": _canonical(maps["text"]),
        "text_i18n": translation_review.text_i18n(maps["text"], confirmed),
        "version": maps["version"],
        "translated": confirmed,
        "translation": translation_review.status_of(maps, approval),
        "options": [
            {
                "id": o["id"],
                "text": _canonical(o["text"]),
                "text_i18n": translation_review.text_i18n(o["text"], confirmed),
            }
            for o in maps["options"]
        ],
    }


def _shown_ballot(question: Question) -> Ballot | None:
    """The open or the most recently closed (not discarded) ballot."""
    return (
        ballots.ballots_for(question).exclude(status=Ballot.Status.DISCARDED)
        .order_by("-round", "-pk").first()
    )


def _bundle(meeting, ballot: Ballot | None, question: Question, tops) -> list[dict]:
    """The other items of an en bloc ballot (lead included when another of
    its items is shown), in agenda order, with the wording voted on."""
    if ballot is None:
        return []
    entries = [(i.question_id, i.version) for i in ballot.items.select_related("version")]
    if not entries:
        return []
    entries.append((ballot.question_id, ballot.version))
    numbers = eligibility.numbers(meeting)
    entries = sorted(
        (e for e in entries if e[0] != question.pk), key=lambda e: numbers.get(e[0], 0),
    )
    questions = Question.objects.in_bulk([qid for qid, _ in entries])
    approved = translation_review.approvals(questions)
    result = []
    for qid, version in entries:
        maps = translation_review.maps_of_version(questions[qid], version)
        confirmed = translation_review.is_confirmed(maps, approved.get(qid))
        result.append({
            "id": qid,
            "label": _label(agenda.top_of(meeting, qid, tops), qid),
            "text": _canonical(maps["text"]),
            "text_i18n": translation_review.text_i18n(maps["text"], confirmed),
            "version": version.number,
        })
    return result


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
        "voted": ballot.result.get("voted"),
        "tally_sum": ballot.result.get("tally_sum"),
    }


def _ballot_election(ballot: Ballot) -> dict | None:
    """The ballot paper of an election round; the runoff proposal only once
    the round is closed (it derives from the published totals)."""
    if ballot.question.kind != Question.Kind.ELECTION:
        return None
    return {
        "mode": ballots.election_mode(ballot),
        "max_votes": ballot.max_votes,
        "cumulate": ballot.cumulate,
        "candidates": [o["id"] for o in ballots.ballot_options(ballot)],
        "runoff_of": ballot.runoff_of_id,
        "proposal": ballots.runoff_proposal(ballot),
    }


def _item_election(question: Question, ballot: Ballot | None, options) -> dict | None:
    """Mode and settings for the ballot page: the shown round's, else (before
    the first round) as opening would freeze them."""
    if question.kind != Question.Kind.ELECTION:
        return None
    if ballot is not None:
        return {
            "mode": ballots.election_mode(ballot),
            "max_votes": ballot.max_votes,
            "cumulate": ballot.cumulate,
            "runoff": ballot.runoff_of_id is not None,
        }
    if len(options) <= 1:
        return {"mode": "approval", "max_votes": 1, "cumulate": False, "runoff": False}
    return {
        "mode": "multi" if question.max_votes >= 2 else "single",
        "max_votes": question.max_votes,
        "cumulate": question.cumulate,
        "runoff": False,
    }


def _ballot_options(ballot: Ballot | None, options: list[dict]) -> list[dict]:
    """An election round's candidates only (a runoff narrows them)."""
    if ballot is None or ballot.question.kind != Question.Kind.ELECTION:
        return options
    ids = {o["id"] for o in ballots.ballot_options(ballot)}
    return [o for o in options if o["id"] in ids]


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
        "finding": ballot.finding,
        "closed_automatically": ballot.closed_automatically,
        "texts": _texts(ballot, order) if released else None,
        "election": _ballot_election(ballot),
    }


def _context(meeting: QuestionSet):
    names = _group_names(meeting)
    order = dict(
        CommitteeGroup.objects.filter(room_id=meeting.room_id)
        .values_list("pk", "position"),
    )
    return names, order


def _control(meeting: QuestionSet) -> MeetingControl | None:
    return MeetingControl.objects.select_related("current_question").filter(
        meeting=meeting,
    ).first()


def _current_question(meeting: QuestionSet) -> Question | None:
    control = _control(meeting)
    return control.current_question if control else None


def _label(top: "agenda.Top | None", question_id: int) -> str:
    if top is None:
        return ""
    if len(top.question_ids) == 1:
        return str(top.number)
    return f"{top.number}{agenda.suffix(top.question_ids.index(question_id))}"


def _top_payload(top: "agenda.Top | None") -> dict | None:
    if top is None:
        return None
    return {
        "number": top.number,
        "section": top.section_id,
        "title": top.title,
        "description": top.description,
    }


def _public(meeting: QuestionSet, names, order) -> dict:
    payload = {
        "meeting": {
            "id": meeting.pk,
            "title": _canonical(translated_map(meeting, "title")),
            "state": meeting.meeting_state,
        },
        "item": None,
        "top": None,
    }
    control = _control(meeting)
    payload["trial"] = bool(control and control.trial)
    question = control.current_question if control else None
    tops = agenda.tops(meeting)
    if question is None:
        if control is not None and control.current_section_id is not None:
            payload["top"] = _top_payload(
                agenda.top_by_section(meeting, control.current_section_id, tops),
            )
        return payload
    top = agenda.top_of(meeting, question.pk, tops)
    payload["top"] = _top_payload(top)
    wording = _wording(question)
    options = wording["options"]
    number = wording["version"]
    ballot = _shown_ballot(question)
    payload["item"] = {
        "id": question.pk,
        "label": _label(top, question.pk),
        "kind": question.kind,
        "text": wording["text"],
        "text_i18n": wording["text_i18n"],
        "translated": wording["translated"],
        "version": number,
        "changed": (number or 0) > 1,
        "named": question.named_vote,
        "options": _ballot_options(ballot, options),
        "election": _item_election(question, ballot, options),
        "bundle": _bundle(meeting, ballot, question, tops),
        "ballot": _ballot_payload(ballot, question, names, order) if ballot else None,
    }
    return payload


def preview_payload(question: Question) -> dict:
    """A snapshot with `question` on the beamer and an empty open ballot —
    for the editor's ballot preview; nothing is stored."""
    meeting = question.question_set
    wording = _wording(question)
    options = wording["options"]
    number = wording["version"]
    top = agenda.top_of(meeting, question.pk)
    election = _item_election(question, None, options)
    ballot_election = None
    if election is not None:
        ballot_election = {
            "mode": election["mode"], "max_votes": election["max_votes"],
            "cumulate": election["cumulate"], "candidates": [o["id"] for o in options],
            "runoff_of": None, "proposal": None,
        }
    return {
        "meeting": {
            "id": meeting.pk,
            "title": _canonical(translated_map(meeting, "title")),
            "state": QuestionSet.MeetingState.STARTED,
        },
        "item": {
            "id": question.pk,
            "label": _label(top, question.pk),
            "kind": question.kind,
            "text": wording["text"],
            "text_i18n": wording["text_i18n"],
            "translated": wording["translated"],
            "version": number,
            "changed": (number or 0) > 1,
            "named": question.named_vote,
            "options": options,
            "election": election,
            "bundle": [],
            "ballot": {
                "id": 0, "status": Ballot.Status.OPEN, "round": 1,
                "progress": {"voted": 0, "eligible": 0, "groups": []},
                "result": None, "finding": "", "texts": None,
                "election": ballot_election,
            },
        },
        "top": _top_payload(top),
    }


def public_payload(meeting: QuestionSet) -> dict:
    """What the beamer and every ballot page see."""
    ballots.abort_stale(meeting)
    meeting.refresh_from_db(fields=["meeting_state"])
    return _public(meeting, *_context(meeting))


def _items(meeting: QuestionSet, tops: list) -> list[dict]:
    labels = agenda.labels(meeting)
    top_numbers = {qid: t.number for t in tops for qid in t.question_ids}
    # Every ballot counts for its lead and for each item bundled into it.
    statuses: dict[int, list[str]] = {}
    bundle_lead: dict[int, int] = {}
    for ballot in Ballot.objects.filter(
        question__question_set_id=meeting.pk,
    ).prefetch_related("items"):
        bundled = [i.question_id for i in ballot.items.all()]
        for qid in (ballot.question_id, *bundled):
            statuses.setdefault(qid, []).append(ballot.status)
        if ballot.status != Ballot.Status.DISCARDED:
            for qid in bundled:
                bundle_lead[qid] = ballot.question_id
    items = []
    agenda_questions = list(eligibility.agenda(meeting))
    approved = translation_review.approvals(q.pk for q in agenda_questions)
    for question in agenda_questions:
        wording = _wording(question, approved.get(question.pk))
        own = statuses.get(question.pk, [])
        live = [s for s in own if s != Ballot.Status.DISCARDED]
        items.append({
            "id": question.pk,
            "label": labels.get(question.pk, ""),
            "top": top_numbers.get(question.pk),
            "kind": question.kind,
            "text": wording["text"],
            "version": wording["version"],
            "translation": wording["translation"],
            "named": question.named_vote,
            "ballot_status": (
                Ballot.Status.OPEN if Ballot.Status.OPEN in live
                else Ballot.Status.CLOSED if live else None
            ),
            "discarded": len(own) - len(live),
            "bundle_lead": bundle_lead.get(question.pk),
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
    tops = agenda.tops(meeting)
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
        items=_items(meeting, tops),
        tops=[
            {**_top_payload(t), "items": list(t.question_ids)}
            for t in tops
        ],
        attendance=_attendance(meeting, names, order),
        texts=texts,
        open_ballot=open_ballot,
        notes=[
            {"section": n.section_id, "question": n.question_id, "text": n.text}
            for n in meeting.top_notes.order_by("pk")
        ],
    )
    return payload
