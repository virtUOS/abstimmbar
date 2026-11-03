# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .live import manager_stream
from .views import (
    CommitteeGroupViewSet,
    CommitteeMemberViewSet,
    GroupTemplateViewSet,
    MeetingViewSet,
)

router = DefaultRouter()
router.register("committee-templates", GroupTemplateViewSet, basename="committee-template")
router.register("committee-groups", CommitteeGroupViewSet, basename="committee-group")
router.register("committee-members", CommitteeMemberViewSet, basename="committee-member")



def _meeting(name, actions, suffix=""):
    return path(
        f"meetings/<int:pk>/{suffix}", MeetingViewSet.as_view(actions),
        name=f"meeting-{name}",
    )


urlpatterns = [
    path("", include(router.urls)),
    path("meetings/<int:pk>/stream/", manager_stream, name="meeting-stream"),
    _meeting("detail", {"get": "retrieve"}),
    _meeting("start", {"post": "start"}, "start/"),
    _meeting("end", {"post": "end"}, "end/"),
    _meeting("invites", {"post": "invites"}, "invites/"),
    _meeting("invites-csv", {"get": "invites_csv"}, "invites.csv"),
    _meeting("invite-remove", {"post": "remove_invite"}, "invites/<int:invite_id>/remove/"),
    _meeting("invite-readmit", {"post": "readmit_invite"}, "invites/<int:invite_id>/readmit/"),
    _meeting("substitution-suggest", {"get": "suggest"}, "substitutions/suggest/"),
    _meeting("substitutions", {"post": "substitutions"}, "substitutions/"),
    _meeting(
        "substitution-detail", {"delete": "delete_substitution"},
        "substitutions/<int:sub_id>/",
    ),
]
