# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Ballot lifecycle: open, cast, close, reset, restart detection (§ 8).

Secrecy: a secret vote touches the database only through the participation
mark (``BallotSeat.voted``); its content goes to the in-memory tally. Nothing
in this module logs, and error messages never carry vote content.
"""
import logging
import secrets
from typing import Literal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Q, QuerySet
from django.utils import timezone

from rooms.models import Question, QuestionSet

from . import eligibility, seals, tally, versions
from .models import (
    Ballot,
    BallotItem,
    BallotSeat,
    BallotText,
    CommitteeGroup,
    MeetingControl,
    MeetingInvite,
    NamedVote,
)
from .services import invite_state

logger = logging.getLogger(__name__)

secret_tally = tally.secret_tally

MAX_TEXT_LENGTH = 2000
MAX_COMMENT_LENGTH = 1000
RESOLUTION_CHOICES = ("yes", "no", "abstain")
RESTART_COMMENT = "Abgebrochen durch Serverneustart."


def _notify(meeting: QuestionSet, debounce=False) -> None:
    from .live import notify  # live imports this module

    notify(meeting, debounce=debounce)


def _invalid():
    return ValidationError("Invalid answer.", code="invalid")


def _is_id(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def ballot_options(ballot: Ballot) -> list[dict]:
    """The candidates of an election round: the version's options in their
    order, narrowed to ``ballot.candidates`` (a runoff) when set."""
    options = ballot.version.options
    if ballot.candidates is None:
        return list(options)
    chosen = set(ballot.candidates)
    return [o for o in options if o["id"] in chosen]


def election_mode(ballot: Ballot) -> Literal["approval", "single", "multi"]:
    """approval: one candidate (yes/no/abstain); single: one vote among
    several (with "no"); multi: up to ``max_votes`` votes (no "no")."""
    if len(ballot_options(ballot)) == 1:
        return "approval"
    return "multi" if ballot.max_votes >= 2 else "single"


def _parse_election(ballot: Ballot, data: dict) -> list[str]:
    mode = election_mode(ballot)
    if mode == "approval":
        choice = data.get("choice")
        if set(data) != {"choice"} or choice not in RESOLUTION_CHOICES:
            raise _invalid()
        return [choice]
    option_ids = {o["id"] for o in ballot_options(ballot)}
    if mode == "single":
        if data in ({"choice": "no"}, {"choice": "abstain"}):
            return [data["choice"]]
        option = data.get("option")
        if set(data) != {"option"} or not _is_id(option) or option not in option_ids:
            raise _invalid()
        return [f"opt:{option}"]
    # multi: unspent votes count as abstentions, so every paper weighs
    # max_votes and the counts add up to voted * max_votes.
    if data == {"choice": "abstain"}:
        return ["abstain"] * ballot.max_votes
    options = data.get("options")
    if (
        set(data) != {"options"} or not isinstance(options, list)
        or not 1 <= len(options) <= ballot.max_votes
        or not all(_is_id(o) for o in options)
        or (not ballot.cumulate and len(set(options)) != len(options))
        or not set(options) <= option_ids
    ):
        raise _invalid()
    return [f"opt:{o}" for o in options] + ["abstain"] * (ballot.max_votes - len(options))


def parse_answer(
    question: Question, data, ballot: Ballot | None = None,
) -> tuple[list[str], str | None]:
    """Normalize a request ``answer`` to (keys, text); see the table in the
    plan. ``{"choice": "abstain"}`` is accepted for every kind. Elections
    are parsed against their ``ballot`` (mode, candidates, settings)."""
    if not isinstance(data, dict):
        raise _invalid()
    if question.kind == Question.Kind.ELECTION:
        # Before the abstain shortcut: a multi-vote abstention weighs max_votes.
        if ballot is None:
            raise _invalid()
        return _parse_election(ballot, data), None
    if data == {"choice": "abstain"}:
        return ["abstain"], None
    kind = question.kind
    if kind == Question.Kind.RESOLUTION:
        choice = data.get("choice")
        if set(data) != {"choice"} or choice not in RESOLUTION_CHOICES:
            raise _invalid()
        return [choice], None
    if kind in (Question.Kind.SINGLE_CHOICE, Question.Kind.MULTIPLE_CHOICE):
        option_ids = set(question.options.values_list("pk", flat=True))
        if kind == Question.Kind.SINGLE_CHOICE:
            option = data.get("option")
            if set(data) != {"option"} or not _is_id(option) or option not in option_ids:
                raise _invalid()
            return [f"opt:{option}"], None
        options = data.get("options")
        if (
            set(data) != {"options"} or not isinstance(options, list) or not options
            or not all(_is_id(o) for o in options)
            or len(set(options)) != len(options)
            or not set(options) <= option_ids
        ):
            raise _invalid()
        return [f"opt:{o}" for o in options], None
    if kind == Question.Kind.OPEN_TEXT:
        text = data.get("text")
        if set(data) != {"text"} or not isinstance(text, str):
            raise _invalid()
        text = text.strip()
        if not 1 <= len(text) <= MAX_TEXT_LENGTH:
            raise _invalid()
        return ["text"], text
    raise _invalid()


def _meeting_ballots(meeting: QuestionSet):
    return Ballot.objects.filter(question__question_set_id=meeting.pk)


def abort_stale(meeting: QuestionSet) -> None:
    """Discard open secret ballots whose tally was lost in a restart."""
    stale = list(
        _meeting_ballots(meeting).filter(status=Ballot.Status.OPEN, secret=True)
        .exclude(epoch=tally.EPOCH).values_list("pk", flat=True),
    )
    if not stale:
        return
    with transaction.atomic():
        now = timezone.now()
        updated = (
            Ballot.objects.select_for_update()
            .filter(pk__in=stale, status=Ballot.Status.OPEN)
        )
        ids = list(updated.values_list("pk", flat=True))
        Ballot.objects.filter(pk__in=ids).update(
            status=Ballot.Status.DISCARDED,
            discard_reason=Ballot.DiscardReason.RESTART,
            discard_comment=RESTART_COMMENT,
            discarded_at=now,
        )
        BallotSeat.objects.filter(ballot_id__in=ids).delete()
        for discarded in (
            Ballot.objects.filter(pk__in=ids).select_related("question__question_set")
            .order_by("pk")
        ):
            seals.append(discarded, "discard")
        for pk in ids:
            transaction.on_commit(lambda pk=pk: secret_tally.discard(pk))
        if ids:
            _notify(meeting)


def _check_running(meeting: QuestionSet) -> None:
    state = QuestionSet.objects.values_list("meeting_state", flat=True).get(pk=meeting.pk)
    if state != QuestionSet.MeetingState.STARTED:
        raise ValidationError("The meeting is not running.", code="not_started")


def open_ballot_of(meeting: QuestionSet) -> Ballot | None:
    abort_stale(meeting)
    return _meeting_ballots(meeting).filter(status=Ballot.Status.OPEN).first()


def ballots_for(question: Question) -> QuerySet[Ballot]:
    """Ballots led by `question` or bundling it en bloc."""
    return Ballot.objects.filter(Q(question=question) | Q(items__question=question)).distinct()


def _lock_running(meeting: QuestionSet) -> None:
    """Lock the meeting row (serializes opening) and check it is running."""
    state = (
        QuestionSet.objects.select_for_update()
        .values_list("meeting_state", flat=True).get(pk=meeting.pk)
    )
    if state != QuestionSet.MeetingState.STARTED:
        raise ValidationError("The meeting is not running.", code="not_started")


def _check_free(meeting: QuestionSet, questions: list[Question]) -> None:
    if _meeting_ballots(meeting).filter(status=Ballot.Status.OPEN).exists():
        raise ValidationError("Another vote is still open.", code="other_open")
    for question in questions:
        if ballots_for(question).filter(status=Ballot.Status.CLOSED).exists():
            raise ValidationError(
                "This item has been voted on. Reset the vote first.", code="already_voted_on",
            )


def _election_settings(
    lead: Question, version, candidates: list[int] | None, runoff_of: Ballot | None,
) -> tuple[int, bool]:
    """(max_votes, cumulate) frozen on the ballot; validates the round."""
    if lead.kind != Question.Kind.ELECTION:
        return 1, False
    max_votes, cumulate = (1, False) if runoff_of is not None else (
        lead.max_votes, lead.cumulate,
    )
    ids = {o["id"] for o in version.options}
    count = len(ids if candidates is None else ids & set(candidates))
    if count == 0:
        raise ValidationError("The election has no candidates.", code="no_candidates")
    if not cumulate and max_votes > count:
        raise ValidationError(
            "More votes than candidates without cumulating.", code="too_many_votes",
        )
    return max_votes, cumulate


def _start(
    meeting: QuestionSet, lead: Question, others: list[Question], *,
    candidates: list[int] | None = None, runoff_of: Ballot | None = None,
) -> Ballot:
    """Create the ballot on `lead` (plus `others` en bloc) with its seats,
    start a secret tally and put the lead on the beamer. Elections freeze
    their settings (a runoff: one vote, no cumulating) and `candidates`."""
    for question in (lead, *others):
        versions.sync(question)
    version = versions.current(lead)
    max_votes, cumulate = _election_settings(lead, version, candidates, runoff_of)
    last_round = max(
        (ballots_for(q).aggregate(m=Max("round"))["m"] or 0) for q in (lead, *others)
    )
    secret = not lead.named_vote
    ballot = Ballot.objects.create(
        question=lead, version=version, round=last_round + 1,
        secret=secret, epoch=tally.EPOCH if secret else "",
        max_votes=max_votes, cumulate=cumulate,
        candidates=list(candidates) if candidates is not None else None,
        runoff_of=runoff_of,
    )
    BallotItem.objects.bulk_create([
        BallotItem(ballot=ballot, question=q, version=versions.current(q)) for q in others
    ])
    BallotSeat.objects.bulk_create([
        BallotSeat(ballot=ballot, member=m, group_id=m.group_id)
        for m in eligibility.eligible_voters(meeting, lead)
    ])
    if secret:
        secret_tally.start(ballot.pk)
    MeetingControl.objects.update_or_create(
        meeting=meeting,
        defaults={"current_question": lead, "current_section_id": lead.section_id},
    )
    _notify(meeting)
    return ballot


@transaction.atomic
def open_ballot(meeting: QuestionSet, question: Question) -> Ballot:
    abort_stale(meeting)
    if question.question_set_id != meeting.pk:
        raise ValidationError("The item does not belong to this meeting.", code="invalid")
    _lock_running(meeting)
    _check_free(meeting, [question])
    return _start(meeting, question, [])


@transaction.atomic
def open_bundle(meeting: QuestionSet, questions: list[Question]) -> Ballot:
    """One vote en bloc over several resolutions; the first on the agenda
    leads (eligibility, beamer), the result applies to all of them."""
    abort_stale(meeting)
    distinct = list({q.pk: q for q in questions}.values())
    if len(distinct) < 2:
        raise ValidationError("Choose at least two items.", code="invalid")
    for question in distinct:
        if question.question_set_id != meeting.pk:
            raise ValidationError(
                "The item does not belong to this meeting.", code="invalid",
            )
        if question.kind != Question.Kind.RESOLUTION:
            raise ValidationError(
                "Only resolutions can be voted on en bloc.", code="invalid",
            )
    if len({q.named_vote for q in distinct}) > 1:
        raise ValidationError(
            "Secret and roll-call items cannot be voted on together.", code="mixed_named",
        )
    _lock_running(meeting)
    numbers = eligibility.numbers(meeting)
    distinct.sort(key=lambda q: numbers[q.pk])
    _check_free(meeting, distinct)
    return _start(meeting, distinct[0], distinct[1:])


def _locked(ballot_id: int) -> Ballot | None:
    return (
        Ballot.objects.select_for_update(of=("self",)).select_related("question")
        .filter(pk=ballot_id).first()
    )


@transaction.atomic
def cast_vote(invite: MeetingInvite, ballot_id: int, data) -> None:
    """Record one vote. Deliberately without any logging (§ 8)."""
    abort_stale(invite.meeting)
    ballot = _locked(ballot_id)
    if (
        ballot is None or ballot.status != Ballot.Status.OPEN
        or ballot.question.question_set_id != invite.meeting_id
        or (ballot.secret and not secret_tally.has(ballot.pk))
    ):
        raise ValidationError("The vote is closed.", code="closed")
    # Judged at the ballot's item: a member removed "after" it still votes.
    if invite_state(invite, ballot.question) != "active":
        raise ValidationError("The link is not valid.", code="invalid_link")
    group_id = (
        ballot.seats.filter(member_id=invite.member_id)
        .values_list("group_id", flat=True).first()
    )
    if group_id is None:
        raise ValidationError("You are not eligible to vote.", code="not_eligible")
    keys, text = parse_answer(ballot.question, data, ballot)
    marked = ballot.seats.filter(member_id=invite.member_id, voted=False).update(voted=True)
    if marked == 0:
        raise ValidationError("You have already voted.", code="already_voted")
    if ballot.secret:
        # Inside the transaction under the ballot lock: on_commit would run
        # after the lock is released and race with close_ballot. A commit
        # failure after this add is accepted as negligible.
        secret_tally.add(ballot.pk, group_id, keys, text)
    else:
        NamedVote.objects.create(
            ballot=ballot, member_id=invite.member_id, answer={"keys": keys, "text": text},
        )
    if not ballot.seats.filter(voted=False).exists():
        # Everyone has voted: close under the lock already held (the close
        # notifies immediately, so the final state is never debounced away).
        # A savepoint: if the close fails, the vote (and its tally entry)
        # stands and the ballot stays open for a manual close.
        try:
            with transaction.atomic():
                close_ballot(ballot, automatic=True)
            return
        except Exception:  # noqa: BLE001
            # Ballot id only: no exc_info (it could carry answer data, § 8).
            logger.warning("auto-close failed for ballot %s", ballot.pk)
    # Progress only (voted/eligible); a burst of votes becomes one event.
    _notify(invite.meeting, debounce=True)


def _count_keys(ballot: Ballot) -> list[str]:
    """All answer keys, so zero counts stay visible."""
    kind = ballot.question.kind
    if kind == Question.Kind.RESOLUTION:
        return list(RESOLUTION_CHOICES)
    if kind == Question.Kind.OPEN_TEXT:
        return ["text", "abstain"]
    if kind == Question.Kind.ELECTION:
        mode = election_mode(ballot)
        if mode == "approval":
            return list(RESOLUTION_CHOICES)
        keys = [f"opt:{o['id']}" for o in ballot_options(ballot)]
        return [*keys, "no", "abstain"] if mode == "single" else [*keys, "abstain"]
    return [f"opt:{o['id']}" for o in ballot.version.options] + ["abstain"]


def _collect(ballot: Ballot) -> tuple[dict[int, dict], int]:
    """Per-group {"counts", "texts"} and the number of counted ballots."""
    if ballot.secret:
        # A copy: the tally is discarded only after the close commits, so a
        # rollback leaves an open ballot with its tally intact.
        snapshot = secret_tally.snapshot(ballot.pk) or {"groups": {}}
        groups = snapshot["groups"]
        return groups, sum(g["ballots"] for g in groups.values())
    seat_groups = dict(ballot.seats.values_list("member_id", "group_id"))
    groups: dict[int, dict] = {}
    votes = list(ballot.named_votes.all())
    for vote in votes:
        group = groups.setdefault(seat_groups[vote.member_id], {"counts": {}, "texts": []})
        for key in vote.answer["keys"]:
            group["counts"][key] = group["counts"].get(key, 0) + 1
    return groups, len(votes)


@transaction.atomic
def close_ballot(ballot: Ballot, *, automatic: bool = False) -> Ballot:
    abort_stale(ballot.question.question_set)
    locked = _locked(ballot.pk)
    if locked is None or locked.status != Ballot.Status.OPEN:
        raise ValidationError("The vote is not open.", code="not_open")
    ballot = locked
    keys = _count_keys(ballot)
    seats = list(ballot.seats.values_list("group_id", "voted"))
    group_ids = {g for g, _ in seats}
    collected, tally_sum = _collect(ballot)
    total = {"eligible": 0, "voted": 0, "counts": dict.fromkeys(keys, 0)}
    result_groups = []
    for group in CommitteeGroup.objects.filter(pk__in=group_ids).order_by("position", "id"):
        counts = dict.fromkeys(keys, 0)
        for key, n in collected.get(group.pk, {}).get("counts", {}).items():
            counts[key] = counts.get(key, 0) + n
            total["counts"][key] = total["counts"].get(key, 0) + n
        eligible = sum(1 for g, _ in seats if g == group.pk)
        voted = sum(1 for g, v in seats if g == group.pk and v)
        total["eligible"] += eligible
        total["voted"] += voted
        result_groups.append({
            "group": group.pk, "eligible": eligible, "voted": voted, "counts": counts,
        })
    if ballot.secret:
        # Groups in fixed order and texts shuffled by a CSPRNG: neither the
        # row ids nor the order may reveal who (or which group) wrote first.
        rng = secrets.SystemRandom()
        texts = []
        for group in CommitteeGroup.objects.filter(pk__in=list(collected)).order_by("position", "id"):
            shuffled = list(collected[group.pk]["texts"])
            rng.shuffle(shuffled)
            texts.extend(BallotText(ballot=ballot, group_id=group.pk, text=t) for t in shuffled)
        BallotText.objects.bulk_create(texts)
    ballot.result = {
        "groups": result_groups,
        "total": total,
        "voted": total["voted"],
        "tally_sum": tally_sum,
    }
    ballot.status = Ballot.Status.CLOSED
    ballot.closed_at = timezone.now()
    ballot.closed_automatically = automatic
    ballot.save(update_fields=["result", "status", "closed_at", "closed_automatically"])
    seals.append(ballot, "result")
    if ballot.secret:
        pk = ballot.pk
        transaction.on_commit(lambda: secret_tally.discard(pk))
    _notify(ballot.question.question_set)
    return ballot


@transaction.atomic
def reset_ballot(ballot: Ballot, comment: str) -> Ballot:
    comment = (comment or "").strip()
    if len(comment) > MAX_COMMENT_LENGTH:
        raise ValidationError("The comment is too long.", code="invalid")
    _check_running(ballot.question.question_set)
    abort_stale(ballot.question.question_set)
    locked = _locked(ballot.pk)
    if locked is None or locked.status not in (Ballot.Status.OPEN, Ballot.Status.CLOSED):
        raise ValidationError("The vote has already been discarded.", code="not_open")
    ballot = locked
    ballot.seats.all().delete()
    ballot.named_votes.all().delete()
    ballot.texts.all().delete()
    ballot.result = None
    ballot.status = Ballot.Status.DISCARDED
    ballot.discard_reason = Ballot.DiscardReason.RESET
    ballot.discard_comment = comment
    ballot.discarded_at = timezone.now()
    ballot.save(update_fields=[
        "result", "status", "discard_reason", "discard_comment", "discarded_at",
    ])
    seals.append(ballot, "discard")
    pk = ballot.pk
    transaction.on_commit(lambda: secret_tally.discard(pk))
    _notify(ballot.question.question_set)
    return ballot


def release_texts(ballot: Ballot) -> Ballot:
    _check_running(ballot.question.question_set)
    if ballot.status != Ballot.Status.CLOSED:
        raise ValidationError("The vote is not closed.", code="not_closed")
    if ballot.question.kind != Question.Kind.OPEN_TEXT:
        raise ValidationError("Only free-text votes have texts.", code="invalid")
    ballot.texts_released = True
    ballot.save(update_fields=["texts_released"])
    _notify(ballot.question.question_set)
    return ballot


@transaction.atomic
def set_finding(ballot: Ballot, finding: str) -> Ballot:
    """The chair's finding (adopted/rejected, "" = left open) on a closed ballot."""
    if finding not in Ballot.Finding.values and finding != "":
        raise _invalid()
    state = QuestionSet.objects.values_list("meeting_state", flat=True).get(
        pk=ballot.question.question_set_id,
    )
    if state not in (QuestionSet.MeetingState.STARTED, QuestionSet.MeetingState.ENDED):
        raise ValidationError("The meeting has not started.", code="not_started")
    if MeetingControl.objects.filter(
        meeting_id=ballot.question.question_set_id, trial=True,
    ).exists():
        raise ValidationError("Findings are not recorded in a test run.", code="trial")
    locked = _locked(ballot.pk)
    if locked is None or locked.status != Ballot.Status.CLOSED:
        raise ValidationError("The vote is not closed.", code="not_closed")
    ballot = locked
    ballot.finding = finding
    ballot.save(update_fields=["finding"])
    seals.append(ballot, "finding")
    _notify(ballot.question.question_set)
    return ballot


@transaction.atomic
def enter(invite: MeetingInvite) -> None:
    """The member opens their link in a running meeting: mark them entered
    and, during an open vote they hold a seat for, give them a place."""
    if invite_state(invite) != "active":
        return
    if invite.entered_at is None:
        invite.entered_at = timezone.now()
        invite.save(update_fields=["entered_at"])
        _notify(invite.meeting)
    ballot = open_ballot_of(invite.meeting)
    if ballot is None:
        return
    ballot = _locked(ballot.pk)
    if ballot is None or ballot.status != Ballot.Status.OPEN:
        return
    for voter in eligibility.eligible_voters(invite.meeting, ballot.question):
        if voter.pk == invite.member_id:
            _, created = BallotSeat.objects.get_or_create(
                ballot=ballot, member_id=voter.pk, defaults={"group_id": voter.group_id},
            )
            if created:
                _notify(invite.meeting)
            return
