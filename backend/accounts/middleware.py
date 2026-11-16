# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Signed-in users' stored UI language for the management API (#300)."""
from django.conf import settings
from django.utils import translation
from django.utils.deprecation import MiddlewareMixin

# Participant-facing API (participant, recording and self-check pages): these
# follow the participant page's own language choice (?lang=, cookie,
# Accept-Language), even when a teacher is signed in in the same browser.
PARTICIPANT_API_PREFIX = "/api/live/"


class UserLanguageMiddleware(MiddlewareMixin):
    """Activate ``User.language`` for authenticated management API requests.

    LocaleMiddleware resolves the language from the ``django_language``
    cookie, which the participant page sets; without this, opening the
    participant page in English switched the teacher's server-side strings
    (errors, search results, …) to English too. Must come after
    AuthenticationMiddleware (and LocaleMiddleware). MiddlewareMixin keeps it
    async-capable, so the SSE stream stays a native async view.
    """

    def process_request(self, request):
        path = request.path_info
        if not path.startswith("/api/") or path.startswith(PARTICIPANT_API_PREFIX):
            return
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return
        language = getattr(user, "language", "")
        if language in dict(settings.LANGUAGES):
            translation.activate(language)
            request.LANGUAGE_CODE = language
