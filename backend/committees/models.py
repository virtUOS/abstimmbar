# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Committee rooms: groups, members, group templates, substitutions, invites."""
import secrets
from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from common.models import TimeStampedModel


def generate_invite_token() -> str:
    return secrets.token_urlsafe(32)


class GroupTemplate(models.Model):
    """Seeded starting point for a committee's groups (names are {de,en})."""

    name = models.CharField(max_length=200)
    # list of {"de": str, "en": str}
    groups = models.JSONField(default=list)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering: ClassVar = ["position"]

    def __str__(self):
        return self.name


class CommitteeGroup(models.Model):
    room = models.ForeignKey(
        "rooms.Room", on_delete=models.CASCADE, related_name="committee_groups",
    )
    name = models.CharField(max_length=200)
    position = models.PositiveIntegerField(default=0)
    is_observer = models.BooleanField(default=False)

    class Meta:
        ordering: ClassVar = ["position", "id"]
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["room"], condition=Q(is_observer=True),
                name="one_observer_group_per_room",
            ),
        ]

    def __str__(self):
        return self.name


class CommitteeMember(TimeStampedModel):
    class Role(models.TextChoices):
        VOTING = "voting", "Voting"
        DEPUTY = "deputy", "Deputy"

    class Language(models.TextChoices):
        DE = "de", "Deutsch"
        EN = "en", "English"

    room = models.ForeignKey(
        "rooms.Room", on_delete=models.CASCADE, related_name="committee_members",
    )
    group = models.ForeignKey(
        CommitteeGroup, on_delete=models.RESTRICT, related_name="members",
    )
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True)
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.VOTING)
    deputy_rank = models.PositiveIntegerField(null=True, blank=True)
    language = models.CharField(max_length=2, choices=Language.choices, default="de")

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["room", "email"], condition=~Q(email=""),
                name="unique_member_email_per_room",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        errors = {}
        if self.group_id and self.room_id and self.group.room_id != self.room_id:
            errors["group"] = "Group belongs to a different room."
        if self.role == self.Role.DEPUTY and self.group_id and self.group.is_observer:
            errors["role"] = "Observers cannot be deputies."
        if self.deputy_rank is not None and self.role != self.Role.DEPUTY:
            errors["deputy_rank"] = "Only deputies have a rank."
        if errors:
            raise ValidationError(errors)


class MeetingSubstitution(models.Model):
    meeting = models.ForeignKey(
        "rooms.QuestionSet", on_delete=models.CASCADE, related_name="substitutions",
    )
    absent = models.ForeignKey(
        CommitteeMember, on_delete=models.CASCADE, related_name="+",
    )
    deputy = models.ForeignKey(
        CommitteeMember, on_delete=models.CASCADE, related_name="+",
    )
    from_question = models.ForeignKey(
        "rooms.Question", null=True, blank=True, on_delete=models.RESTRICT,
        related_name="+",
    )

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["meeting", "absent"], name="unique_substitution_absent",
            ),
            models.UniqueConstraint(
                fields=["meeting", "deputy"], name="unique_substitution_deputy",
            ),
        ]


class MeetingInvite(models.Model):
    meeting = models.ForeignKey(
        "rooms.QuestionSet", on_delete=models.CASCADE, related_name="invites",
    )
    member = models.ForeignKey(
        CommitteeMember, on_delete=models.CASCADE, related_name="invites",
    )
    token = models.CharField(
        max_length=48, unique=True, default=generate_invite_token,
    )
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_after = models.ForeignKey(
        "rooms.Question", null=True, blank=True, on_delete=models.RESTRICT,
        related_name="+",
    )
    # Set when the member enters the running meeting via their link.
    entered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["meeting", "member"], name="unique_invite_per_member",
            ),
        ]


class MotionVersion(models.Model):
    """Frozen wording of an agenda item (text and options) once the meeting
    has started; every later change adds a new version."""

    question = models.ForeignKey(
        "rooms.Question", on_delete=models.CASCADE, related_name="motion_versions",
    )
    number = models.PositiveIntegerField()
    text_de = models.TextField(blank=True)
    text_en = models.TextField(blank=True)
    # [{"id", "text_de", "text_en"}] in option order.
    options = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering: ClassVar = ["number"]
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["question", "number"], name="unique_version_number",
            ),
        ]


class MeetingControl(models.Model):
    """What the beamer of a running meeting shows."""

    meeting = models.OneToOneField(
        "rooms.QuestionSet", on_delete=models.CASCADE, related_name="meeting_control",
    )
    current_question = models.ForeignKey(
        "rooms.Question", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    current_section = models.ForeignKey(
        "rooms.Section", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)


class Ballot(models.Model):
    """One voting round on an agenda item, bound to the version voted on."""

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"
        DISCARDED = "discarded", "Discarded"

    class DiscardReason(models.TextChoices):
        RESET = "reset", "Reset"
        RESTART = "restart", "Restart"

    question = models.ForeignKey(
        "rooms.Question", on_delete=models.CASCADE, related_name="ballots",
    )
    version = models.ForeignKey(
        MotionVersion, on_delete=models.RESTRICT, related_name="ballots",
    )
    round = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    secret = models.BooleanField()
    # Process epoch of a secret ballot (§ 8): a mismatch means the in-memory
    # tally was lost in a restart.
    epoch = models.CharField(max_length=32, blank=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(null=True, blank=True)
    texts_released = models.BooleanField(default=False)
    discard_reason = models.CharField(
        max_length=10, choices=DiscardReason.choices, blank=True,
    )
    discard_comment = models.TextField(blank=True)
    discarded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering: ClassVar = ["round"]
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["question", "round"], name="unique_ballot_round",
            ),
            models.UniqueConstraint(
                fields=["question"], condition=Q(status="open"),
                name="one_open_ballot_per_question",
            ),
        ]


class BallotSeat(models.Model):
    """Participation mark of an eligible voter. Deliberately without any
    timestamp (§ 8): the order of marks must not reveal who cast which vote."""

    ballot = models.ForeignKey(Ballot, on_delete=models.CASCADE, related_name="seats")
    member = models.ForeignKey(
        CommitteeMember, on_delete=models.CASCADE, related_name="+",
    )
    group = models.ForeignKey(
        CommitteeGroup, on_delete=models.RESTRICT, related_name="+",
    )
    voted = models.BooleanField(default=False)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["ballot", "member"], name="unique_ballot_seat",
            ),
        ]


class NamedVote(models.Model):
    """A member's answer in a named (non-secret) ballot."""

    ballot = models.ForeignKey(
        Ballot, on_delete=models.CASCADE, related_name="named_votes",
    )
    member = models.ForeignKey(
        CommitteeMember, on_delete=models.CASCADE, related_name="+",
    )
    answer = models.JSONField()

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["ballot", "member"], name="unique_named_vote",
            ),
        ]


class BallotText(models.Model):
    """Free text of a secret ballot, written shuffled when the ballot closes."""

    ballot = models.ForeignKey(Ballot, on_delete=models.CASCADE, related_name="texts")
    group = models.ForeignKey(
        CommitteeGroup, on_delete=models.RESTRICT, related_name="+",
    )
    text = models.TextField()
