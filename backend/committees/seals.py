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

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from rooms.models import Question, Room

from . import agenda
from .models import Ballot, BallotText, MeetingControl, SealLink

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
    """Ids only (groups, members, items): renaming a group or member, or
    relabelling the agenda after the close, must not change the hash."""
    result = ballot.result or {"groups": [], "total": {}, "voted": 0, "tally_sum": 0}
    seats = list(ballot.seats.all())
    seat_groups = {s.member_id: s.group_id for s in seats}
    votes = [] if ballot.secret else list(ballot.named_votes.all())

    texts_by_group: dict[int, list[str]] = {}
    if ballot.question.kind == Question.Kind.OPEN_TEXT:
        if ballot.secret:
            rows = BallotText.objects.filter(ballot=ballot).values_list("group_id", "text")
        else:
            rows = ((seat_groups.get(v.member_id), v.answer.get("text")) for v in votes)
        for group_id, text in rows:
            if text:
                texts_by_group.setdefault(group_id, []).append(text)

    return {
        "reference": ref,
        "secret": ballot.secret,
        "round": ballot.round,
        "version": _version(ballot.version),
        "items": [
            {"question_id": i.question_id, "version": _version(i.version)}
            for i in sorted(ballot.items.select_related("version"), key=lambda i: i.question_id)
        ],
        "groups": sorted(
            (
                {
                    "group_id": g["group"],
                    "eligible": g["eligible"],
                    "voted": g["voted"],
                    "counts": g["counts"],
                }
                for g in result["groups"]
            ),
            key=lambda g: g["group_id"],
        ),
        "total": result["total"],
        "voted": result["voted"],
        "tally_sum": result["tally_sum"],
        "voters": sorted(s.member_id for s in seats if s.voted),
        "named": sorted(
            (
                {"member_id": v.member_id, "keys": list(v.answer.get("keys", []))}
                for v in votes
            ),
            key=lambda n: n["member_id"],
        ),
        "texts": [
            {"group_id": gid, "texts": sorted(texts)}
            for gid, texts in sorted(texts_by_group.items(), key=lambda kv: kv[0] or 0)
        ],
        "opened_at": _iso(ballot.opened_at),
        "closed_at": _iso(ballot.closed_at),
    }


def content(ballot: Ballot, kind: str, ref: str) -> dict:
    """What a link of `kind` seals. `ref` is the link's stored reference —
    never recomputed for verification (the agenda may change later)."""
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
    """Links that must not be sealed: a test run leaves no trace."""
    return MeetingControl.objects.filter(
        meeting_id=ballot.question.question_set_id, trial=True,
    ).exists()


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


MIN_FINGERPRINT = 16


def _chain_intact(room: Room) -> bool:
    previous = ""
    for expected_seq, link in enumerate(SealLink.objects.filter(room=room).order_by("seq"), 1):
        if (
            link.seq != expected_seq
            or link.previous != previous
            or link.hash != link_hash(
                link.seq, link.kind, link.reference, link.content_hash, link.previous,
            )
        ):
            return False
        previous = link.hash
    return True


def _status(link: SealLink, discards: set[tuple[int, int]]) -> str:
    """valid / altered / discarded / deleted for one link. `discards` holds
    (ballot_id, seq) of the room's discard links."""
    if link.deleted_at is not None:
        return "deleted"
    ballot = link.ballot
    if ballot is None:
        return "altered"
    if (
        link.kind != SealLink.Kind.DISCARD
        and ballot.status == Ballot.Status.DISCARDED
        and any(b == ballot.pk and seq > link.seq for b, seq in discards)
    ):
        # A reset wipes the rows the result was built from.
        return "discarded"
    recomputed = digest(content(ballot, link.kind, link.reference))
    return "valid" if recomputed == link.content_hash else "altered"


def normalize_fingerprint(raw: str) -> str:
    """Hex digits only, lowercase; ValidationError(code="invalid") if too
    short or not hex."""
    value = "".join(raw.split()).lower()
    if len(value) < MIN_FINGERPRINT or any(c not in "0123456789abcdef" for c in value):
        raise ValidationError(
            f"The fingerprint needs at least {MIN_FINGERPRINT} hex characters.",
            code="invalid",
        )
    return value


def verify(room: Room, reference: str, fingerprint: str = "") -> dict:
    fp = normalize_fingerprint(fingerprint) if fingerprint.strip() else ""
    links = list(
        SealLink.objects.filter(room=room, reference=reference)
        .select_related("ballot__question__question_set", "ballot__version")
        .order_by("seq")
    )
    discards = set(
        SealLink.objects.filter(room=room, kind=SealLink.Kind.DISCARD, ballot__isnull=False)
        .values_list("ballot_id", "seq")
    )
    return {
        "found": bool(links),
        "chain_intact": _chain_intact(room),
        "links": [
            {
                "kind": link.kind,
                "seq": link.seq,
                "created_at": link.created_at,
                "hash": link.hash,
                "status": _status(link, discards),
            }
            for link in links
        ],
        "fingerprint_matches": (
            any(link.hash.startswith(fp) for link in links) if fp else None
        ),
    }
