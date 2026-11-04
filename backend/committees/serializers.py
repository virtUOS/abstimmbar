# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
from typing import ClassVar

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from common.i18n_fields import TranslatedMapMixin, translated_map
from rooms.models import QuestionSet

from .models import (
    CommitteeGroup,
    CommitteeMember,
    GroupTemplate,
    MeetingControl,
    MeetingInvite,
    MeetingSubstitution,
)
from .services import invite_state, managed_committee_rooms


class GroupTemplateSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = GroupTemplate
        fields: ClassVar = ["id", "name", "groups"]

    def get_name(self, obj):
        return translated_map(obj, "name")


class _ManagedRoomMixin:
    """`room` may only name a room the user manages and is fixed once set."""

    def _check_room(self, attrs):
        room = attrs.get("room")
        if self.instance is not None:
            if room is not None and room.pk != self.instance.room_id:
                raise serializers.ValidationError({"room": "The room cannot be changed."})
            return
        user = self.context["request"].user
        if room is None or not managed_committee_rooms(user).filter(pk=room.pk).exists():
            raise serializers.ValidationError({"room": "Invalid room."})


class CommitteeGroupSerializer(
    _ManagedRoomMixin, TranslatedMapMixin, serializers.ModelSerializer,
):
    translated_fields = ("name",)

    member_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = CommitteeGroup
        fields: ClassVar = ["id", "room", "name", "position", "is_observer", "member_count"]
        read_only_fields: ClassVar = ["is_observer"]

    def validate(self, attrs):
        self._check_room(attrs)
        return attrs


class CommitteeMemberSerializer(_ManagedRoomMixin, serializers.ModelSerializer):
    class Meta:
        model = CommitteeMember
        fields: ClassVar = ["id", "room", "group", "name", "email", "role", "deputy_rank", "language"]

    def validate(self, attrs):
        self._check_room(attrs)
        instance = self.instance or CommitteeMember()
        for key, value in attrs.items():
            setattr(instance, key, value)
        try:
            instance.full_clean()
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.message_dict) from exc
        return attrs


class MeetingMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = CommitteeMember
        fields: ClassVar = ["id", "name", "email", "group", "role"]


def invite_url(request, invite: MeetingInvite) -> str:
    return request.build_absolute_uri(f"/g/{invite.token}/")


class MeetingInviteSerializer(serializers.ModelSerializer):
    member = MeetingMemberSerializer(read_only=True)
    url = serializers.SerializerMethodField()
    state = serializers.SerializerMethodField()

    class Meta:
        model = MeetingInvite
        fields: ClassVar = ["id", "member", "url", "removed_at", "removed_after", "state"]

    def get_url(self, obj):
        return invite_url(self.context["request"], obj)

    def get_state(self, obj):
        return invite_state(obj)


class MeetingSubstitutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeetingSubstitution
        fields: ClassVar = ["id", "absent", "deputy", "from_question"]


class MeetingSerializer(serializers.ModelSerializer):
    invites = serializers.SerializerMethodField()
    substitutions = serializers.SerializerMethodField()
    started_at = serializers.SerializerMethodField()
    ended_at = serializers.SerializerMethodField()
    chair_is_member = serializers.SerializerMethodField()
    trial = serializers.SerializerMethodField()

    class Meta:
        model = QuestionSet
        fields: ClassVar = [
            "id", "meeting_state", "scheduled_at", "chair_votes", "invites", "substitutions",
            "started_at", "ended_at", "chair_is_member", "trial",
        ]

    def get_trial(self, obj):
        control = self._control(obj)
        return bool(control and control.trial)

    def _control(self, obj):
        if not hasattr(obj, "_control_cache"):
            obj._control_cache = MeetingControl.objects.filter(meeting=obj).first()
        return obj._control_cache

    def get_started_at(self, obj):
        control = self._control(obj)
        return control and serializers.DateTimeField().to_representation(control.started_at)

    def get_ended_at(self, obj):
        control = self._control(obj)
        return control and serializers.DateTimeField().to_representation(control.ended_at)

    def get_chair_is_member(self, obj):
        """Whether the requesting user (the chair) is a voting member of a
        voting group of the room — the precondition for "chair votes too"."""
        email = getattr(self.context["request"].user, "email", "")
        return bool(email) and CommitteeMember.objects.filter(
            room_id=obj.room_id, email__iexact=email,
            role=CommitteeMember.Role.VOTING, group__is_observer=False,
        ).exists()

    def get_invites(self, obj):
        invites = list(obj.invites.select_related("member").order_by(
            "member__group__position", "member__group_id", "member__name", "id",
        ))
        for invite in invites:
            invite.meeting = obj
        return MeetingInviteSerializer(invites, many=True, context=self.context).data

    def get_substitutions(self, obj):
        return MeetingSubstitutionSerializer(
            obj.substitutions.order_by("id"), many=True,
        ).data
