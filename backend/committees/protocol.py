# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Protocol data of an ended meeting (§ 9): agenda, attendance, results.

For humans, so names are fine (unlike the seal content). Secrecy (§ 8) still
holds: no vote timestamps, and a secret ballot lists neither voters nor
choices per person — only the counts. Content is in the canonical language
(``CONTENT_DEFAULT_LANGUAGE``, i.e.
``MODELTRANSLATION_DEFAULT_LANGUAGE``), taken from the motion version voted on.
"""
from django.core.exceptions import ValidationError
from django.db.models import Prefetch

from common.i18n_fields import translated_map
from rooms.models import Question, QuestionSet

from . import agenda
from .models import (
    Ballot,
    BallotItem,
    BallotSeat,
    CommitteeGroup,
    MeetingControl,
    MeetingSubstitution,
    MotionVersion,
    NamedVote,
    SealLink,
)
from .payloads import _canonical, group_name

RESOLUTION_KEYS = ("yes", "no", "abstain")


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _labels(tops: list[agenda.Top]) -> dict[int, str]:
    out: dict[int, str] = {}
    for top in tops:
        for i, qid in enumerate(top.question_ids):
            out[qid] = str(top.number) if len(top.question_ids) == 1 else (
                f"{top.number}{agenda.suffix(i)}"
            )
    return out


def _version_text(version: MotionVersion | None, question: Question) -> str:
    if version is None:
        return _canonical(translated_map(question, "text"))
    return _canonical({"de": version.text_de, "en": version.text_en})


def _options(kind: str, version: MotionVersion | None) -> list[dict]:
    """Count keys (as in ``ballots._count_keys``) with their texts: option
    texts for ``opt:<id>``, the plain key for fixed keys (the frontend
    translates those)."""
    if kind == Question.Kind.RESOLUTION:
        return [{"key": k, "text": k} for k in RESOLUTION_KEYS]
    if kind == Question.Kind.OPEN_TEXT:
        return [{"key": "text", "text": "text"}, {"key": "abstain", "text": "abstain"}]
    options = [
        {
            "key": f"opt:{o['id']}",
            "text": _canonical({"de": o.get("text_de", ""), "en": o.get("text_en", "")}),
        }
        for o in (version.options if version else [])
    ]
    return [*options, {"key": "abstain", "text": "abstain"}]


def _same_wording(a: MotionVersion, b: MotionVersion) -> bool:
    return a.text_de == b.text_de and a.text_en == b.text_en and a.options == b.options


def _latest_link(ballot: Ballot, kind: str) -> SealLink | None:
    links = [link for link in ballot.seal_links.all() if link.kind == kind]
    return max(links, key=lambda link: link.seq, default=None)


def _result(ballot: Ballot, names: dict[int, str]) -> dict:
    result = ballot.result or {"groups": [], "total": {}, "voted": 0, "tally_sum": 0}
    return {
        "groups": [
            {
                "name": names.get(g["group"], ""),
                "eligible": g["eligible"],
                "voted": g["voted"],
                "counts": g["counts"],
            }
            for g in result["groups"]
        ],
        "total": result["total"],
        "voted": result["voted"],
        "tally_sum": result["tally_sum"],
        "count_check_ok": result["voted"] == result["tally_sum"],
    }


def _voters(ballot: Ballot, names, order) -> list[dict]:
    """Who voted (§ 9.1) — for a secret ballot only *that* they voted."""
    seats = sorted(
        (s for s in ballot.seats.all() if s.voted),
        key=lambda s: (order.get(s.group_id, 0), s.group_id, s.member.name, s.member_id),
    )
    return [{"name": s.member.name, "group": names.get(s.group_id, "")} for s in seats]


def _named_votes(ballot: Ballot, names, order) -> list[dict]:
    if ballot.secret:
        return []
    seat_groups = {s.member_id: s.group_id for s in ballot.seats.all()}
    rows = []
    for vote in ballot.named_votes.all():
        group_id = seat_groups.get(vote.member_id, vote.member.group_id)
        rows.append((
            order.get(group_id, 0), group_id, vote.member.name, vote.member_id,
            {
                "member": vote.member.name,
                "group": names.get(group_id, ""),
                "keys": list(vote.answer.get("keys", [])),
            },
        ))
    return [r[-1] for r in sorted(rows, key=lambda r: r[:4])]


def _texts(ballot: Ballot, kind: str, names, order) -> list[dict]:
    """Free texts without names: secret ones as shuffled at close, named
    ones sorted by text so the order reveals nobody; grouped by group."""
    if kind != Question.Kind.OPEN_TEXT:
        return []
    if ballot.secret:
        rows = [(t.group_id, t.text) for t in sorted(ballot.texts.all(), key=lambda t: t.pk)]
    else:
        seat_groups = {s.member_id: s.group_id for s in ballot.seats.all()}
        rows = sorted(
            (
                (seat_groups.get(v.member_id), v.answer.get("text"))
                for v in ballot.named_votes.all() if v.answer.get("text")
            ),
            key=lambda r: r[1],
        )
    rows.sort(key=lambda r: order.get(r[0], 0))
    return [{"group": names.get(gid, ""), "text": text} for gid, text in rows]


def _attendance(meeting: QuestionSet, labels, names, order) -> dict:
    invites = sorted(
        (i for i in meeting.invites.select_related("member__group") if i.entered_at),
        key=lambda i: (
            order.get(i.member.group_id, 0), i.member.group_id, i.member.name, i.pk,
        ),
    )
    present, observers = [], []
    for invite in invites:
        member = invite.member
        if member.group.is_observer:
            observers.append(member.name)
            continue
        left = invite.removed_at is not None
        present.append({
            "name": member.name,
            "group": names.get(member.group_id, ""),
            "left": left,
            "left_after": labels.get(invite.removed_after_id) if left else None,
        })
    substitutions = sorted(
        MeetingSubstitution.objects.filter(meeting=meeting).select_related("absent", "deputy"),
        key=lambda s: (order.get(s.absent.group_id, 0), s.absent.group_id, s.absent.name, s.pk),
    )
    return {
        "present": present,
        "substitutions": [
            {
                "deputy": s.deputy.name,
                "absent": s.absent.name,
                "group": names.get(s.absent.group_id, ""),
                "from_label": labels.get(s.from_question_id),
            }
            for s in substitutions
        ],
        "observers": observers,
    }


def _ballots_by_question(meeting: QuestionSet) -> dict[int, list[tuple[Ballot, MotionVersion]]]:
    """Question pk → [(ballot, version voted for that question)] by round;
    a bundle ballot counts for its lead and each bundled item."""
    rows = (
        Ballot.objects.filter(question__question_set_id=meeting.pk)
        .select_related("version")
        .prefetch_related(
            Prefetch("items", queryset=BallotItem.objects.select_related("version")),
            Prefetch("named_votes", queryset=NamedVote.objects.select_related("member")),
            Prefetch("seats", queryset=BallotSeat.objects.select_related("member")),
            "texts", "seal_links",
        )
        .order_by("round", "pk")
    )
    out: dict[int, list] = {}
    for ballot in rows:
        out.setdefault(ballot.question_id, []).append((ballot, ballot.version))
        for item in ballot.items.all():
            out.setdefault(item.question_id, []).append((ballot, item.version))
    for entries in out.values():
        entries.sort(key=lambda e: (e[0].round, e[0].pk))
    return out


def _item(question, label, entries, labels, positions, names, order) -> dict:
    closed = [e for e in entries if e[0].status == Ballot.Status.CLOSED]
    ballot, voted_version = closed[-1] if closed else (None, None)
    all_versions = list(question.motion_versions.all())  # ordered by number
    version = voted_version or (all_versions[-1] if all_versions else None)
    first = all_versions[0] if all_versions else None
    item = {
        "label": label,
        "kind": question.kind,
        "named": question.named_vote,  # the voted ballot's, below
        "text": _version_text(version, question),
        "version": version.number if version else None,
        "version_changed": bool(
            version and first and version.pk != first.pk and not _same_wording(version, first)
        ),
        "status": "voted" if ballot else "not_voted",
        "bundle_with": [],
        "rounds_discarded": [
            {"round": b.round, "reason": b.discard_reason, "comment": b.discard_comment}
            for b, _ in entries if b.status == Ballot.Status.DISCARDED
        ],
        "result": None,
        "options": _options(question.kind, version),
        "finding": None,
        "voters": [],
        "named_votes": [],
        "texts": [],
        "opened_at": None,
        "closed_at": None,
        "reference": None,
        "fingerprint": None,
        "finding_fingerprint": None,
    }
    if ballot is None:
        return item
    partners = [ballot.question_id, *(i.question_id for i in ballot.items.all())]
    result_link = _latest_link(ballot, SealLink.Kind.RESULT)
    finding_link = _latest_link(ballot, SealLink.Kind.FINDING)
    item.update(
        bundle_with=[
            labels.get(qid, "")
            for qid in sorted(
                (q for q in partners if q != question.pk), key=lambda q: positions.get(q, 0),
            )
        ],
        result=_result(ballot, names),
        finding=ballot.finding,
        named=not ballot.secret,
        voters=_voters(ballot, names, order),
        named_votes=_named_votes(ballot, names, order),
        texts=_texts(ballot, question.kind, names, order),
        opened_at=_iso(ballot.opened_at),
        closed_at=_iso(ballot.closed_at),
        reference=result_link.reference if result_link else None,
        fingerprint=result_link.hash if result_link else None,
        finding_fingerprint=finding_link.hash if finding_link else None,
    )
    return item


def build(meeting: QuestionSet) -> dict:
    """The protocol of an ended meeting; ValidationError(code="not_ended")
    otherwise."""
    if meeting.meeting_state != QuestionSet.MeetingState.ENDED:
        raise ValidationError("The meeting has not ended.", code="not_ended")
    if MeetingControl.objects.filter(meeting_id=meeting.pk, trial=True).exists():
        raise ValidationError("A test run has no protocol.", code="not_ended")
    groups = list(CommitteeGroup.objects.filter(room_id=meeting.room_id))
    names = {g.pk: group_name(g) for g in groups}
    order = {g.pk: g.position for g in groups}
    tops = agenda.tops(meeting)
    labels = _labels(tops)
    questions = {
        q.pk: q
        for q in meeting.questions.prefetch_related(
            Prefetch("motion_versions", queryset=MotionVersion.objects.order_by("number")),
        )
    }
    positions = {
        qid: n for n, qid in enumerate(qid for top in tops for qid in top.question_ids)
    }
    by_question = _ballots_by_question(meeting)
    control = MeetingControl.objects.filter(meeting_id=meeting.pk).first()
    notes = list(meeting.top_notes.all())
    section_notes = {n.section_id: n.text for n in notes if n.section_id}
    question_notes = {n.question_id: n.text for n in notes if n.question_id}
    return {
        "id": meeting.pk,
        "committee": _canonical(translated_map(meeting.room, "title")),
        "title": _canonical(translated_map(meeting, "title")),
        "scheduled_at": _iso(meeting.scheduled_at),
        "started_at": _iso(control.started_at if control else None),
        "ended_at": _iso(control.ended_at if control else None),
        "attendance": _attendance(meeting, labels, names, order),
        "tops": [
            {
                "number": top.number,
                "title": top.title,
                "description": top.description,
                # Note target for editing on the protocol page: the section,
                # or the TOP's only question when it has no section.
                "section": top.section_id,
                "question": (
                    top.question_ids[0] if not top.section_id and top.question_ids else None
                ),
                "note": (
                    section_notes.get(top.section_id, "") if top.section_id
                    else question_notes.get(top.question_ids[0], "") if top.question_ids
                    else ""
                ),
                "items": [
                    _item(
                        questions[qid], labels[qid], by_question.get(qid, []),
                        labels, positions, names, order,
                    )
                    for qid in top.question_ids
                ],
            }
            for top in tops
        ],
    }
