# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Seal chain (§ 9): every result, finding and discard of a committee room
becomes one link whose hash covers its content and the previous link.

``content()`` is built from persisted rows only, so it can be recomputed
later to verify a link. Secrecy (§ 8): no vote timestamps, and for secret
ballots only *who* voted, never the choice.
"""
import hashlib
import json

from django.db import transaction
from django.utils import timezone

from rooms.models import Question, Room

from . import agenda, eligibility
from .models import Ballot, BallotText, CommitteeGroup, MeetingControl, SealLink

HASH_VERSION = 1


def canonical(obj) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()


def digest(obj) -> str:
    return hashlib.sha256(canonical(obj)).hexdigest()


def _meeting_date(ballot: Ballot) -> str:
    meeting = ballot.question.question_set
    when = meeting.scheduled_at
    if when is None:
        when = (
            MeetingControl.objects.filter(meeting_id=meeting.pk)
            .values_list("started_at", flat=True).first()
        )
    if when is None:
        when = ballot.opened_at
    return timezone.localtime(when, timezone.get_default_timezone()).strftime("%Y%m%d")


def reference(ballot: Ballot) -> str:
    """``G{meeting}-{YYYYMMDD}-TOP{label}`` plus ``-W{round}`` from round 2;
    an en bloc ballot carries its lead item's label."""
    meeting = ballot.question.question_set
    label = agenda.labels(meeting).get(ballot.question_id, "")
    ref = f"G{meeting.pk}-{_meeting_date(ballot)}-TOP{label}"
    if ballot.round >= 2:
        ref += f"-W{ballot.round}"
    return ref


def _version(version) -> dict:
    return {
        "number": version.number,
        "text_de": version.text_de,
        "text_en": version.text_en,
        "options": version.options,
    }


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _result_content(ballot: Ballot, ref: str) -> dict:
    from .payloads import group_name  # payloads imports ballots, which imports us

    meeting = ballot.question.question_set
    groups = {g.pk: g for g in CommitteeGroup.objects.filter(room_id=meeting.room_id)}
    names = {pk: group_name(g) for pk, g in groups.items()}
    result = ballot.result or {"groups": [], "total": {}, "voted": 0, "tally_sum": 0}

    labels = agenda.labels(meeting)
    numbers = eligibility.numbers(meeting)
    bundled = sorted(
        ballot.items.select_related("version"), key=lambda i: numbers.get(i.question_id, 0),
    )
    seats = list(ballot.seats.select_related("member"))
    seat_groups = {s.member_id: s.group_id for s in seats}

    named = []
    if not ballot.secret:
        named = sorted(
            (
                {"member": v.member.name, "keys": list(v.answer.get("keys", []))}
                for v in ballot.named_votes.select_related("member")
            ),
            key=lambda n: (n["member"], n["keys"]),
        )

    texts_by_group: dict[int, list[str]] = {}
    if ballot.question.kind == Question.Kind.OPEN_TEXT:
        if ballot.secret:
            rows = BallotText.objects.filter(ballot=ballot).values_list("group_id", "text")
        else:
            rows = (
                (seat_groups.get(v.member_id), v.answer.get("text"))
                for v in ballot.named_votes.all()
            )
        for group_id, text in rows:
            if text:
                texts_by_group.setdefault(group_id, []).append(text)
    texts = [
        {"group": names.get(g["group"], ""), "texts": sorted(texts_by_group[g["group"]])}
        for g in result["groups"]
        if g["group"] in texts_by_group
    ]

    return {
        "reference": ref,
        "secret": ballot.secret,
        "round": ballot.round,
        "version": _version(ballot.version),
        "items": [
            {"reference_label": labels.get(i.question_id, ""), "version": _version(i.version)}
            for i in bundled
        ],
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
        "voters": sorted(
            f"{s.member.name} ({names.get(s.group_id, '')})" for s in seats if s.voted
        ),
        "named": named,
        "texts": texts,
        "opened_at": _iso(ballot.opened_at),
        "closed_at": _iso(ballot.closed_at),
    }


def content(ballot: Ballot, kind: str, ref: str | None = None) -> dict:
    """What a link of `kind` seals. `ref` defaults to the current reference;
    a verifier passes the stored one."""
    if ref is None:
        ref = reference(ballot)
    if kind == SealLink.Kind.RESULT:
        return _result_content(ballot, ref)
    if kind == SealLink.Kind.FINDING:
        return {"reference": ref, "finding": ballot.finding}
    if kind == SealLink.Kind.DISCARD:
        return {
            "reference": ref,
            "reason": ballot.discard_reason,
            "comment": ballot.discard_comment,
        }
    raise ValueError(f"Unknown seal kind {kind!r}")


def link_hash(seq: int, kind: str, ref: str, content_hash: str, previous: str) -> str:
    return digest({
        "v": HASH_VERSION, "seq": seq, "kind": kind, "reference": ref,
        "content_hash": content_hash, "previous": previous,
    })


def _skip(ballot: Ballot) -> bool:
    """Links that must not be sealed (trial meetings, Task 6). None yet."""
    return False


@transaction.atomic
def append(ballot: Ballot, kind: str) -> SealLink | None:
    """Add a link for `ballot` to its room's chain (inside the caller's
    transaction; the room row lock serializes the sequence)."""
    if _skip(ballot):
        return None
    meeting = ballot.question.question_set
    room = Room.objects.select_for_update().get(pk=meeting.room_id)
    last = SealLink.objects.filter(room=room).order_by("-seq").first()
    seq = last.seq + 1 if last else 1
    previous = last.hash if last else ""
    ref = reference(ballot)
    content_hash = digest(content(ballot, kind, ref))
    return SealLink.objects.create(
        room=room, seq=seq, kind=kind, reference=ref, ballot=ballot,
        meeting_id=meeting.pk, content_hash=content_hash, previous=previous,
        hash=link_hash(seq, kind, ref, content_hash, previous),
    )
