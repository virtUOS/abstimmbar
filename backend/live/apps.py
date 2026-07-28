# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.apps import AppConfig


class LiveConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "live"
