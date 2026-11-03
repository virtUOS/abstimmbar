# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Committee helpers: room access, template application, member-list parsing."""
import re

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Q

from rooms.models import Room

from .models import CommitteeGroup, GroupTemplate

_NAME_EMAIL = re.compile(r"^(?P<name>.*?)\s*<(?P<email>[^<>]*)>$")
_SPLIT = re.compile(r"[\n\r,;]")


def managed_committee_rooms(user):
    """Committee rooms the user manages (owner/co-owner; staff: all)."""
    rooms = Room.objects.filter(kind=Room.Kind.COMMITTEE)
    if user.is_staff:
        return rooms
    return rooms.filter(Q(owners=user) | Q(owner=user)).distinct()


@transaction.atomic
def apply_template(room: Room, template: GroupTemplate) -> list[CommitteeGroup]:
    if room.committee_groups.filter(is_observer=False).exists():
        raise ValidationError("Groups already exist.")
    created = []
    for position, name in enumerate(template.groups, start=1):
        created.append(CommitteeGroup.objects.create(
            room=room, position=position,
            name_de=(name.get("de") or "").strip() or None,
            name_en=(name.get("en") or "").strip() or None,
        ))
    return created


def parse_member_list(text: str) -> tuple[list[tuple[str, str]], list[dict]]:
    """Parse pasted members: separators newline/comma/semicolon, formats
    ``Name <mail>`` and ``mail`` (name = part before the @). Empty segments
    are dropped silently."""
    entries: list[tuple[str, str]] = []
    skipped: list[dict] = []
    seen: set[str] = set()
    for segment in _SPLIT.split(text or ""):
        segment = segment.strip()
        if not segment:
            continue
        match = _NAME_EMAIL.match(segment)
        if match:
            name, email = match.group("name").strip(), match.group("email").strip()
        else:
            name, email = "", segment
        try:
            validate_email(email)
        except ValidationError:
            skipped.append({"line": segment, "reason": "invalid_email"})
            continue
        key = email.lower()
        if key in seen:
            skipped.append({"line": segment, "reason": "duplicate"})
            continue
        seen.add(key)
        entries.append((name or email.split("@", 1)[0], email))
    return entries, skipped
