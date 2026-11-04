# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
from django.urls import path

from .live import member_stream
from .views import ballot_preview, entry_page, me, vote

urlpatterns = [
    path("g/preview/<int:question_id>/", ballot_preview, name="committee-ballot-preview"),
    path("g/<str:token>/", entry_page, name="committee-entry"),
    path("g/<str:token>/stream/", member_stream, name="committee-stream"),
    path("g/<str:token>/me/", me, name="committee-me"),
    path("g/<str:token>/vote/", vote, name="committee-vote"),
]
