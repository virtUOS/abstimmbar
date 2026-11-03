# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from common.i18n_fields import TranslatedMapMixin, translated_map

from .models import CommitteeGroup, CommitteeMember, GroupTemplate
from .services import managed_committee_rooms


class GroupTemplateSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = GroupTemplate
        fields = ["id", "name", "groups"]

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
        fields = ["id", "room", "name", "position", "is_observer", "member_count"]
        read_only_fields = ["is_observer"]

    def validate(self, attrs):
        self._check_room(attrs)
        return attrs


class CommitteeMemberSerializer(_ManagedRoomMixin, serializers.ModelSerializer):
    class Meta:
        model = CommitteeMember
        fields = ["id", "room", "group", "name", "email", "role", "deputy_rank", "language"]

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
