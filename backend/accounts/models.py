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
    # Guided-tour onboarding: has the user seen or dismissed the first-login
    # tour offer? Separate from ``onboarded`` (which fires on the first whoami
    # to seed the example room and is thus always true by the time the UI
    # renders). default=False so existing users get the tour offer once.
    onboarding_tour_seen = models.BooleanField(default=False)

    def __str__(self):
        return self.get_username()

    @property
    def effective_easy_mode(self) -> bool:
        """Resolved Easy/Pro mode: explicit choice, else role default
        (non-staff = simple/True, staff = pro/False)."""
        if self.easy_mode is not None:
            return self.easy_mode
        return not self.is_staff


class DailyModeSession(models.Model):
    """One row per browser session per day, tagged with the effective Easy/Pro
    mode — for the "sessions per day by mode" statistic. Stores no user
    reference and only a one-way SHA-256 hash of the session key (never the
    raw key itself), so this stats table can never be used to re-authenticate
    a live session. Uniqueness on (session_hash, date) is all the statistic
    needs; see the ``prune_mode_sessions`` command for retention."""
    session_hash = models.CharField(max_length=64)  # sha256 hexdigest
    date = models.DateField()
    mode = models.CharField(max_length=4)  # "easy" | "pro"

    class Meta:
        unique_together = (("session_hash", "date"),)


class TourEvent(models.Model):
    """One guided-tour event for the admin statistics: started (with where it
    was started from), completed, or aborted (with the step id it was ended
    on). Anonymous by design — no user or session reference, only the mode —
    so it is not personal data. Counting starts with its deployment."""

    class Kind(models.TextChoices):
        STARTED = "started", "Started"
        COMPLETED = "completed", "Completed"
        ABORTED = "aborted", "Aborted"

    class Source(models.TextChoices):
        WELCOME = "welcome", "Welcome dialog"
        HELP = "help", "Help menu"

    kind = models.CharField(max_length=10, choices=Kind.choices)
    mode = models.CharField(max_length=4)  # "easy" | "pro"
    source = models.CharField(max_length=10, choices=Source.choices, blank=True)
    step = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
