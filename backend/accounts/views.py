# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Session/identity endpoints for the SPA."""
import json
import logging
import re

from basicbar_auth.oidc import provider_logout_url
from basicbar_integrations import ai, translation_service
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth import logout as django_logout
from django.db import IntegrityError, transaction
from django.db.models import F
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from rooms.onboarding import seed_example_room

from .models import TourDailyCount

User = get_user_model()
logger = logging.getLogger(__name__)


def _example_ids(user):
    """(room_id, set_id) of the user's complete example room, else (None, None).
    Complete = owned is_example room whose first set has >= 1 question."""
    from rooms.models import QuestionSet, Room
    room = Room.objects.filter(owner=user, is_example=True).order_by("-id").first()
    if not room:
        return None, None
    qs = QuestionSet.objects.filter(room=room).order_by("id").first()
    if not qs or not qs.questions.exists():
        return None, None
    return room.id, qs.id


def whoami(request):
    """Return the current session user (for the SPA to check login state).

    Also returns the CSRF token in the body: ``get_token`` sets the cookie
    *and* hands the SPA an authoritative token, so unsafe requests work even
    cross-origin in dev, where reading the cookie from JavaScript can be
    unreliable (production is same-origin behind Caddy)."""
    csrf_token = get_token(request)
    user = request.user
    # Content-i18n config (#33 MR2): the default/canonical authoring language
    # and whether machine-translation drafts are available, so the SPA can
    # decide which language to show/edit without a second round-trip.
    content_default_language = settings.MODELTRANSLATION_DEFAULT_LANGUAGE
    content_translation_enabled = translation_service.is_enabled()
    if not user.is_authenticated:
        return JsonResponse(
            {
                "authenticated": False,
                "csrf_token": csrf_token,
                "ai_enabled": ai.is_enabled(),
                "content_default_language": content_default_language,
                "content_translation_enabled": content_translation_enabled,
            }
        )
    # Onboarding (#78): seed a ready-made example room exactly once per
    # user (also catches pre-existing accounts, whose onboarded defaults to
    # False). select_for_update + a second read under the lock makes this
    # race-safe against concurrent first requests from the same user.
    # whoami is the app's load-time check, so a seeding failure must never
    # break it — log and carry on (onboarded stays False, so it retries).
    if not user.onboarded:
        try:
            with transaction.atomic():
                locked = User.objects.select_for_update().get(pk=user.pk)
                if not locked.onboarded:
                    seed_example_room(locked)
                    locked.onboarded = True
                    locked.save(update_fields=["onboarded"])
            user.refresh_from_db()
        except Exception:
            logger.exception("Onboarding seed failed for user %s", user.pk)
    _record_mode_session(request, user)
    ex_room, ex_set = _example_ids(user)
    return JsonResponse(
        {
            "authenticated": True,
            "username": user.get_username(),
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "subject": user.subject,
            "is_staff": user.is_staff,
            "language": user.language,
            # Effective Easy/Pro mode: explicit choice, else role default
            # (non-staff = simple, staff = pro) — see User.effective_easy_mode.
            "easy_mode": user.effective_easy_mode,
            "onboarding_tour_seen": user.onboarding_tour_seen,
            "csrf_token": csrf_token,
            "ai_enabled": ai.is_enabled(),
            "ai_generate_max_questions": settings.AI_GEN_MAX_QUESTIONS,
            "content_default_language": content_default_language,
            "content_translation_enabled": content_translation_enabled,
            "example_room_id": ex_room,
            "example_set_id": ex_set,
        }
    )


def _record_mode_session(request, user):
    """Record one DailyModeSession row per browser session per day, tagged
    with the caller's effective Easy/Pro mode — feeds the "sessions per day
    by mode" admin statistic. Best-effort: whoami must never break because
    of this."""
    try:
        key = request.session.session_key
        if not key:
            return
        import hashlib

        from django.utils import timezone

        from .models import DailyModeSession

        # Store only a one-way hash: the raw key is a live session credential,
        # and this stats table must never be able to re-authenticate a session
        # (participant anonymity / least-privilege, see CLAUDE.md). The hash is
        # still stable per session, so (hash, date) keeps the per-day count.
        session_hash = hashlib.sha256(key.encode()).hexdigest()
        DailyModeSession.objects.update_or_create(
            session_hash=session_hash,
            date=timezone.localdate(),
            defaults={"mode": "easy" if user.effective_easy_mode else "pro"},
        )
    except Exception:
        logger.exception("Failed to record mode session")


def logout_view(request):
    """Log out of Django and (if logged in via OIDC) the identity provider.

    GET-friendly so the SPA can trigger it with a plain redirect.
    """
    was_authenticated = request.user.is_authenticated
    end_session_url = None
    if was_authenticated and settings.OIDC_OP_LOGOUT_ENDPOINT:
        end_session_url = provider_logout_url(request)
    django_logout(request)
    return redirect(end_session_url or settings.LOGOUT_REDIRECT_URL)


