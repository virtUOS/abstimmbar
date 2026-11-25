# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from basicbar_lti.views import lti_jwks, lti_login, lti_register
from django.urls import path

from . import views

urlpatterns = [
    path("lti/login/", lti_login, name="lti-login"),
    path("lti/register/", lti_register, name="lti-register"),
    path("lti/launch/", views.lti_launch, name="lti-launch"),
    path("lti/jwks/", lti_jwks, name="lti-jwks"),
    path("lti/icon.svg", views.lti_icon, name="lti-icon"),
    path("lti/deep-link/", views.deep_link_respond, name="lti-deep-link"),
]
