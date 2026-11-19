# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Per-user rate limits for the AI endpoints (#343).

Two scopes, rates in ``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`` (env
``AI_THROTTLE_RATE`` / ``AI_VISION_THROTTLE_RATE``): ``ai`` for every text
AI call, ``ai_vision`` for the alt-text suggestion. The value ``off``
disables a scope, staff are never throttled. DRF runs throttles in
``initial()``, i.e. before the handler (and so before the model) is reached.
"""
import logging
import math

from django.utils.translation import ngettext
from rest_framework.exceptions import Throttled
from rest_framework.settings import api_settings
from rest_framework.throttling import SimpleRateThrottle

logger = logging.getLogger("abstimmbar.ai")


_DEFAULTS = {"ai": "120/hour", "ai_vision": "30/hour"}
_warned: set[str] = set()


class _AIThrottle(SimpleRateThrottle):
    scope = ""

    def get_rate(self):
        # Read lazily (not DRF's import-time class attribute) so the rates
        # can be overridden in tests.
        rate = api_settings.DEFAULT_THROTTLE_RATES.get(self.scope)
        if not rate or str(rate).strip().lower() == "off":
            return None
        try:
            self.parse_rate(rate)  # DRF semantics: "N/second|minute|hour|day"
        except (ValueError, KeyError, TypeError, AttributeError):
            default = _DEFAULTS[self.scope]
            if rate not in _warned:
                _warned.add(rate)
                logger.warning(
                    "Invalid rate %r for AI throttle scope %s, using %s",
                    rate, self.scope, default,
                )
            return default
        return rate

    def get_cache_key(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return None  # never reached: the endpoints require a login
        return self.cache_format % {"scope": self.scope, "ident": user.pk}

    def allow_request(self, request, view):
        if getattr(request.user, "is_staff", False):
            return True
        if super().allow_request(request, view):
            return True
        logger.warning("AI throttled scope=%s user=%s", self.scope, request.user.pk)
        wait = self.wait()
        minutes = max(1, math.ceil(wait / 60)) if wait else 1
        detail = ngettext(
            "You have used the AI very often just now. "
            "Please try again in %(minutes)s minute.",
            "You have used the AI very often just now. "
            "Please try again in %(minutes)s minutes.",
            minutes,
        ) % {"minutes": minutes}
        # wait=None: DRF would otherwise append its own "available in N seconds"
        # sentence to the detail; Retry-After is taken from ``exc.wait``.
        exc = Throttled(detail=detail)
        exc.wait = math.ceil(wait) if wait else None
        raise exc


class AIThrottle(_AIThrottle):
    scope = "ai"


class AIVisionThrottle(_AIThrottle):
    scope = "ai_vision"
