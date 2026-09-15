# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Project-local OIDC callback that tolerates a replayed/stale callback.

mozilla-django-oidc's callback view raises ``SuspiciousOperation`` when it
receives a ``code``/``state`` whose ``state`` is no longer in the session's
``oidc_states`` (already consumed). That is exactly what a browser *Back* press
right after login does — it re-requests ``/oidc/callback/?code=…&state=…`` with
the now-spent state — and it surfaces to the user as a 400 error page.

We catch that one case and redirect to the SPA instead. The parent view raises
*before* authenticating, so the replay never logs anyone in; this only turns an
ugly error page into a friendly redirect, it does not weaken the state check.
Every other outcome (real provider ``error``, unusable token) already goes
through the parent's ``login_failure`` redirect, so we leave those untouched.
"""
from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.http import HttpResponseRedirect
from mozilla_django_oidc.views import OIDCAuthenticationCallbackView


class SafeOIDCCallbackView(OIDCAuthenticationCallbackView):
    def get(self, request):
        try:
            return super().get(request)
        except SuspiciousOperation:
            # Stale/replayed callback (e.g. Back after login): send them to the
            # app. A still-valid session lands logged in; otherwise the SPA
            # shows the landing page.
            return HttpResponseRedirect(settings.LOGIN_REDIRECT_URL)
