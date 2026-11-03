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
        "rooms.Question", null=True, blank=True, on_delete=models.SET_NULL,
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
        "rooms.Question", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["meeting", "member"], name="unique_invite_per_member",
            ),
        ]