@require_POST
def set_language(request):
    """POST /api/whoami/language/ {language} — remember the user's UI language.

    Plain Django view (matches ``whoami``); the SPA sends its CSRF token from
    ``whoami`` so the request passes CSRF as elsewhere.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Not authenticated."}, status=403)
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        data = {}
    raw = data.get("language") if isinstance(data, dict) else ""
    language = (str(raw) if raw else "").strip()
    if language not in dict(settings.LANGUAGES):
        return JsonResponse({"detail": "Unsupported language."}, status=400)
    request.user.language = language
    request.user.save(update_fields=["language"])
    return JsonResponse({"language": language})


@require_POST
def set_mode(request):
    """POST /api/whoami/mode/ {easy_mode} — toggle the user's Easy/Pro mode.

    Plain Django view (matches ``set_language``). Stores an explicit
    True/False choice (overriding the role default), even for staff —
    admins default to Pro but may opt into simple mode just like anyone
    else. Returns the *effective* value (see ``User.effective_easy_mode``).
    """
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Not authenticated."}, status=403)
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        data = {}
    easy = bool(data.get("easy_mode")) if isinstance(data, dict) else False
    request.user.easy_mode = easy
    request.user.save(update_fields=["easy_mode"])
    return JsonResponse({"easy_mode": request.user.effective_easy_mode})


@require_POST
def set_tour_seen(request):
    """POST /api/whoami/tour-seen/ — mark the first-login guided tour as seen
    or dismissed (idempotent). Plain Django view, matching ``set_mode``."""
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Not authenticated."}, status=403)
    if not request.user.onboarding_tour_seen:
        request.user.onboarding_tour_seen = True
        request.user.save(update_fields=["onboarding_tour_seen"])
    return JsonResponse({"onboarding_tour_seen": True})


# Tour step ids are short dotted slugs (e.g. "q.word_cloud", "example.restore").
TOUR_STEP_RE = re.compile(r"^[a-z0-9_.-]{1,60}$")


@require_POST
def record_tour_event(request):
    """POST /api/whoami/tour-event/ — count one anonymous guided-tour event
    for the admin statistics: {"kind": "started"|"completed"|"aborted",
    "mode": "easy"|"pro", "source": "welcome"|"help" (started only),
    "step": "<step id>" (aborted only)}. Fields that don't belong to the kind
    are dropped. The event only increments today's ``TourDailyCount`` bucket
    (no per-event row, no timestamp). Plain Django view, matching
    ``set_tour_seen``."""
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Not authenticated."}, status=403)
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return JsonResponse({"detail": "Invalid JSON."}, status=400)
    kind, mode = data.get("kind"), data.get("mode")
    if kind not in TourDailyCount.Kind.values or mode not in ("easy", "pro"):
        return JsonResponse({"detail": "Invalid kind or mode."}, status=400)
    source = step = ""
    if kind == TourDailyCount.Kind.STARTED:
        source = data.get("source")
        if source not in TourDailyCount.Source.values:
            return JsonResponse({"detail": "Invalid source."}, status=400)
    elif kind == TourDailyCount.Kind.ABORTED:
        step = data.get("step")
        if not isinstance(step, str) or not TOUR_STEP_RE.match(step):
            return JsonResponse({"detail": "Invalid step."}, status=400)
    bucket = {"date": timezone.localdate(), "kind": kind, "mode": mode, "source": source, "step": step}
    counts = TourDailyCount.objects.filter(**bucket)
    if not counts.update(n=F("n") + 1):
        try:
            with transaction.atomic():
                TourDailyCount.objects.create(**bucket, n=1)
        except IntegrityError:  # created concurrently — count on the winner's row
            counts.update(n=F("n") + 1)
    return JsonResponse({"status": "ok"}, status=201)


@require_POST
def ensure_example_room(request):
    """POST /api/whoami/example-room/ — return the user's example room/set ids,
    (re)creating the example room via the onboarding seeder when missing or
    incomplete. Idempotent. Plain Django view, matching ``set_mode``."""
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Not authenticated."}, status=403)
    room_id, set_id = _example_ids(request.user)
    if room_id is None:
        # Guard against two near-simultaneous POSTs (double-click / retry)
        # both seeing (None, None) and each creating an example room — same
        # race whoami guards above with select_for_update + a re-check under
        # the lock.
        with transaction.atomic():
            locked = User.objects.select_for_update().get(pk=request.user.pk)
            room_id, set_id = _example_ids(locked)
            if room_id is None:
                seed_example_room(locked)
                room_id, set_id = _example_ids(locked)
    return JsonResponse({"example_room_id": room_id, "example_set_id": set_id})
