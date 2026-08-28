# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Session/identity endpoints for the SPA."""
import json
import logging

from basicbar_auth.oidc import provider_logout_url
from basicbar_integrations import ai, translation_service
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth import logout as django_logout
from django.db import transaction
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from rooms.onboarding import seed_example_room

User = get_user_model()
logger = logging.getLogger(__name__)


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
            "csrf_token": csrf_token,
            "ai_enabled": ai.is_enabled(),
            "content_default_language": content_default_language,
            "content_translation_enabled": content_translation_enabled,
        }
    )


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
