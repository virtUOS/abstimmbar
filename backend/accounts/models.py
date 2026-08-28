# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""User accounts.

Only room creators (lecturers, staff, students running their own polls) have
accounts — participants stay anonymous by design (concept §9) and never get a
``User`` record. Roles (ADR to follow with the rooms app): admin via
``is_staff``/``is_superuser``; anyone authenticated may create rooms
(review decision, July 2026), restrictable later via claims/groups.
"""
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Application user, provisioned just-in-time on first OIDC login."""

    # OIDC subject identifier (stable, unique per identity provider).
    subject = models.CharField(max_length=255, unique=True, null=True, blank=True)
    # Snapshot of the OIDC claims from the last login; basis for later
    # claim-based restrictions on room creation (concept §8.2).
    claims = models.JSONField(default=dict, blank=True)
    # Preferred UI language ("en"/"de"), set from the SPA; blank = site default.
    language = models.CharField(max_length=10, blank=True)
    # Easy/Pro UI mode (#52). None = not chosen yet → role default (see
    # effective_easy_mode): non-staff start simple, staff start pro. An
    # explicit True/False (set via /api/whoami/mode/) overrides the default.
    easy_mode = models.BooleanField(null=True, blank=True, default=None)
    # Onboarding (#78): has this user already received the seeded example
    # room? default=False so existing users get it too, on their next
    # whoami — see accounts.views.whoami and rooms.onboarding.
    onboarded = models.BooleanField(default=False)

    def __str__(self):
        return self.get_username()

    @property
    def effective_easy_mode(self) -> bool:
        """Resolved Easy/Pro mode: explicit choice, else role default
        (non-staff = simple/True, staff = pro/False)."""
        if self.easy_mode is not None:
            return self.easy_mode
        return not self.is_staff
