# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from typing import ClassVar

from django.contrib import admin

from .models import AnswerOption, Question, QuestionSet, Room, Section, UploadedImage


class QuestionSetInline(admin.TabularInline):
    model = QuestionSet
    extra = 0


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("title", "code", "updated_at")
    search_fields = ("title", "code")
    inlines: ClassVar = [QuestionSetInline]


class AnswerOptionInline(admin.TabularInline):
    model = AnswerOption
    extra = 0


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ("__str__", "question_set", "kind", "position")
    list_filter = ("kind",)
    inlines: ClassVar = [AnswerOptionInline]


admin.site.register(QuestionSet)
admin.site.register(Section)
admin.site.register(UploadedImage)
