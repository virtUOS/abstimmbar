# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CommitteeGroupViewSet, CommitteeMemberViewSet, GroupTemplateViewSet

router = DefaultRouter()
router.register("committee-templates", GroupTemplateViewSet, basename="committee-template")
router.register("committee-groups", CommitteeGroupViewSet, basename="committee-group")
router.register("committee-members", CommitteeMemberViewSet, basename="committee-member")

urlpatterns = [path("", include(router.urls))]
