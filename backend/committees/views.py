# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
import csv
import io
from typing import ClassVar

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import translation
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.csv_safe import csv_safe
from common.i18n_fields import resolve_translated_text, translated_map
from rooms.models import Question, QuestionSet

from . import services
from .models import CommitteeGroup, CommitteeMember, GroupTemplate, MeetingInvite
from .serializers import (
    CommitteeGroupSerializer,
    CommitteeMemberSerializer,
    GroupTemplateSerializer,
    MeetingInviteSerializer,
    MeetingMemberSerializer,
    MeetingSerializer,
    MeetingSubstitutionSerializer,
    invite_url,
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


def _detail(exc: DjangoValidationError) -> ValidationError:
    return ValidationError({"detail": exc.messages[0]})


_CSV_LABELS = {
    "de": {
        "header": ["Name", "E-Mail", "Gruppe", "Rolle", "Link"],
        "voting": "Stimmberechtigt", "deputy": "Stellvertretung", "observer": "Beobachtend",
    },
    "en": {
        "header": ["Name", "E-Mail", "Group", "Role", "Link"],
        "voting": "Voting", "deputy": "Deputy", "observer": "Observer",
    },
}


class MeetingViewSet(viewsets.GenericViewSet):
    """A meeting set's lifecycle, personal links and substitutions — only for
    the managers of its committee room (everything else 404)."""

    permission_classes: ClassVar = [IsAuthenticated]
    serializer_class = MeetingSerializer

    def get_queryset(self):
        return QuestionSet.objects.filter(
            type=QuestionSet.SetType.MEETING,
            room__in=managed_committee_rooms(self.request.user),
        )

    def _respond(self, meeting, status_code=status.HTTP_200_OK):
        meeting.refresh_from_db()
        return Response(self.get_serializer(meeting).data, status=status_code)

    def _member(self, meeting, value, field):
        try:
            return meeting.room.committee_members.select_related("group").get(pk=int(value))
        except (TypeError, ValueError, CommitteeMember.DoesNotExist):
            raise ValidationError({field: "Invalid member."}) from None

    def _question(self, meeting, value, field):
        if value in (None, ""):
            return None
        try:
            return meeting.questions.get(pk=int(value))
        except (TypeError, ValueError, Question.DoesNotExist):
            raise ValidationError({field: "Invalid item."}) from None

    def _invite(self, meeting, invite_id):
        return get_object_or_404(
            MeetingInvite.objects.select_related("member", "meeting"),
            meeting=meeting, pk=invite_id,
        )

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)

    def start(self, request, pk=None):
        meeting = self.get_object()
        try:
            services.start_meeting(meeting)
        except DjangoValidationError as exc:
            raise _detail(exc) from exc
        return self._respond(meeting)

    def end(self, request, pk=None):
        meeting = self.get_object()
        try:
            services.end_meeting(meeting)
        except DjangoValidationError as exc:
            raise _detail(exc) from exc
        return self._respond(meeting)

    def invites(self, request, pk=None):
        meeting = self.get_object()
        services.ensure_invites(meeting)
        return self._respond(meeting)

    def invites_csv(self, request, pk=None):
        meeting = self.get_object()
        lang = (translation.get_language() or "en").split("-")[0]
        labels = _CSV_LABELS.get(lang, _CSV_LABELS["en"])
        invites = meeting.invites.select_related("member__group").order_by(
            "member__group__position", "member__group_id", "member__name", "id",
        )
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(labels["header"])
        for invite in invites:
            member = invite.member
            role = "observer" if member.group.is_observer else member.role
            row = [
                member.name, member.email,
                resolve_translated_text(translated_map(member.group, "name")),
                labels[role], invite_url(request, invite),
            ]
            writer.writerow([csv_safe(cell) for cell in row])
        response = HttpResponse(
            "\ufeff" + buffer.getvalue(), content_type="text/csv; charset=utf-8",
        )
        response["Content-Disposition"] = f'attachment; filename="links-{meeting.pk}.csv"'
        return response

    def suggest(self, request, pk=None):
        meeting = self.get_object()
        absent = self._member(meeting, request.query_params.get("absent"), "absent")
        deputy = services.suggest_deputy(meeting, absent)
        return Response({"deputy": MeetingMemberSerializer(deputy).data if deputy else None})

    def substitutions(self, request, pk=None):
        meeting = self.get_object()
        absent = self._member(meeting, request.data.get("absent"), "absent")
        deputy = self._member(meeting, request.data.get("deputy"), "deputy")
        from_question = self._question(meeting, request.data.get("from_question"), "from_question")
        try:
            with transaction.atomic():
                substitution = services.add_substitution(
                    meeting, absent, deputy, from_question=from_question,
                )
        except DjangoValidationError as exc:
            raise _detail(exc) from exc
        except IntegrityError as exc:
            raise ValidationError(
                {"detail": "This member or deputy is already part of a substitution."},
            ) from exc
        return Response(
            MeetingSubstitutionSerializer(substitution).data, status=status.HTTP_201_CREATED,
        )

    def delete_substitution(self, request, pk=None, sub_id=None):
        meeting = self.get_object()
        substitution = get_object_or_404(meeting.substitutions, pk=sub_id)
        substitution.meeting = meeting
        try:
            services.remove_substitution(substitution)
        except DjangoValidationError as exc:
            raise _detail(exc) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _invite_response(self, invite):
        invite.refresh_from_db()
        return Response(MeetingInviteSerializer(invite, context={"request": self.request}).data)

    def remove_invite(self, request, pk=None, invite_id=None):
        meeting = self.get_object()
        invite = self._invite(meeting, invite_id)
        after = self._question(meeting, request.data.get("after_question"), "after_question")
        try:
            services.remove_invite(invite, after_question=after)
        except DjangoValidationError as exc:
            raise _detail(exc) from exc
        return self._invite_response(invite)

    def readmit_invite(self, request, pk=None, invite_id=None):
        meeting = self.get_object()
        invite = self._invite(meeting, invite_id)
        try:
            services.readmit_invite(invite)
        except DjangoValidationError as exc:
            raise _detail(exc) from exc
        return self._invite_response(invite)
