# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
import csv
import io
import json
from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, ProtectedError, RestrictedError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import translation
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.csv_safe import csv_safe
from common.i18n_fields import resolve_translated_text, translated_map
from rooms.models import Question, QuestionSet

from . import ballots, live, payloads, services
from .models import (
    Ballot,
    BallotSeat,
    CommitteeGroup,
    CommitteeMember,
    GroupTemplate,
    MeetingControl,
    MeetingInvite,
    NamedVote,
)
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
        try:
            with transaction.atomic():
                instance.delete()
        except (RestrictedError, ProtectedError) as exc:
            # Seats and texts of past votes keep their group (RESTRICT).
            raise ValidationError(
                {"detail": "This group took part in votes and cannot be deleted."},
            ) from exc

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

    def perform_update(self, serializer):
        # From the database: the serializer's validate() already set the
        # new values on the instance.
        role, group_id, room_id = CommitteeMember.objects.values_list(
            "role", "group_id", "room_id",
        ).get(pk=serializer.instance.pk)
        data = serializer.validated_data
        changes_seat = (
            ("role" in data and data["role"] != role)
            or ("group" in data and data["group"].pk != group_id)
        )
        if changes_seat and QuestionSet.objects.filter(
            room_id=room_id, type=QuestionSet.SetType.MEETING,
            meeting_state=QuestionSet.MeetingState.STARTED,
        ).exists():
            # Seats, deputies and open ballots follow role and group.
            raise ValidationError(
                {"detail": "Members cannot change role or group during a running meeting."},
            )
        self.perform_create(serializer)

    def perform_destroy(self, instance):
        voted = (
            BallotSeat.objects.filter(member=instance)
            .exclude(ballot__status=Ballot.Status.DISCARDED).exists()
            or NamedVote.objects.filter(member=instance)
            .exclude(ballot__status=Ballot.Status.DISCARDED).exists()
        )
        if voted:
            # Deleting would cascade into their seats and named votes.
            raise ValidationError(
                {"detail": "This member took part in votes and cannot be deleted."},
            )
        instance.delete()

    @action(detail=False, methods=["get"])
    def known(self, request):
        """Autocomplete: people from the requester's own rooms (see
        ``services.known_people``) to add to ``?room=`` — ``?q=`` ≥ 2 chars."""
        room = _managed_room_or_404(request, request.query_params.get("room"))
        return Response(services.known_people(request.user, room, request.query_params.get("q", "")))

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
        for name, email in entries:
            if email.lower() in existing:
                skipped.append({"line": email, "reason": "exists"})
                continue
            # One savepoint per row: a member added concurrently (unique
            # room/email) skips that row instead of failing the request.
            try:
                with transaction.atomic():
                    member = CommitteeMember.objects.create(
                        room=room, group=group, name=name[:200], email=email, role=role,
                    )
            except IntegrityError:
                skipped.append({"line": email, "reason": "exists"})
                continue
            created.append(member)
        return Response(
            {
                "created": CommitteeMemberSerializer(created, many=True).data,
                "skipped": skipped,
            },
            status=status.HTTP_201_CREATED,
        )


def _detail(exc: DjangoValidationError) -> ValidationError:
    return ValidationError({"detail": exc.messages[0]})


