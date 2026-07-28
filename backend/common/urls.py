# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from basicbar_integrations.views import TranslateView
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    DataCollectionView,
    FooterPagesView,
    ManagePageViewSet,
    PageDetailView,
    SiteLogoView,
    SiteManageView,
    SiteView,
)

router = DefaultRouter()
router.register("manage/pages", ManagePageViewSet, basename="manage-page")

urlpatterns = [
    path("site/", SiteView.as_view()),
    path("data-collection/", DataCollectionView.as_view()),
    path("pages/", FooterPagesView.as_view()),
    path("pages/<slug:slug>/", PageDetailView.as_view()),
    path("manage/site/", SiteManageView.as_view()),
    path("manage/site/logo/", SiteLogoView.as_view()),
    path("translate/", TranslateView.as_view()),
    path("", include(router.urls)),
]
