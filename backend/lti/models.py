# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Abstimmbars LTI-Fachmodell: LMS-Kurskontext ↔ Raum.

Plattform-Registrierung, Tool-Key und User-Links kommen aus basicbar-lti;
hier lebt nur, worauf ein Kurskontext in diesem Tool abbildet.
"""
from typing import ClassVar

from basicbar_lti.models import LtiPlatform
from django.db import models

from common.models import TimeStampedModel


class LtiContextLink(TimeStampedModel):
    """LMS course context ↔ room (created on first instructor launch)."""

    platform = models.ForeignKey(
        LtiPlatform, on_delete=models.CASCADE, related_name="context_links"
    )
    context_id = models.CharField(max_length=255)
    room = models.ForeignKey(
        "rooms.Room", on_delete=models.CASCADE, related_name="lti_links"
    )

    class Meta:
        constraints: ClassVar = [
            models.UniqueConstraint(
                fields=["platform", "context_id"], name="one_room_per_context"
            )
        ]

    def __str__(self):
        return f"{self.platform.name}:{self.context_id} → {self.room}"
