# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Every committee room gets exactly one observer group on creation; a
deleted meeting leaves its seal links as placeholders."""
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.utils import timezone

from rooms.models import QuestionSet, Room

from .models import CommitteeGroup, SealLink


@receiver(post_save, sender=Room)
def create_observer_group(sender, instance, created, **kwargs):
    if created and instance.kind == Room.Kind.COMMITTEE:
        CommitteeGroup.objects.create(
            room=instance, is_observer=True,
            name_de="Beobachtende", name_en="Observers", position=999,
        )


@receiver(pre_delete, sender=QuestionSet)
def keep_seal_placeholders(sender, instance, **kwargs):
    if instance.type == QuestionSet.SetType.MEETING:
        SealLink.objects.filter(meeting_id=instance.pk).update(
            deleted_at=timezone.now(), ballot=None,
        )
