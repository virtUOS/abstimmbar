# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Live side (ADR-0002): Run, Vote, ParticipantToken.

Anonymity by design (concept §9): votes reference only an opaque
participant token — no user account, no IP, no fingerprint. The token's
sole purpose is preventing double votes within a run.
"""
import secrets
from typing import ClassVar

from django.db import models

from common.models import TimeStampedModel


def generate_token_key():
    return secrets.token_hex(16)


class ParticipantToken(models.Model):
    """Opaque per-room participant identity, issued on join.

    Stored client-side (localStorage); reused across runs so the
    "same code every session" bookmark flow works without re-joining.
    """

    room = models.ForeignKey("rooms.Room", on_delete=models.CASCADE, related_name="tokens")
    key = models.CharField(max_length=32, unique=True, default=generate_token_key)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"token …{self.key[-6:]} ({self.room.code})"


class Run(TimeStampedModel):
    """One live session of a question set (concept §3.1, „Durchführung").

    Teacher-paced phase machine, per Cliqr flow (1)–(4):
    lobby → preview (question on beamer only) → open (answerable) →
    closed → results → … → finished.
    """

    class Phase(models.TextChoices):
        LOBBY = "lobby", "Lobby"
        PREVIEW = "preview", "Question shown, not yet open"
        OPEN = "open", "Accepting votes"
        CLOSED = "closed", "Voting closed"
        RESULTS = "results", "Results on the beamer"
        FINISHED = "finished", "Finished"

    class Mode(models.TextChoices):
        LIVE = "live", "Teacher-paced (live)"
        # Self-paced quiz (concept §6.3): all questions open at once,
        # participants answer at their own pace with instant feedback.
        # Phases collapse to open → finished; active_question stays null.
        SELF_PACED = "self_paced", "Self-paced quiz"

    question_set = models.ForeignKey(
        "rooms.QuestionSet", on_delete=models.CASCADE, related_name="runs"
    )
    phase = models.CharField(max_length=10, choices=Phase.choices, default=Phase.LOBBY)
    mode = models.CharField(max_length=10, choices=Mode.choices, default=Mode.LIVE)
    active_question = models.ForeignKey(
        "rooms.Question", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # When the active question was opened — basis for the countdown timer
    # (v2) and its server-side enforcement in the vote endpoint.
    opened_at = models.DateTimeField(null=True, blank=True)
    # When this run's *first* question was opened — names the result archive
    # ("Durchführung vom …", #17). Set once, never overwritten.
    first_opened_at = models.DateTimeField(null=True, blank=True)
    # Presenter pressed "reveal correct answers" (v2): server state, so
    # participant devices can highlight in sync with the beamer.
    answers_revealed = models.BooleanField(default=False)
    ended_at = models.DateTimeField(null=True, blank=True)
    # Recording mode (#53): when set, this run is "recorded" — viewers of the
    # recording can vote later via a per-question deep link keyed by this token
    # (dedicated recording path, independent of the room's active run). Empty
    # token = not recorded. Non-guessable, like QuestionSet.share_token.
    recording_token = models.CharField(
        max_length=32, unique=True, null=True, blank=True, default=None
    )

    def enable_recording(self):
        """Mint a recording token (idempotent) so the run accepts async votes
        from recording viewers via /r/<token>/."""
        if not self.recording_token:
            self.recording_token = secrets.token_urlsafe(16)[:32]
            self.save(update_fields=["recording_token"])
        return self.recording_token

    def disable_recording(self):
        """Clear the recording token (idempotent) — a run started without
        recording must not stay in recording mode after being resumed."""
        if self.recording_token:
            self.recording_token = None
            self.save(update_fields=["recording_token", "updated_at"])

    class Meta:
        ordering: ClassVar = ["-created_at"]
        constraints: ClassVar = [
            # At most one unfinished run per question set — the presenter
            # either continues it or resets (concept §6.1 dialog).
            models.UniqueConstraint(
                fields=["question_set"],
                condition=~models.Q(phase="finished"),
                name="one_active_run_per_set",
            )
        ]

    @property
    def is_active(self):
        return self.phase != self.Phase.FINISHED

    def __str__(self):
        return f"Run #{self.pk} of {self.question_set} ({self.phase})"


class Vote(models.Model):
    """One participant's answer to one question within a run.

    Choice kinds store selected options (M2M); word clouds store raw text
    plus a casefolded key so spelling variants merge in the aggregation
    (review decision, July 2026).
    """

    class Source(models.TextChoices):
        ONSITE = "onsite", "On-site (live)"
        RECORDING = "recording", "Recording viewer (async, #53)"

    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="votes")
    question = models.ForeignKey(
        "rooms.Question", on_delete=models.CASCADE, related_name="votes"
    )
    token = models.ForeignKey(ParticipantToken, on_delete=models.CASCADE, related_name="votes")
    # Recording mode (#53): distinguishes on-site (live) from recording-viewer
    # (async) votes so results can be split; both attribute to the same run.
    source = models.CharField(
        max_length=10, choices=Source.choices, default=Source.ONSITE
    )
    options = models.ManyToManyField("rooms.AnswerOption", blank=True, related_name="votes")
    text = models.CharField(max_length=500, blank=True)
    text_key = models.CharField(max_length=60, blank=True, db_index=True)
    # v2 KI: live free-text evaluation, filled by a background worker after
    # the vote is stored. Blank verdict = still pending / not evaluated.
    ai_verdict = models.CharField(max_length=40, blank=True, default="")
    ai_note = models.CharField(max_length=200, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    # The double-vote guard (one submission per participant/question/run) is
    # enforced in the vote view, not by a DB constraint: word clouds with
    # ``allow_multiple`` deliberately store several votes per token (#14).

    def save(self, *args, **kwargs):
        if self.question.kind == "word_cloud":
            # Word clouds: single short term, whitespace collapsed.
            self.text = " ".join(self.text.split())[:60]
        else:
            self.text = self.text.strip()[:500]
        self.text_key = self.text.casefold()[:60]
        super().save(*args, **kwargs)


class PriorityScore(models.Model):
    """One participant's points for one option of a ``priorities`` question
    (#58). A submission stores a row for every option of the question,
    including 0, so per-option min/max are correct across all participants."""

    vote = models.ForeignKey(
        "Vote", on_delete=models.CASCADE, related_name="priority_scores"
    )
    option = models.ForeignKey(
        "rooms.AnswerOption",
        on_delete=models.CASCADE,
        related_name="priority_scores",
    )
    points = models.PositiveSmallIntegerField()

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["vote", "option"], name="one_score_per_vote_option"
            )
        ]

    def __str__(self):
        return f"{self.points} pts (vote {self.vote_id}, option {self.option_id})"


class OrderingResponse(models.Model):
    """One participant's assigned rank (0-based) for one option of an
    ``ordering`` question (#72). A submission stores a row per option; the
    correct rank is the option's own ``position`` (the editor's drag order)."""

    vote = models.ForeignKey(
        "Vote", on_delete=models.CASCADE, related_name="ordering_responses"
    )
    option = models.ForeignKey(
        "rooms.AnswerOption",
        on_delete=models.CASCADE,
        related_name="ordering_responses",
    )
    position = models.PositiveSmallIntegerField()

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["vote", "option"], name="one_ordering_per_vote_option"
            )
        ]

    def __str__(self):
        return f"pos {self.position} (vote {self.vote_id}, option {self.option_id})"


class MatrixResponse(models.Model):
    """One checked cell of a ``matrix`` question (#4): the participant ticked
    ``column`` for ``row``. A submission stores one row per checked cell only
    (unlike ``PriorityScore``, unchecked cells are simply absent) — several
    columns may be checked per row, independently per row."""

    vote = models.ForeignKey(
        "Vote", on_delete=models.CASCADE, related_name="matrix_responses"
    )
    row = models.ForeignKey(
        "rooms.AnswerOption", on_delete=models.CASCADE, related_name="matrix_responses"
    )
    column = models.ForeignKey(
        "rooms.MatrixColumn", on_delete=models.CASCADE, related_name="matrix_responses"
    )

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["vote", "row", "column"], name="one_cell_per_vote"
            )
        ]

    def __str__(self):
        return f"row {self.row_id} × col {self.column_id} (vote {self.vote_id})"
