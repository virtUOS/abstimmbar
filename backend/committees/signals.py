# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Every committee room gets exactly one observer group on creation."""
from django.db.models.signals import post_save
from django.dispatch import receiver

from rooms.models import Room

from .models import CommitteeGroup


@receiver(post_save, sender=Room)
def create_observer_group(sender, instance, created, **kwargs):
    if created and instance.kind == Room.Kind.COMMITTEE:
        CommitteeGroup.objects.create(
            room=instance, is_observer=True,
            name_de="Beobachtende", name_en="Observers", position=999,
        )
