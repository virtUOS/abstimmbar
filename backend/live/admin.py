# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.contrib import admin

from .models import ParticipantToken, Run, Vote


@admin.register(Run)
class RunAdmin(admin.ModelAdmin):
    list_display = ("__str__", "phase", "active_question", "created_at", "ended_at")
    list_filter = ("phase",)


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ("run", "question", "text", "created_at")


admin.site.register(ParticipantToken)
