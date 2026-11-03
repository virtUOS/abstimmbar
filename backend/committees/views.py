# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
from typing import ClassVar

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import CommitteeGroup, CommitteeMember, GroupTemplate
from .serializers import (
    CommitteeGroupSerializer,
    CommitteeMemberSerializer,
    GroupTemplateSerializer,
)
from .services import apply_template, managed_committee_rooms, parse_member_list


def _room_filter(request, queryset):
    """?room=<id> narrows to one room; a bad/foreign id simply matches nothing."""
    room = request.query_params.get("room")
    if room is None:
        return queryset
    try:
        return queryset.filter(room_id=int(room))
    except ValueError:
        return queryset.none()


def _managed_room_or_404(request, room_id):
    try:
        room_id = int(room_id)
    except (TypeError, ValueError):
        raise ValidationError({"room": "A room is required."}) from None
    return get_object_or_404(managed_committee_rooms(request.user), pk=room_id)


class GroupTemplateViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = GroupTemplateSerializer
    permission_classes: ClassVar = [IsAuthenticated]
    queryset = GroupTemplate.objects.all()
    pagination_class = None


class CommitteeGroupViewSet(viewsets.ModelViewSet):
    serializer_class = CommitteeGroupSerializer
    permission_classes: ClassVar = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        rooms = managed_committee_rooms(self.request.user)
        queryset = CommitteeGroup.objects.filter(room__in=rooms).annotate(
            member_count=Count("members"),
        )
        if self.action == "list":
            queryset = _room_filter(self.request, queryset)
        return queryset

    def perform_destroy(self, instance):
        if instance.is_observer:
            raise ValidationError({"detail": "The observer group cannot be deleted."})
        if instance.members.exists():
            raise ValidationError(
                {"detail": "Move or remove the group's members first."},
            )
        instance.delete()

    @action(detail=False, methods=["post"], url_path="apply-template")
    def apply_template(self, request):
        room = _managed_room_or_404(request, request.data.get("room"))
        try:
            template_id = int(request.data.get("template"))
        except (TypeError, ValueError):
            raise ValidationError({"template": "A template is required."}) from None
        template = get_object_or_404(GroupTemplate, pk=template_id)
        try:
            groups = apply_template(room, template)
        except DjangoValidationError as exc:
            raise ValidationError({"detail": exc.messages[0]}) from exc
        queryset = self.get_queryset().filter(pk__in=[g.pk for g in groups])
        return Response(
            self.get_serializer(queryset, many=True).data,
            status=status.HTTP_201_CREATED,
        )


class CommitteeMemberViewSet(viewsets.ModelViewSet):
    serializer_class = CommitteeMemberSerializer
    permission_classes: ClassVar = [IsAuthenticated]
    pagination_class = None

    def get_queryset(self):
        rooms = managed_committee_rooms(self.request.user)
        queryset = CommitteeMember.objects.filter(room__in=rooms).order_by("group__position", "id")
        if self.action == "list":
            queryset = _room_filter(self.request, queryset)
        return queryset

    def perform_create(self, serializer):
        try:
            with transaction.atomic():
                serializer.save()
        except IntegrityError as exc:
            raise ValidationError({"detail": "Member could not be saved."}) from exc

    perform_update = perform_create

    @action(detail=False, methods=["post"])
    def bulk(self, request):
        room = _managed_room_or_404(request, request.data.get("room"))
        try:
            group = room.committee_groups.get(pk=int(request.data.get("group")))
        except (TypeError, ValueError, CommitteeGroup.DoesNotExist):
            raise ValidationError({"group": "Invalid group."}) from None
        role = request.data.get("role") or CommitteeMember.Role.VOTING
        if role not in CommitteeMember.Role.values:
            raise ValidationError({"role": "Invalid role."})
        if role == CommitteeMember.Role.DEPUTY and group.is_observer:
            raise ValidationError({"role": "Observers cannot be deputies."})
        text = request.data.get("text")
        if not isinstance(text, str):
            raise ValidationError({"text": "Text is required."})

        entries, skipped = parse_member_list(text)
        existing = {
            e.lower() for e in room.committee_members.exclude(email="")
            .values_list("email", flat=True)
        }
        created = []
        with transaction.atomic():
            for name, email in entries:
                if email.lower() in existing:
                    skipped.append({"line": email, "reason": "exists"})
                    continue
                created.append(CommitteeMember.objects.create(
                    room=room, group=group, name=name[:200], email=email, role=role,
                ))
        return Response(
            {
                "created": CommitteeMemberSerializer(created, many=True).data,
                "skipped": skipped,
            },
            status=status.HTTP_201_CREATED,
        )
