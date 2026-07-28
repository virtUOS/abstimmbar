# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Shared logic for the one-off migration that restores the invariant
'a room's owner is always among its owners' (broken by legacy backfill in
0018_room_owner). Idempotent: only adds missing memberships."""


def ensure_owner_membership(Room):
    """Add each room's ``owner`` to its ``owners`` M2M where missing.
    Returns the number of rooms fixed. Works with both the real model and a
    historical (migration ``apps.get_model``) model."""
    fixed = 0
    for room in Room.objects.exclude(owner=None).iterator():
        if not room.owners.filter(pk=room.owner_id).exists():
            room.owners.add(room.owner_id)
            fixed += 1
    return fixed
