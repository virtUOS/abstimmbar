# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
from django.urls import path

from .views import entry_page

urlpatterns = [
    path("g/<str:token>/", entry_page, name="committee-entry"),
]
