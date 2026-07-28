# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("platforms", views.LtiPlatformViewSet, basename="lti-platform")

urlpatterns = [
    path("tool-info/", views.LtiToolInfoView.as_view(), name="lti-tool-info"),
    *router.urls,
]