def _coded(exc: DjangoValidationError) -> ValidationError:
    """Like ``_detail`` plus the machine-readable ``code`` (ballot errors)."""
    return ValidationError({"detail": exc.messages[0], "code": exc.code})


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
        try:
            services.check_not_ended(meeting)
        except DjangoValidationError as exc:
            raise _detail(exc) from exc
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
            invite.meeting = meeting
            # Only valid links: secretariats must never mail out dead ones.
            if services.invite_state(invite) not in ("waiting", "active"):
                continue
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

    def _ballot(self, meeting, ballot_id):
        return get_object_or_404(
            Ballot.objects.select_related("question"),
            question__question_set=meeting, pk=ballot_id,
        )

    def _console(self, meeting, status_code=status.HTTP_200_OK):
        return Response(payloads.manager_payload(meeting), status=status_code)

    def control(self, request, pk=None):
        return self._console(self.get_object())

    def show(self, request, pk=None):
        meeting = self.get_object()
        question = self._question(meeting, request.data.get("question"), "question")
        if meeting.meeting_state != QuestionSet.MeetingState.STARTED:
            raise ValidationError({"detail": "The meeting is not running.", "code": "not_started"})
        open_ballot = ballots.open_ballot_of(meeting)
        if open_ballot is not None and (
            question is None or open_ballot.question_id != question.pk
        ):
            # The ballot pages follow the shown item: switching away would
            # hide the open vote from every voter.
            raise ValidationError({"detail": "Another vote is still open.", "code": "vote_open"})
        control, _ = MeetingControl.objects.get_or_create(meeting=meeting)
        control.current_question = question
        control.save(update_fields=["current_question"])
        live.notify(meeting)
        return self._console(meeting)

    def open_item(self, request, pk=None, question_id=None):
        meeting = self.get_object()
        question = get_object_or_404(meeting.questions, pk=question_id)
        try:
            ballots.open_ballot(meeting, question)
        except DjangoValidationError as exc:
            raise _coded(exc) from exc
        return self._console(meeting, status.HTTP_201_CREATED)

    def close_ballot(self, request, pk=None, ballot_id=None):
        meeting = self.get_object()
        try:
            ballots.close_ballot(self._ballot(meeting, ballot_id))
        except DjangoValidationError as exc:
            raise _coded(exc) from exc
        return self._console(meeting)

    def reset_ballot(self, request, pk=None, ballot_id=None):
        meeting = self.get_object()
        comment = request.data.get("comment", "")
        if not isinstance(comment, str):
            raise ValidationError({"detail": "Invalid comment.", "code": "invalid"})
        try:
            ballots.reset_ballot(self._ballot(meeting, ballot_id), comment)
        except DjangoValidationError as exc:
            raise _coded(exc) from exc
        return self._console(meeting)

    def release_texts(self, request, pk=None, ballot_id=None):
        meeting = self.get_object()
        try:
            ballots.release_texts(self._ballot(meeting, ballot_id))
        except DjangoValidationError as exc:
            raise _coded(exc) from exc
        return self._console(meeting)


# --- personal entry page (/g/<token>/) -----------------------------------------


def _localized(obj, base, lang):
    """Translated field for `lang`, falling back to the other language."""
    others = [code for code in ("de", "en") if code != lang]
    for code in (lang, *others):
        value = getattr(obj, f"{base}_{code}", "")
        if value:
            return value
    return ""


# UI strings of the ballot page's inline script (handed over via
# json_script; evaluated lazily under the page's language). Placeholders in
# braces are filled in by the script.
BALLOT_STRINGS = {
    "notStarted": _("The meeting has not started yet. This page updates by itself."),
    "waitVote": _("Please wait for the next vote."),
    "item": _("Item {number}"),
    "version": _("Version {number}"),
    "changed": _("changed"),
    "hintTap": _("One tap casts your vote immediately and for good."),
    "hintFinal": _("Your vote is final once you cast it."),
    "secret": _("Secret ballot"),
    "named": _("Roll-call vote – your vote is stored with your name."),
    "yes": _("Yes"),
    "no": _("No"),
    "abstain": _("Abstain"),
    "submit": _("Cast vote"),
    "yourAnswer": _("Your answer"),
    "styleHint": _("Your writing style may also allow conclusions about you."),
    "voted": _("Your vote has been cast."),
    "notEligible": _("You are not eligible to vote in this ballot."),
    "invalid": _("This link is not valid (any more). Please contact the chair of the meeting."),
    "reconnecting": _("Connection lost – reconnecting …"),
    "error": _("Your vote could not be cast. Please try again."),
    "voteOpen": _("Voting is open"),
    "progress": _("{voted} of {eligible} have voted"),
    "result": _("Result"),
    "total": _("Total"),
    "answers": _("Answers"),
}


