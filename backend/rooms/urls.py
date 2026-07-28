# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ImageUploadView,
    QuestionSetViewSet,
    QuestionViewSet,
    RoomViewSet,
    SearchView,
    SectionViewSet,
    SharedSetCopyView,
    SharedSetView,
)

router = DefaultRouter()
router.register("rooms", RoomViewSet, basename="room")
router.register("question-sets", QuestionSetViewSet, basename="questionset")
router.register("questions", QuestionViewSet, basename="question")
router.register("sections", SectionViewSet, basename="section")

urlpatterns = [
    path("search/", SearchView.as_view()),
    path("images/", ImageUploadView.as_view()),
    path("shared/<str:token>/", SharedSetView.as_view()),
    path("shared/<str:token>/copy/", SharedSetCopyView.as_view()),
    path("", include(router.urls)),
]
