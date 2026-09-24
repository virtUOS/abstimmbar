# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Root URL configuration."""
from basicbar_auth.oidc import SilentLoginView, backchannel_logout
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from accounts.oidc import SafeOIDCCallbackView
from accounts.views import (
    ensure_example_room,
    logout_view,
    record_tour_event,
    set_language,
    set_mode,
    set_tour_seen,
    whoami,
)
from common.views import MetricsView
from live.urls import api_urlpatterns as live_api
from live.urls import page_urlpatterns as live_pages
from lti.api_urls import urlpatterns as lti_api

urlpatterns = [
    path("admin/", admin.site.urls),
    # Top-level, not under /api/ — a Prometheus scrape target, not an app API
    # route. Token-guarded inside the view itself (see MetricsView).
    path("metrics", MetricsView.as_view()),
    path("oidc/logout-redirect/", logout_view, name="spa-logout"),
    path("oidc/silent/", SilentLoginView.as_view(), name="oidc-silent"),
    path(
        "oidc/backchannel-logout/",
        backchannel_logout,
        name="oidc-backchannel-logout",
    ),
    # Override the callback before mozilla's include: a Back press after login
    # replays the spent code/state, which mozilla raises SuspiciousOperation for
    # (a 400 page); redirect to the SPA instead. Same name so reverse() is stable.
    path(
        "oidc/callback/",
        SafeOIDCCallbackView.as_view(),
        name="oidc_authentication_callback",
    ),
    path("oidc/", include("mozilla_django_oidc.urls")),
    path("api/whoami/", whoami),
    path("api/whoami/language/", set_language),
    path("api/whoami/mode/", set_mode),
    path("api/whoami/tour-seen/", set_tour_seen),
    path("api/whoami/tour-event/", record_tour_event),
    path("api/whoami/example-room/", ensure_example_room),
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