def entry_page(request, token):
    """The personal ballot page: a framework-free shell that follows the
    meeting over SSE (``ballot.html``) — or, for an invalid link, only the
    generic notice."""
    invite, state = services.resolve_invite(token)
    valid = state in ("waiting", "active")
    lang = request.GET.get("lang")
    if lang not in dict(settings.LANGUAGES):
        lang = invite.member.language if valid else None
    lang = lang or (request.LANGUAGE_CODE or "").split("-")[0] or settings.MODELTRANSLATION_DEFAULT_LANGUAGE
    context = {"invalid": not valid}
    if valid:
        if state == "active":
            # Opening the link counts as entering the meeting (and, during an
            # open vote the member holds a seat for, gives them a place).
            ballots.enter(invite)
        meeting, member = invite.meeting, invite.member
        context.update(
            state=state, member=member, is_observer=member.group.is_observer,
            token=invite.token,
            strings=BALLOT_STRINGS,
            config={"token": invite.token, "observer": member.group.is_observer, "state": state},
            room_title=_localized(meeting.room, "title", lang),
            meeting_title=_localized(meeting, "title", lang),
            scheduled_at=meeting.scheduled_at,
            # Group names are content: canonical language only (PR 2), the
            # same as in the stream's progress rows.
            group_name=payloads.group_name(member.group),
        )
    with translation.override(lang):
        response = render(
            request, "committees/ballot.html", context,
            status=404 if state == "unknown" else 200,
        )
    response["Cache-Control"] = "no-store"
    response["Referrer-Policy"] = "no-referrer"
    return response


# --- ballot endpoints (cookie-less, token in the path) -------------------------


def _no_store(response):
    response["Cache-Control"] = "no-store"
    return response


@require_GET
def me(request, token):
    invite, state = services.resolve_invite(token)
    if invite is None:
        return _no_store(JsonResponse({"code": "invalid_link"}, status=404))
    if state == "active":
        ballots.enter(invite)
    ballot = ballots.open_ballot_of(invite.meeting) if state == "active" else None
    seat = (
        ballot.seats.filter(member_id=invite.member_id).first() if ballot is not None else None
    )
    return _no_store(JsonResponse({
        "state": state,
        "observer": invite.member.group.is_observer,
        "ballot": ballot.pk if ballot is not None else None,
        "eligible": seat is not None,
        "voted": bool(seat and seat.voted),
    }))


_VOTE_STATUS = {
    "already_voted": 409, "closed": 409,
    "not_eligible": 403, "invalid_link": 403,
}


# CSRF exemption is deliberate: the personal token in the path is the secret
# and the participant page is cookie-less (no session to ride on), so there is
# no ambient credential a cross-site request could abuse.
@csrf_exempt
@require_POST
def vote(request, token):
    invite, _state = services.resolve_invite(token)
    if invite is None:
        return _no_store(JsonResponse({"code": "invalid_link"}, status=403))
    try:
        body = json.loads(request.body)
        ballot_id = body["ballot"]
        answer = body["answer"]
        if isinstance(ballot_id, bool) or not isinstance(ballot_id, int):
            raise ValueError
    except (ValueError, KeyError, TypeError):
        return _no_store(JsonResponse({"code": "invalid"}, status=400))
    try:
        ballots.cast_vote(invite, ballot_id, answer)
    except DjangoValidationError as exc:
        # Only the code goes back, never anything derived from the answer.
        return _no_store(JsonResponse(
            {"code": exc.code}, status=_VOTE_STATUS.get(exc.code, 400),
        ))
    return _no_store(JsonResponse({"voted": True}))
