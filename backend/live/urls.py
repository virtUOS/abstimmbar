# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.urls import path

from . import views

# API routes (mounted under /api/ in config.urls).
api_urlpatterns = [
    path("live/rooms/<str:code>/join/", views.join),
    path("live/rooms/<str:code>/vote/", views.vote),
    path("live/rooms/<str:code>/retract/", views.retract),
    path("live/rooms/<str:code>/quiz/", views.quiz),
    path("live/rooms/<str:code>/stream/", views.stream),
    # Recording mode (#53): async viewer voting, keyed by the run's token.
    path("live/recording/<str:token>/", views.recording_questions),
    path("live/recording/<str:token>/vote/", views.recording_vote),
    path("question-sets/<int:set_id>/live-status/", views.live_status),
    path("question-sets/<int:set_id>/start-run/", views.start_run),
    path("question-sets/<int:set_id>/results/", views.set_results),
    path("question-sets/<int:set_id>/results.csv", views.results_csv),
    path("question-sets/<int:set_id>/delete-results/", views.delete_results),
    path("question-sets/<int:set_id>/archive-results/", views.archive_results),
    path("runs/<int:run_id>/control/", views.control_run),
    path("runs/<int:run_id>/ai-summary/", views.run_summary),
    path("runs/<int:run_id>/wordcloud-ai/", views.wordcloud_ai),
    path(
        "runs/<int:run_id>/questions/<int:question_id>/ai-wordcloud/",
        views.optimize_wordcloud,
    ),
    path(
        "runs/<int:run_id>/questions/<int:question_id>/ai-freetext/",
        views.evaluate_freetext,
    ),
    path("runs/<int:run_id>/", views.delete_run),
]

# Participant-facing pages (mounted at the site root).
page_urlpatterns = [
    path("p/", views.participant_home, name="participant-home"),
    path("p/<str:code>/", views.participant_page, name="participant-page"),
    # Deliberately OUTSIDE "/p/" so basicbar_lti's frame-ancestors middleware
    # leaves its framing headers alone (#74; the view sets its own CSP).
    path(
        "question-preview/<int:question_id>/",
        views.question_preview,
        name="question-preview",
    ),
    path("p/<str:code>/qr.png", views.room_qr, name="room-qr"),
    # Recording mode (#53): the viewer page + per-question QR.
    path("r/<str:token>/", views.recording_page, name="recording-page"),
    path("r/<str:token>/qr.png", views.recording_qr, name="recording-qr"),
]
