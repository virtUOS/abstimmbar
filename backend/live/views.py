# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Live endpoints: join, vote, presenter control, SSE stream, QR code.

Participant endpoints are anonymous (concept §9); presenter endpoints
require an owner of the room. The stream is the only async view (ADR-0003).
"""
import asyncio
import csv
import io

import nh3
import qrcode
from asgiref.sync import sync_to_async
from basicbar_integrations import ai
from basicbar_integrations.html_sanitize import clean_html
from django.conf import settings
from django.db import IntegrityError, connections, transaction
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone, translation
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.i18n_fields import resolve_translated_text, translated_map
from common.markdown import render_markdown
from common.models import SiteConfig
from rooms.models import AnswerOption, Question, QuestionSet, Room

from . import ai_evaluation, ai_freetext, ai_report, ai_wordcloud, ai_wordcloud_live
from .hub import hub, sse_frame
from .models import OrderingResponse, ParticipantToken, PriorityScore, Run, Vote
from .results import (
    likert_summary,
    options_with_counts,
    ordering_stats,
    priority_stats,
    run_results,
    words_with_counts,
)
from .state import active_run, broadcast, build_payloads, question_payload

KEEPALIVE_SECONDS = 25


def _room_by_code(code):
    # Word codes are stored lowercase; be forgiving about how a participant
    # typed it (case, surrounding whitespace). Numeric codes are unaffected.
    return get_object_or_404(Room, code=(code or "").strip().lower())


def _require_owner(user, room):
    return user.is_authenticated and (
        user.is_staff or room.owners.filter(pk=user.pk).exists()
    )


def _lang_from_query(request):
    """If ?lang= names a supported language, activate it for this request so
    the participant page (and the QR/short link that carries ?lang) renders in
    that language. Returns the code to persist as a cookie, else None."""
    lang = request.GET.get("lang")
    if lang and lang in dict(settings.LANGUAGES):
        translation.activate(lang)
        request.LANGUAGE_CODE = lang
        return lang
    return None


# --- participant pages (served by Django: ultra-light, same-origin) --------


@ensure_csrf_cookie
def participant_home(request):
    """The stable home URL with the code input (concept §6.2)."""
    lang = _lang_from_query(request)
    response = render(request, "live/home.html")
    if lang:
        response.set_cookie(settings.LANGUAGE_COOKIE_NAME, lang, max_age=31536000, samesite="Lax")
    return response


@ensure_csrf_cookie
def participant_page(request, code):
    lang = _lang_from_query(request)
    room = _room_by_code(code)
    # Closing info shown once the vote is finished (#24): the site-wide text
    # first, the room's own below it. closing_info now stores sanitized HTML
    # (editor-unify #49); render it directly (defensively re-cleaned) instead
    # of through the Markdown parser, which would double-process it.
    site = SiteConfig.load()
    closing_html = clean_html(site.closing_info) + clean_html(room.closing_info)
    response = render(
        request,
        "live/participant.html",
        {
            "room": room,
            "closing_html": closing_html,
            # Content-i18n (#33 MR2): fallback language for the client-side
            # `locText` resolver when the participant's UI language isn't
            # among the authored keys.
            "CONTENT_DEFAULT_LANGUAGE": settings.MODELTRANSLATION_DEFAULT_LANGUAGE,
        },
    )
    if lang:
        response.set_cookie(settings.LANGUAGE_COOKIE_NAME, lang, max_age=31536000, samesite="Lax")
    return response


@xframe_options_exempt
@ensure_csrf_cookie
def question_preview(request, question_id):
    """Owner-only interactive preview of one question (#74).

    Reuses the participant page in a standalone "preview" mode: it renders the
    question exactly as participants see it — no run, no SSE, submissions inert.
    The question payload is the same one the live loop broadcasts.

    Deliberately NOT under the ``/p/`` prefix: the basicbar_lti frame-ancestors
    middleware rewrites framing headers there (to 'self' + LMS origins), which
    would block the editor's cross-origin dev iframe. Here we set our own CSP
    allowing only 'self' + the app's own SPA (FRONTEND_BASE_URL), so it embeds
    in dev (cross-origin) and prod (same-origin) without opening it up wider.
    """
    question = get_object_or_404(
        Question.objects.select_related("question_set__room"), pk=question_id
    )
    room = question.question_set.room
    if not _require_owner(request.user, room):
        raise Http404
    preview_state = {
        "phase": "open",
        "run_id": 0,
        "room": {
            "code": "",
            "title": translated_map(room, "title"),
            "show_logo": False,
            "show_qr": False,
            "show_code": False,
            "corner": room.presentation_corner,
        },
        "set_title": translated_map(question.question_set, "title"),
        "question": question_payload(question, shuffle_seed=0),
    }
    response = render(
        request,
        "live/participant.html",
        {
            "room": room,
            "preview": True,
            "preview_state": preview_state,
            "closing_html": "",
            "CONTENT_DEFAULT_LANGUAGE": settings.MODELTRANSLATION_DEFAULT_LANGUAGE,
        },
    )
    # Frame only in our own app (SPA editor), dev cross-origin included.
    response["Content-Security-Policy"] = (
        f"frame-ancestors 'self' {settings.FRONTEND_BASE_URL}"
    )
    return response


def room_qr(request, code):
    """QR code pointing at the participant short URL."""
    room = _room_by_code(code)
    url = request.build_absolute_uri(f"/p/{room.code}")
    image = qrcode.make(url, box_size=12, border=1)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return HttpResponse(buffer.getvalue(), content_type="image/png")


# --- participant API ---------------------------------------------------------


@api_view(["POST"])
def join(request, code):
    """Issue (or confirm) a participant token for this room."""
    room = _room_by_code(code)
    key = (request.data.get("token") or "").strip()
    token = None
    if key:
        token = ParticipantToken.objects.filter(room=room, key=key).first()
    if token is None:
        token = ParticipantToken.objects.create(room=room)
    return Response({"token": token.key})


def _clean_priority_points(question, raw):
    """Validate a ``priorities`` submission (#58).

    Returns ``(points_by_option_id, None)`` with an entry for EVERY option of
    the question (options missing from ``raw`` default to 0), or
    ``(None, error_message)`` on invalid input. Total must not exceed 100.
    """
    if not isinstance(raw, dict):
        return None, "Points must be an object."
    valid_ids = list(question.options.values_list("pk", flat=True))
    valid = set(valid_ids)
    cleaned = {}
    for key, value in raw.items():
        try:
            option_id = int(key)
        except (TypeError, ValueError):
            return None, "Invalid option id."
        if option_id not in valid:
            return None, "Invalid option."
        if isinstance(value, bool) or not isinstance(value, int):
            return None, "Points must be whole numbers."
        if value < 0 or value > 100:
            return None, "Points out of range."
        cleaned[option_id] = value
    if sum(cleaned.values()) > 100:
        return None, "Total exceeds 100."
    for option_id in valid_ids:
        cleaned.setdefault(option_id, 0)
    return cleaned, None


def _clean_ordering(question, raw):
    """Validate an ``ordering`` submission (#72).

    ``raw`` must be a list of option ids that is exactly a permutation of the
    question's options (all present, no duplicates, no foreign ids). Returns
    ``(order_list_of_pks, None)`` or ``(None, error_message)``.
    """
    if not isinstance(raw, list):
        return None, "Order must be a list."
    valid_ids = list(question.options.values_list("pk", flat=True))
    cleaned = []
    for entry in raw:
        if isinstance(entry, bool):
            return None, "Invalid option id."
        try:
            option_id = int(entry)
        except (TypeError, ValueError):
            return None, "Invalid option id."
        cleaned.append(option_id)
    if sorted(cleaned) != sorted(valid_ids):
        return None, "Order must contain every option exactly once."
    return cleaned, None


@api_view(["POST"])
def vote(request, code):
    """Record one participant's answer to the currently open question."""
    room = _room_by_code(code)
    token = ParticipantToken.objects.filter(
        room=room, key=request.data.get("token", "")
    ).first()
    if token is None:
        return Response({"detail": "Unknown participant token."}, status=403)

    run = active_run(room)
    if run is None or run.phase != Run.Phase.OPEN:
        return Response({"detail": "Voting is closed."}, status=status.HTTP_409_CONFLICT)

    if run.mode == Run.Mode.SELF_PACED:
        # Self-paced (concept §6.3): every question of the set is open;
        # the participant says which one they are answering. No countdown —
        # own pace is the point.
        question = Question.objects.filter(
            question_set=run.question_set, pk=request.data.get("question")
        ).first()
        if question is None:
            return Response({"detail": "Unknown question."}, status=400)
    else:
        question = run.active_question
        if question is None:
            return Response(
                {"detail": "Voting is closed."}, status=status.HTTP_409_CONFLICT
            )
        # Countdown enforcement (v2): the timer is not just cosmetic — late
        # votes are rejected server-side (1 s network grace).
        if question.time_limit and run.opened_at:
            deadline = run.opened_at + timezone.timedelta(seconds=question.time_limit + 1)
            if timezone.now() > deadline:
                return Response(
                    {"detail": "Time is up."}, status=status.HTTP_409_CONFLICT
                )

    # Double-vote guard (app-level, since the DB constraint is gone): one
    # submission per participant/question/run — except word clouds marked
    # ``allow_multiple`` in a live run, which collect several terms (#14).
    allow_multiple = (
        run.mode == Run.Mode.LIVE
        and question.kind == Question.Kind.WORD_CLOUD
        and question.allow_multiple
    )
    if not allow_multiple and Vote.objects.filter(
        run=run, question=question, token=token
    ).exists():
        return Response({"detail": "Already voted."}, status=status.HTTP_409_CONFLICT)

    # Per-participant cap for allow_multiple word clouds (#76): reject once the
    # token has contributed the author's maximum (0 = unlimited). Enforced here
    # so a manipulated client cannot exceed it.
    if allow_multiple and question.wordcloud_max_answers and Vote.objects.filter(
        run=run, question=question, token=token
    ).count() >= question.wordcloud_max_answers:
        return Response(
            {"detail": "Maximum reached."}, status=status.HTTP_409_CONFLICT
        )

    if question.kind == Question.Kind.PRIORITIES:
        cleaned, error = _clean_priority_points(question, request.data.get("points"))
        if error:
            return Response({"detail": error}, status=400)
        options = {o.pk: o for o in question.options.all()}
        try:
            with transaction.atomic():
                vote_obj = Vote.objects.create(run=run, question=question, token=token)
                PriorityScore.objects.bulk_create(
                    [
                        PriorityScore(vote=vote_obj, option=options[oid], points=pts)
                        for oid, pts in cleaned.items()
                    ]
                )
        except IntegrityError:
            return Response(
                {"detail": "Already voted."}, status=status.HTTP_409_CONFLICT
            )
        broadcast(room, debounce=True)
        return Response({"status": "ok"}, status=status.HTTP_201_CREATED)

    if question.kind == Question.Kind.ORDERING:
        order, error = _clean_ordering(question, request.data.get("order"))
        if error:
            return Response({"detail": error}, status=400)
        options = {o.pk: o for o in question.options.all()}
        try:
            with transaction.atomic():
                vote_obj = Vote.objects.create(run=run, question=question, token=token)
                OrderingResponse.objects.bulk_create(
                    [
                        OrderingResponse(vote=vote_obj, option=options[oid], position=idx)
                        for idx, oid in enumerate(order)
                    ]
                )
        except IntegrityError:
            return Response({"detail": "Already voted."}, status=status.HTTP_409_CONFLICT)
        broadcast(room, debounce=True)
        return Response({"status": "ok"}, status=status.HTTP_201_CREATED)

    if question.kind in Question.TEXT_KINDS:
        text = str(request.data.get("text", "")).strip()
        if not text:
            return Response({"detail": "Empty answer."}, status=400)
        option_ids = []
        # One term per participant: reject a repeat of the same word cloud
        # entry (case-insensitive, matching the aggregation's merge) (#14).
        if allow_multiple:
            key = " ".join(text.split())[:60].casefold()[:60]
            if Vote.objects.filter(
                run=run, question=question, token=token, text_key=key
            ).exists():
                return Response(
                    {"detail": "Diesen Begriff hast du schon genannt."},
                    status=status.HTTP_409_CONFLICT,
                )
    else:
        option_ids = request.data.get("options") or []
        if not isinstance(option_ids, list) or not option_ids:
            return Response({"detail": "No option selected."}, status=400)
        single = question.kind in (Question.Kind.SINGLE_CHOICE, Question.Kind.LIKERT)
        if single and len(option_ids) > 1:
            return Response({"detail": "Only one option allowed."}, status=400)
        options = list(
            AnswerOption.objects.filter(question=question, pk__in=option_ids)
        )
        if len(options) != len(set(option_ids)):
            return Response({"detail": "Invalid option."}, status=400)
        text = ""

    try:
        with transaction.atomic():
            vote_obj = Vote.objects.create(
                run=run, question=question, token=token, text=text
            )
            if option_ids:
                vote_obj.options.set(options)
    except IntegrityError:
        return Response({"detail": "Already voted."}, status=status.HTTP_409_CONFLICT)

    broadcast(room, debounce=True)
    # Live free-text evaluation (v2 KI): hand the fresh answer to the
    # background worker; it labels it korrekt/unklar/falsch and pushes an
    # updated presenter snapshot. Only for opted-in open_text questions.
    if question.kind == Question.Kind.OPEN_TEXT and question.ai_evaluate:
        ai_evaluation.schedule(vote_obj.pk, room.pk)
    # Live word-cloud AI (consolidate/group): only recomputes while the
    # presenter is showing an AI view for this question (throttled).
    if question.kind == Question.Kind.WORD_CLOUD:
        ai_wordcloud_live.schedule(run.pk, question.pk, room.pk)
    payload = {"status": "ok"}
    if run.mode == Run.Mode.SELF_PACED:
        feedback = _self_paced_feedback(run, question, set(option_ids))
        if feedback is not None:
            payload.update(feedback)
    return Response(payload, status=status.HTTP_201_CREATED)


@api_view(["POST"])
def retract(request, code):
    """Withdraw one of the participant's own word-cloud terms while the
    question is open (#14). Deletes only the caller's matching vote(s) —
    identified by the opaque token — so anonymity is preserved."""
    room = _room_by_code(code)
    token = ParticipantToken.objects.filter(
        room=room, key=request.data.get("token", "")
    ).first()
    if token is None:
        return Response({"detail": "Unknown participant token."}, status=403)
    run = active_run(room)
    if run is None or run.phase != Run.Phase.OPEN:
        return Response({"detail": "Voting is closed."}, status=status.HTTP_409_CONFLICT)
    question = run.active_question
    if question is None:
        return Response({"detail": "Voting is closed."}, status=status.HTTP_409_CONFLICT)
    raw = str(request.data.get("text", "")).strip()
    key = " ".join(raw.split())[:60].casefold()[:60]
    if not key:
        return Response({"detail": "Empty answer."}, status=400)
    deleted, _ = Vote.objects.filter(
        run=run, question=question, token=token, text_key=key
    ).delete()
    if deleted:
        broadcast(room, debounce=True)
    return Response({"deleted": deleted})


def _self_paced_feedback(run, question, chosen_ids):
    """Instant right/wrong feedback (concept §6.3), unless the set says
    "never reveal" or the question has no correct answer marked."""
    if run.question_set.reveal_answers == "never":
        return None
    if question.kind not in Question.CHOICE_KINDS:
        return None
    correct_ids = set(
        question.options.filter(is_correct=True).values_list("pk", flat=True)
    )
    if not correct_ids:
        return None
    return {"correct": sorted(correct_ids), "is_correct": chosen_ids == correct_ids}


@api_view(["GET"])
def quiz(request, code):
    """All questions of the open self-paced run (concept §6.3).

    Fetched once by the participant page; ?token= additionally returns
    which questions this participant already answered (and whether
    correctly), so a reload resumes instead of restarting.
    """
    room = _room_by_code(code)
    run = active_run(room)
    if run is None or run.mode != Run.Mode.SELF_PACED or run.phase != Run.Phase.OPEN:
        return Response(
            {"detail": "No self-paced quiz is open."}, status=status.HTTP_409_CONFLICT
        )

    questions = list(run.question_set.questions.prefetch_related("options"))
    feedback = run.question_set.reveal_answers != "never"

    answered = {}
    token = ParticipantToken.objects.filter(
        room=room, key=request.GET.get("token", "")
    ).first()
    if token is not None:
        votes = run.votes.filter(token=token).prefetch_related("options")
        for vote_obj in votes:
            question = next(
                (q for q in questions if q.pk == vote_obj.question_id), None
            )
            entry = {"is_correct": None}
            if feedback and question and question.kind in Question.CHOICE_KINDS:
                correct_ids = {o.pk for o in question.options.all() if o.is_correct}
                if correct_ids:
                    chosen_ids = {o.pk for o in vote_obj.options.all()}
                    entry["is_correct"] = chosen_ids == correct_ids
            answered[str(vote_obj.question_id)] = entry

    return Response(
        {
            # {de, en} map (#33 MR2), matching every other title/text field in
            # this payload (via question_payload) and the live SSE snapshot.
            "set_title": translated_map(run.question_set, "title"),
            "feedback": feedback,
            "questions": [question_payload(q, shuffle_seed=run.pk) for q in questions],
            "answered": answered,
        }
    )


# --- recording mode (#53): async viewer voting ------------------------------


def _recording_run(token):
    """The recorded run for a deep-link token, or 404. Independent of the
    room's active run — a recorded run may be finished and still accept
    async votes."""
    run = (
        Run.objects.filter(recording_token=token)
        .select_related("question_set__room")
        .first()
        if token
        else None
    )
    if run is None:
        raise Http404
    return run


class _AnswerError(Exception):
    """Payload validation error for a single vote."""

    def __init__(self, detail):
        self.detail = detail


def _parse_answer(question, data):
    """Validate a vote payload for ``question``; return (text, option_ids,
    options). Raises _AnswerError(detail) on invalid input. Shared shape with
    the live vote view."""
    if question.kind in Question.TEXT_KINDS:
        text = str(data.get("text", "")).strip()
        if not text:
            raise _AnswerError("Empty answer.")
        return text, [], []
    option_ids = data.get("options") or []
    if not isinstance(option_ids, list) or not option_ids:
        raise _AnswerError("No option selected.")
    single = question.kind in (Question.Kind.SINGLE_CHOICE, Question.Kind.LIKERT)
    if single and len(option_ids) > 1:
        raise _AnswerError("Only one option allowed.")
    options = list(AnswerOption.objects.filter(question=question, pk__in=option_ids))
    if len(options) != len(set(option_ids)):
        raise _AnswerError("Invalid option.")
    return "", option_ids, options


def _question_results(run, question):
    """Combined per-question results (all sources) for the viewer client."""
    if question.kind in Question.TEXT_KINDS:
        return {"words": words_with_counts(run, question)}
    if question.kind == Question.Kind.PRIORITIES:
        return {"priorities": priority_stats(run, question)}
    if question.kind == Question.Kind.ORDERING:
        return {"ordering": ordering_stats(run, question)}
    payload = {"results": options_with_counts(run, question)}
    if question.kind == Question.Kind.LIKERT:
        payload["likert"] = likert_summary(payload["results"])
    return payload


@api_view(["GET"])
def recording_questions(request, token):
    """All questions of a recorded run for the async viewer (#53).

    Mirrors ``quiz`` but is keyed by the run's recording token and returns the
    combined results for questions this viewer already answered (?token=), so a
    reload/resume shows results for answered questions.
    """
    run = _recording_run(token)
    questions = list(run.question_set.questions.prefetch_related("options"))
    feedback = run.question_set.reveal_answers != "never"

    answered = {}
    token_obj = ParticipantToken.objects.filter(
        room=run.question_set.room, key=request.GET.get("token", "")
    ).first()
    if token_obj is not None:
        votes = run.votes.filter(
            token=token_obj, source=Vote.Source.RECORDING
        ).prefetch_related("options")
        by_id = {q.pk: q for q in questions}
        for vote_obj in votes:
            question = by_id.get(vote_obj.question_id)
            if question is None:
                continue
            entry = {"is_correct": None, **_question_results(run, question)}
            if feedback and question.kind in Question.CHOICE_KINDS:
                correct_ids = {o.pk for o in question.options.all() if o.is_correct}
                if correct_ids:
                    chosen_ids = {o.pk for o in vote_obj.options.all()}
                    entry["is_correct"] = chosen_ids == correct_ids
                    entry["correct"] = sorted(correct_ids)
            answered[str(vote_obj.question_id)] = entry

    return Response(
        {
            "set_title": translated_map(run.question_set, "title"),
            "room_code": run.question_set.room.code,
            "feedback": feedback,
            "questions": [question_payload(q, shuffle_seed=run.pk) for q in questions],
            "answered": answered,
        }
    )


@api_view(["POST"])
def recording_vote(request, token):
    """Record an async viewer's answer against the recorded run (#53).

    Dedicated path: bypasses ``active_run``/phase gating; no server-side time
    limit (client countdown only). Tags the vote ``source=recording`` so it
    attributes to the original run yet stays separable from on-site votes.
    Returns the combined results for the question so the viewer sees them.
    """
    run = _recording_run(token)
    room = run.question_set.room
    token_obj = ParticipantToken.objects.filter(
        room=room, key=request.data.get("token", "")
    ).first()
    if token_obj is None:
        return Response({"detail": "Unknown participant token."}, status=403)
    question = Question.objects.filter(
        question_set=run.question_set, pk=request.data.get("question")
    ).first()
    if question is None:
        return Response({"detail": "Unknown question."}, status=400)

    allow_multiple = (
        question.kind == Question.Kind.WORD_CLOUD and question.allow_multiple
    )
    if not allow_multiple and Vote.objects.filter(
        run=run, question=question, token=token_obj, source=Vote.Source.RECORDING
    ).exists():
        return Response({"detail": "Already voted."}, status=status.HTTP_409_CONFLICT)

    # Per-participant cap for allow_multiple word clouds (#76), recording path.
    if allow_multiple and question.wordcloud_max_answers and Vote.objects.filter(
        run=run, question=question, token=token_obj, source=Vote.Source.RECORDING
    ).count() >= question.wordcloud_max_answers:
        return Response(
            {"detail": "Maximum reached."}, status=status.HTTP_409_CONFLICT
        )

    if question.kind == Question.Kind.PRIORITIES:
        cleaned, error = _clean_priority_points(question, request.data.get("points"))
        if error:
            return Response({"detail": error}, status=400)
        options = {o.pk: o for o in question.options.all()}
        with transaction.atomic():
            vote_obj = Vote.objects.create(
                run=run, question=question, token=token_obj,
                source=Vote.Source.RECORDING,
            )
            PriorityScore.objects.bulk_create(
                [PriorityScore(vote=vote_obj, option=options[oid], points=pts)
                 for oid, pts in cleaned.items()]
            )
        return Response(
            {"status": "ok", **_question_results(run, question)},
            status=status.HTTP_201_CREATED,
        )

    if question.kind == Question.Kind.ORDERING:
        order, error = _clean_ordering(question, request.data.get("order"))
        if error:
            return Response({"detail": error}, status=400)
        options = {o.pk: o for o in question.options.all()}
        with transaction.atomic():
            vote_obj = Vote.objects.create(
                run=run, question=question, token=token_obj,
                source=Vote.Source.RECORDING,
            )
            OrderingResponse.objects.bulk_create(
                [OrderingResponse(vote=vote_obj, option=options[oid], position=idx)
                 for idx, oid in enumerate(order)]
            )
        return Response(
            {"status": "ok", **_question_results(run, question)},
            status=status.HTTP_201_CREATED,
        )

    try:
        text, option_ids, options = _parse_answer(question, request.data)
    except _AnswerError as error:
        return Response({"detail": error.detail}, status=400)

    if allow_multiple and text:
        key = " ".join(text.split())[:60].casefold()[:60]
        if Vote.objects.filter(
            run=run, question=question, token=token_obj,
            source=Vote.Source.RECORDING, text_key=key,
        ).exists():
            return Response(
                {"detail": "Diesen Begriff hast du schon genannt."},
                status=status.HTTP_409_CONFLICT,
            )

    with transaction.atomic():
        vote_obj = Vote.objects.create(
            run=run, question=question, token=token_obj, text=text,
            source=Vote.Source.RECORDING,
        )
        if option_ids:
            vote_obj.options.set(options)

    payload = {"status": "ok", **_question_results(run, question)}
    feedback = _self_paced_feedback(run, question, set(option_ids))
    if feedback is not None:
        payload.update(feedback)
    return Response(payload, status=status.HTTP_201_CREATED)


def recording_qr(request, token):
    """QR code for a recorded run's per-question deep link (#53)."""
    _recording_run(token)  # 404 for an unknown/disabled token
    url = request.build_absolute_uri(f"/r/{token}/")
    question_id = request.GET.get("q")
    if question_id and question_id.isdigit():
        url += f"?q={question_id}"
    image = qrcode.make(url, box_size=8, border=1)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return HttpResponse(buffer.getvalue(), content_type="image/png")


@ensure_csrf_cookie
def recording_page(request, token):
    """The async viewer page for a recording (#53) — reuses participant.html
    in recording mode (no SSE; drives the question flow via the recording
    endpoints)."""
    lang = _lang_from_query(request)
    run = _recording_run(token)
    room = run.question_set.room
    site = SiteConfig.load()
    closing_html = clean_html(site.closing_info) + clean_html(room.closing_info)
    entry = request.GET.get("q") or ""
    response = render(
        request,
        "live/participant.html",
        {
            "room": room,
            "closing_html": closing_html,
            "CONTENT_DEFAULT_LANGUAGE": settings.MODELTRANSLATION_DEFAULT_LANGUAGE,
            "recording_token": token,
            "entry_question": entry if entry.isdigit() else "",
        },
    )
    if lang:
        response.set_cookie(settings.LANGUAGE_COOKIE_NAME, lang, max_age=31536000, samesite="Lax")
    return response


# --- presenter API -----------------------------------------------------------


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def live_status(request, set_id):
    """For the start dialog: is there an active run / stored votes?"""
    question_set = get_object_or_404(QuestionSet, pk=set_id)
    if not _require_owner(request.user, question_set.room):
        raise Http404
    run = (
        Run.objects.filter(question_set=question_set)
        .exclude(phase=Run.Phase.FINISHED)
        .first()
    )
    has_votes = Vote.objects.filter(run__question_set=question_set).exists()
    # Whether the run the start dialog would resume already carries answers —
    # lets the UI offer archive/delete instead of silently appending (#70).
    active_run_has_votes = bool(run and run.votes.exists())
    return Response(
        {
            "active_run": run.pk if run else None,
            "has_votes": has_votes,
            "active_run_has_votes": active_run_has_votes,
            "room_code": question_set.room.code,
        }
    )


def _finish_other_room_runs(room, keep_set):
    """Enforce one active run per room: archive (has votes, or a minted
    recording token) or delete (neither) the unfinished runs of *other* sets
    in ``room`` before a new run is activated. The participant page shows a
    single active run, but the per-set constraint
    (``one_active_run_per_set``) still allows a different set to hold an
    unfinished run — this closes that gap. A run with a recording token
    must be archived rather than deleted: the recording vote path
    (``recording_vote``/``_recording_run``) is phase-independent, so a
    finished run still serves its shared ``/r/<token>/`` link and accepts
    future async votes — deleting it would break that link and lose them.
    The target set (``keep_set``) keeps its own continue/archive/delete
    flow."""
    others = (
        Run.objects.filter(question_set__room=room)
        .exclude(phase=Run.Phase.FINISHED)
        .exclude(question_set=keep_set)
    )
    for other in others:
        if other.votes.exists() or other.recording_token:
            other.phase = Run.Phase.FINISHED
            other.ended_at = timezone.now()
            other.save(update_fields=["phase", "ended_at", "updated_at"])
        else:
            other.delete()


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def start_run(request, set_id):
    """Start presenting: reuse the unfinished run, or reset (delete results).

    Body: {"reset": bool, "mode": "live"|"self_paced"} — reset deletes all
    previous runs of this set including votes ("Ergebnisse löschen? ja");
    otherwise new votes add to the existing ones (Cliqr behaviour).
    Teacher-paced ↔ self-paced is switchable (concept §6.3): starting in
    the other mode repurposes the unfinished run.
    """
    question_set = get_object_or_404(QuestionSet.objects.select_related("room"), pk=set_id)
    if not _require_owner(request.user, question_set.room):
        raise Http404
    mode = request.data.get("mode") or Run.Mode.LIVE
    if mode not in {m.value for m in Run.Mode}:
        return Response({"detail": "Invalid mode."}, status=400)

    # One active run per room: a room's participant page shows a single
    # active run, so finish/drop any unfinished run of *other* sets first.
    _finish_other_room_runs(question_set.room, question_set)

    # What to do with prior results of this set (start dialog, #17):
    #   delete   — wipe all previous runs and start empty
    #   continue — keep counting into the most recent run (same Durchführung)
    #   archive  — leave previous runs as named archives, start a fresh one
    # (legacy ``reset`` maps to delete / continue.)
    existing = request.data.get("existing")
    user = request.user
    if (
        existing is None
        and not request.data.get("reset")
        and getattr(user, "effective_easy_mode", False)
    ):
        # Easy mode (#52): no start dialog — auto-archive when the latest
        # non-empty run is from another calendar day, else continue. Driven
        # by ``effective_easy_mode`` (explicit choice, else Pro default for
        # staff / Simple default for everyone else) so an admin who opted
        # into Simple gets this too, not just non-staff users. Only kicks in
        # when the request carries no explicit signal at all (no
        # ``existing``, no legacy ``reset``) — an easy-mode UI never sends
        # either, but pre-existing/legacy callers that do must be unaffected.
        last = (
            question_set.runs.filter(votes__isnull=False)
            .order_by("-created_at")
            .first()
        )
        if last is not None and timezone.localdate(last.created_at) != timezone.localdate():
            existing = "archive"
        else:
            existing = "continue"
    if existing not in {"delete", "continue", "archive"}:
        existing = "delete" if request.data.get("reset") else "continue"

    if existing == "delete":
        Run.objects.filter(question_set=question_set).delete()
    elif existing == "archive":
        # Keep the current Durchführung as an archive. This must also handle an
        # UNFINISHED run that already carries answers (the presenter closed the
        # tab without ending it) — otherwise the code below would reactivate it
        # and new votes would land on the old run instead of a fresh one (#70).
        # An empty unfinished run needs no archiving; it is reused below.
        for stale in (
            Run.objects.filter(question_set=question_set)
            .exclude(phase=Run.Phase.FINISHED)
        ):
            if stale.votes.exists():
                stale.phase = Run.Phase.FINISHED
                stale.ended_at = timezone.now()
                stale.save(update_fields=["phase", "ended_at", "updated_at"])

    initial_phase = Run.Phase.OPEN if mode == Run.Mode.SELF_PACED else Run.Phase.LOBBY

    # An unfinished run is always resumed (the start dialog only appears once
    # every run is finished). Otherwise: continue reactivates the latest run;
    # archive/delete begin a brand-new one alongside/without the old.
    run = (
        Run.objects.filter(question_set=question_set)
        .exclude(phase=Run.Phase.FINISHED)
        .first()
    )
    if run is None and existing == "continue":
        run = Run.objects.filter(question_set=question_set).order_by("-created_at").first()

    if run is None:
        run = Run.objects.create(question_set=question_set, mode=mode, phase=initial_phase)
        if mode == Run.Mode.SELF_PACED:
            run.first_opened_at = timezone.now()
            run.save(update_fields=["first_opened_at"])
    else:
        run.mode = mode
        run.phase = initial_phase
        run.active_question = None
        run.answers_revealed = False
        run.ended_at = None
        if mode == Run.Mode.SELF_PACED and run.first_opened_at is None:
            run.first_opened_at = timezone.now()
        run.save()
    # Recording mode (#53): opt-in per presentation, live only. Mints a
    # recording token so viewers of the recording can vote later via
    # /r/<token>/. Never for self-paced (already async). Pro feature — the
    # easy-mode start flow never sends it.
    if mode == Run.Mode.LIVE and request.data.get("recording"):
        run.enable_recording()
    else:
        # Start without recording clears a stale token from a resumed run.
        run.disable_recording()
    broadcast(question_set.room)
    return Response(
        {
            "run": run.pk,
            "room_code": question_set.room.code,
            "recording_token": run.recording_token,
        }
    )


VALID_PHASES = {p.value for p in Run.Phase}


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def control_run(request, run_id):
    """Presenter phase machine: {"phase": …, "question": id|null}."""
    run = get_object_or_404(
        Run.objects.select_related("question_set__room"), pk=run_id
    )
    room = run.question_set.room
    if not _require_owner(request.user, room):
        raise Http404
    if not run.is_active:
        return Response({"detail": "Run is finished."}, status=409)

    # Reveal correct answers (v2): server state so participant devices
    # highlight in sync with the beamer (presenter key "A").
    if request.data.get("reveal"):
        run.answers_revealed = True
        run.save(update_fields=["answers_revealed", "updated_at"])
        broadcast(room)
        return Response({"status": "ok", "phase": run.phase})

    # Recording mode (#53): turn the current run into a recorded one so the
    # beamer shows per-question deep links; live only (self-paced is already
    # async). Mints a token once; broadcast carries it to the beamer.
    if request.data.get("recording") and run.mode == Run.Mode.LIVE:
        run.enable_recording()
        broadcast(room)
        return Response({"status": "ok", "recording_token": run.recording_token})

    phase = request.data.get("phase")
    if phase not in VALID_PHASES:
        return Response({"detail": "Invalid phase."}, status=400)

    if "question" in request.data:
        question_id = request.data["question"]
        if question_id is None:
            run.active_question = None
        else:
            run.active_question = get_object_or_404(
                Question, pk=question_id, question_set=run.question_set
            )

    needs_question = phase in {
        Run.Phase.PREVIEW, Run.Phase.OPEN, Run.Phase.CLOSED, Run.Phase.RESULTS
    }
    if needs_question and run.active_question is None:
        return Response({"detail": "No active question."}, status=400)

    run.phase = phase
    if phase == Run.Phase.OPEN:
        run.opened_at = timezone.now()
        if run.first_opened_at is None:
            run.first_opened_at = run.opened_at
    if phase in (Run.Phase.PREVIEW, Run.Phase.OPEN):
        run.answers_revealed = False
    if phase == Run.Phase.FINISHED:
        run.ended_at = timezone.now()
    run.save()
    # Eager AI word-cloud (#75): start computing as soon as the vote closes so
    # the presenter can switch to the AI views instantly (kept warm afterwards).
    if phase in (Run.Phase.CLOSED, Run.Phase.RESULTS):
        q = run.active_question
        if q and q.kind == Question.Kind.WORD_CLOUD and q.wordcloud_ai_enabled:
            ai_wordcloud_live.ensure_result(run.pk, q.pk, room.pk)
    broadcast(room)
    return Response({"status": "ok", "phase": run.phase})


# --- results (management view, M3) -------------------------------------------


def _plain(html):
    """Strip all markup (CSV/plain-text rendering of question texts)."""
    return " ".join(nh3.clean(html or "", tags=set()).split())


def _owned_question_set(user, set_id):
    question_set = get_object_or_404(
        QuestionSet.objects.select_related("room"), pk=set_id
    )
    if not _require_owner(user, question_set.room):
        raise Http404
    return question_set


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def set_results(request, set_id):
    """All runs of a set with per-question aggregations (concept §7)."""
    question_set = _owned_question_set(request.user, set_id)
    # Skip runs without any votes (e.g. a freshly prepared archive run, #27):
    # a Durchführung is only worth listing once it collected answers.
    runs = (
        question_set.runs.filter(votes__isnull=False)
        .distinct()
        .order_by("-created_at")
    )
    return Response({"results": [run_results(run) for run in runs]})


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_run(request, run_id):
    """Delete one run including its votes (concept §7)."""
    run = get_object_or_404(Run.objects.select_related("question_set__room"), pk=run_id)
    if not _require_owner(request.user, run.question_set.room):
        raise Http404
    room = run.question_set.room
    run.delete()
    broadcast(room)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def optimize_wordcloud(request, run_id, question_id):
    """Optional AI cleanup of a word-cloud result: merge spelling variants
    and synonyms, group into thematic clusters. Non-destructive — the raw
    votes are untouched; counts are recomputed server-side."""
    if not ai.is_enabled():
        return Response({"detail": "KI ist nicht konfiguriert."}, status=503)
    run = get_object_or_404(Run.objects.select_related("question_set__room"), pk=run_id)
    if not _require_owner(request.user, run.question_set.room):
        raise Http404
    question = get_object_or_404(
        Question, pk=question_id, question_set=run.question_set
    )
    if question.kind != Question.Kind.WORD_CLOUD:
        return Response({"detail": "Nur für Wortwolken verfügbar."}, status=400)
    words = words_with_counts(run, question, limit=200)
    if not words:
        return Response({"clusters": [], "merged": []})
    try:
        data = ai.chat_json(
            ai_wordcloud.optimize_system(),
            ai_wordcloud.build_optimize_prompt(words),
        )
    except ai.AIError as exc:
        return Response({"detail": f"KI-Fehler: {exc}"}, status=502)
    return Response(ai_wordcloud.apply_optimization(words, data))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def wordcloud_ai(request, run_id):
    """Presenter toggles the live AI word-cloud view on/off for a question.

    Body: {"question": <id>, "active": bool}. While active, the LLM keeps the
    consolidated + grouped views fresh (throttled); turning it off frees the
    in-memory result. Only for word-cloud questions of this run."""
    run = get_object_or_404(Run.objects.select_related("question_set__room"), pk=run_id)
    room = run.question_set.room
    if not _require_owner(request.user, room):
        raise Http404
    question = get_object_or_404(
        Question, pk=request.data.get("question"), question_set=run.question_set
    )
    if question.kind != Question.Kind.WORD_CLOUD or not question.wordcloud_ai_enabled:
        return Response(
            {"detail": "KI-Aufräumen ist für diese Frage nicht aktiviert."},
            status=400,
        )
    if not ai.is_enabled():
        return Response({"detail": "KI ist nicht konfiguriert."}, status=503)
    active = bool(request.data.get("active"))
    ai_wordcloud_live.set_active(run.pk, question.pk, room.pk, active)
    return Response({"status": "ok", "active": active})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def evaluate_freetext(request, run_id, question_id):
    """Optional AI evaluation of free-text answers: classify each distinct
    answer as korrekt / unklar / falsch. Non-destructive; counts are
    recomputed server-side. An optional ``reference`` (expected answer or
    criterion) sharpens the judgement."""
    if not ai.is_enabled():
        return Response({"detail": "KI ist nicht konfiguriert."}, status=503)
    run = get_object_or_404(Run.objects.select_related("question_set__room"), pk=run_id)
    if not _require_owner(request.user, run.question_set.room):
        raise Http404
    question = get_object_or_404(
        Question, pk=question_id, question_set=run.question_set
    )
    if question.kind != Question.Kind.OPEN_TEXT:
        return Response({"detail": "Nur für Freitext-Fragen verfügbar."}, status=400)
    categories = question.evaluation_categories
    answers = words_with_counts(run, question, limit=200)
    if not answers:
        return Response(
            {"groups": [], "categories": ai_freetext.clean_categories(categories),
             "chart": question.evaluation_chart}
        )
    reference = str(request.data.get("reference") or "").strip()[
        : ai_freetext.REFERENCE_MAX
    ]
    try:
        data = ai.chat_json(
            ai_freetext.evaluate_system(categories),
            ai_freetext.build_evaluate_prompt(
                # Canonical text for the LLM (#33 MR2): the model works on
                # one language, not the {de, en} map.
                resolve_translated_text(translated_map(question, "text")),
                reference, answers, categories,
            ),
        )
    except ai.AIError as exc:
        return Response({"detail": f"KI-Fehler: {exc}"}, status=502)
    result = ai_freetext.apply_evaluation(answers, data, categories)
    result["chart"] = question.evaluation_chart
    return Response(result)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def run_summary(request, run_id):
    """Optional AI short report of one run: a compact German Markdown
    summary of the (anonymous, already-aggregated) results. Display-only."""
    if not ai.is_enabled():
        return Response({"detail": "KI ist nicht konfiguriert."}, status=503)
    run = get_object_or_404(Run.objects.select_related("question_set__room"), pk=run_id)
    if not _require_owner(request.user, run.question_set.room):
        raise Http404
    results = run_results(run)
    if not results["votes_total"]:
        return Response({"detail": "Noch keine Antworten für einen Bericht."}, status=400)
    try:
        data = ai.chat_json(
            ai_report.report_system(),
            ai_report.build_report_prompt(
                # Canonical text for the LLM (#33 MR2), not the request's
                # active UI language.
                resolve_translated_text(translated_map(run.question_set, "title")),
                results,
            ),
        )
    except ai.AIError as exc:
        return Response({"detail": f"KI-Fehler: {exc}"}, status=502)
    report = str(data.get("report", "")).strip()[: ai_report.REPORT_MAX]
    if not report:
        return Response({"detail": "Kein Bericht erhalten."}, status=502)
    # Render the LLM's Markdown to sanitized HTML so the client shows it via
    # RichText like all other rich content (editor-unify #49).
    return Response({"report": render_markdown(report)})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def delete_results(request, set_id):
    """Delete all runs (and votes) of a set."""
    question_set = _owned_question_set(request.user, set_id)
    question_set.runs.all().delete()
    broadcast(question_set.room)
    return Response({"status": "ok"})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def archive_results(request, set_id):
    """Archive the current results and prepare a fresh run (#27).

    A one-click shortcut for the presentation start dialog's "Archivieren &
    neu starten": the running (or most recent) Durchführung is finished and
    kept as an archive, and an empty run is prepared so the next presentation
    starts clean — without the presenter having to open the start dialog.
    Idempotent: if an empty run is already waiting, it is returned as-is.
    """
    question_set = _owned_question_set(request.user, set_id)
    active = (
        question_set.runs.exclude(phase=Run.Phase.FINISHED)
        .order_by("-created_at")
        .first()
    )
    # Finish a Durchführung only if it actually collected answers; an empty
    # unfinished run is already the "fresh" run we would create.
    if active is not None and active.votes.exists():
        active.phase = Run.Phase.FINISHED
        active.ended_at = timezone.now()
        active.save(update_fields=["phase", "ended_at", "updated_at"])
        active = None
    if active is None:
        active = Run.objects.create(
            question_set=question_set,
            mode=Run.Mode.LIVE,
            phase=Run.Phase.LOBBY,
        )
    broadcast(question_set.room)
    return Response({"run": active.pk})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def results_csv(request, set_id):
    """CSV export of all stored results of a set (concept §7).

    Semicolon-separated with a UTF-8 BOM so German Excel opens it directly.
    """
    question_set = _owned_question_set(request.user, set_id)
    # Optional ?run=<id>: export only that Durchführung, else the whole set
    # including archived runs (#17).
    runs = question_set.runs.order_by("created_at")
    run_id = request.query_params.get("run")
    if run_id:
        runs = runs.filter(pk=run_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(
        ["durchfuehrung", "gestartet", "frage_nr", "frage", "antwort", "richtig",
         "stimmen", "vor_ort", "aufzeichnung", "prozent"]
    )
    for run in runs:
        started = run.first_opened_at or run.created_at
        for question in run.question_set.questions.prefetch_related("options"):
            # CSV needs a plain string (#33 MR2): resolve the {de, en} map to
            # the canonical/active language rather than exporting a dict.
            question_text = resolve_translated_text(translated_map(question, "text"))
            base = [run.pk, started.strftime("%Y-%m-%d %H:%M"),
                    question.position + 1, _plain(question_text)]
            if question.kind in Question.TEXT_KINDS:
                for word in words_with_counts(run, question, limit=100000):
                    writer.writerow(
                        base
                        + [word["text"], "", word["count"],
                           word.get("onsite", ""), word.get("recording", ""), ""]
                    )
            elif question.kind == Question.Kind.PRIORITIES:
                # Fixed CSV schema: for priorities the stimmen/vor_ort/
                # aufzeichnung columns carry the average / min / max points.
                for option in priority_stats(run, question):
                    writer.writerow(
                        base
                        + [resolve_translated_text(option["text"]), "",
                           option["avg"], option["min"], option["max"], ""]
                    )
            elif question.kind == Question.Kind.ORDERING:
                # Fixed CSV schema: for ordering the "stimmen" column carries the
                # per-item correct-placement rate (%) and "prozent" the solution
                # position; a summary row carries the fully-correct rate.
                stats = ordering_stats(run, question)
                for item in stats["items"]:
                    writer.writerow(
                        base
                        + [resolve_translated_text(item["text"]), "",
                           item["correct_rate"], "", "", item["correct_position"]]
                    )
                writer.writerow(
                    base + ["Zusammenfassung: komplett richtig", "",
                            stats["full_correct_rate"], "", "", ""]
                )
            else:
                options = options_with_counts(run, question)
                summary = (
                    likert_summary(options)
                    if question.kind == Question.Kind.LIKERT
                    else None
                )
                # Per-step %s over the scale (excluding abstentions) for Likert.
                step_pct = {s["id"]: s["pct"] for s in summary["steps"]} if summary else {}
                for option in options:
                    writer.writerow(
                        base
                        + [resolve_translated_text(option["text"]),
                           "x" if option["is_correct"] else "",
                           option["count"], option.get("onsite", ""),
                           option.get("recording", ""),
                           step_pct.get(option["id"], "")]
                    )
                if summary:
                    for label, count, pct in (
                        ("Zusammenfassung: Zustimmung", summary["agree"], summary["agree_pct"]),
                        ("Zusammenfassung: Neutral", summary["neutral"], summary["neutral_pct"]),
                        ("Zusammenfassung: Ablehnung", summary["disagree"], summary["disagree_pct"]),
                        ("Zusammenfassung: Enthaltung", summary["abstentions"], ""),
                    ):
                        writer.writerow(base + [label, "", count, "", "", pct])
    response = HttpResponse(
        "\ufeff" + buffer.getvalue(), content_type="text/csv; charset=utf-8"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="abstimmbar-ergebnisse-{question_set.pk}.csv"'
    )
    return response


# --- SSE stream (the only async view; ADR-0003) ------------------------------


async def stream(request, code):
    # ORM access goes through sync_to_async, and the connection is returned
    # to the pool immediately: a stream lives for minutes — it must not keep
    # a pooled DB connection checked out while idle (request_finished, which
    # normally closes it, only fires once the stream ends).
    def _context():
        try:
            room = Room.objects.filter(code=code).first()
            is_owner = room is not None and _require_owner(request.user, room)
            return room, is_owner
        finally:
            connections.close_all()

    room, is_owner = await sync_to_async(_context)()
    if room is None:
        raise Http404

    role = "participant"
    if request.GET.get("role") == "presenter":
        if not is_owner:
            return JsonResponse({"detail": "Forbidden"}, status=403)
        role = "presenter"

    subscriber = hub.subscribe(room.pk, role)
    # Joining/leaving changes the participant counter on the beamer.
    if role == "participant":
        broadcast(room, debounce=True)

    def _initial():
        try:
            return build_payloads(room)
        finally:
            connections.close_all()

    async def events():
        try:
            initial = await sync_to_async(_initial)()
            yield sse_frame(initial[role])
            while True:
                try:
                    # Queue items are pre-serialized SSE frames (see hub).
                    yield await asyncio.wait_for(
                        subscriber.queue.get(), timeout=KEEPALIVE_SECONDS
                    )
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            hub.unsubscribe(room.pk, subscriber)
            if role == "participant":
                broadcast(room, debounce=True)

    response = StreamingHttpResponse(events(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
