# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Root URL configuration."""
from basicbar_auth.oidc import SilentLoginView, backchannel_logout
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from accounts.views import logout_view, set_language, set_mode, whoami
from live.urls import api_urlpatterns as live_api
from live.urls import page_urlpatterns as live_pages
from lti.api_urls import urlpatterns as lti_api

urlpatterns = [
    path("admin/", admin.site.urls),
    path("oidc/logout-redirect/", logout_view, name="spa-logout"),
    path("oidc/silent/", SilentLoginView.as_view(), name="oidc-silent"),
    path(
        "oidc/backchannel-logout/",
        backchannel_logout,
        name="oidc-backchannel-logout",
    ),
    path("oidc/", include("mozilla_django_oidc.urls")),
    path("api/whoami/", whoami),
    path("api/whoami/language/", set_language),
    path("api/whoami/mode/", set_mode),
    path("api/", include((live_api, "live"))),
    path("api/", include("rooms.urls")),
    path("api/", include("common.urls")),
    path("api/lti/", include((lti_api, "lti-api"))),
    path("", include("lti.urls")),
    *live_pages,
]

# Serve uploaded media and static files during local development. (Static
# needs explicit wiring because we run uvicorn, not `manage.py runserver`.)
if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
