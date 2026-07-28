# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Abstimmbars LTI-Launch: Kurskontext → Raum (concept §8.1).

Die generische LTI-Machinerie (Registrierung, Handshake, Provisionierung)
kommt aus basicbar-lti; hier lebt, was ein Launch in DIESEM Tool bedeutet:
an instructor launch links the LMS course context to a room (created on
first launch) and lands in the management SPA; a learner launch redirects
to the anonymous participant page — LTI learners are not provisioned as
users (anonymity by design stays intact). Deep linking lets the instructor
pick or create a question set from within the LMS.
"""
import logging
from typing import ClassVar

from basicbar_lti.provisioning import (
    CLAIM,
    is_instructor,
    launch_storage,
    platform_for,
    provision_user,
)
from basicbar_lti.tool_conf import build_tool_conf
from basicbar_lti.views import LtiPlatformViewSet as BaseLtiPlatformViewSet
from basicbar_lti.views import LtiToolInfoView as BaseLtiToolInfoView
from django.conf import settings
from django.contrib.auth import login
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from pylti1p3.contrib.django import DjangoMessageLaunch
from pylti1p3.deep_link_resource import DeepLinkResource

from accounts.permissions import IsAdmin
from rooms.models import QuestionSet, Room

from .models import LtiContextLink

logger = logging.getLogger(__name__)


def _ensure_room(platform, launch_data, user):
    """Course context ↔ room link; the room is created on first launch."""
    context = launch_data.get(f"{CLAIM}context") or {}
    context_id = str(context.get("id") or "")
    if not context_id:
        return None
    link = (
        LtiContextLink.objects.filter(platform=platform, context_id=context_id)
        .select_related("room")
        .first()
    )
    if link is None:
        room = Room.objects.create(
            title=(context.get("title") or f"LTI-Kurs {context_id}")[:200]
        )
        link = LtiContextLink.objects.create(
            platform=platform, context_id=context_id, room=room
        )
    if user is not None:
        link.room.owners.add(user)
    return link.room


@csrf_exempt
def lti_launch(request):
    """Message launch: resource link or deep-linking request."""
    message_launch = DjangoMessageLaunch(
        request, build_tool_conf(), launch_data_storage=launch_storage()
    )
    launch_data = message_launch.get_launch_data()
    platform = platform_for(launch_data)
    if platform is None:
        return render(request, "lti/error.html",
                      {"message": "Unbekannte Plattform-Registrierung."}, status=403)

    instructor = is_instructor(launch_data)

    if message_launch.is_deep_link_launch():
        if not instructor:
            return render(request, "lti/error.html",
                          {"message": "Nur Lehrende können Inhalte einbinden."}, status=403)
        user = provision_user(platform, launch_data)
        room = _ensure_room(platform, launch_data, user)
        if room is None:
            return render(request, "lti/error.html",
                          {"message": "Der Launch enthält keinen Kurskontext."}, status=400)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return render(
            request,
            "lti/deep_link_select.html",
            {
                "launch_id": message_launch.get_launch_id(),
                "room": room,
                "question_sets": room.question_sets.order_by("-updated_at"),
            },
        )

    # Resource link launch.
    custom = launch_data.get(f"{CLAIM}custom") or {}
    set_id = str(custom.get("set") or "")

    if instructor:
        user = provision_user(platform, launch_data)
        room = _ensure_room(platform, launch_data, user)
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        base = settings.FRONTEND_BASE_URL.rstrip("/")
        if set_id and room and room.question_sets.filter(pk=set_id).exists():
            return redirect(f"{base}/sets/{set_id}")
        if room:
            return redirect(f"{base}/rooms/{room.pk}")
        return redirect(base + "/")

    # Learners join anonymously — no account, straight to the participant page.
    context = launch_data.get(f"{CLAIM}context") or {}
    link = (
        LtiContextLink.objects.filter(
            platform=platform, context_id=str(context.get("id") or "")
        )
        .select_related("room")
        .first()
    )
    if link is None:
        return render(request, "lti/error.html",
                      {"message": "Dieser Kurs ist noch nicht verknüpft — die "
                                  "Lehrperson muss Abstimmbar zuerst öffnen."},
                      status=404)
    return redirect(f"/p/{link.room.code}/")


# A tiny, self-contained brand mark (green rounded square + check) served as
# the tool icon for LMS registration and deep-link items. Deliberately code-
# defined (no binary asset) and NOT the institution logo.
_LTI_ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" '
    'role="img" aria-label="abstimmBAR">'
    '<rect width="64" height="64" rx="14" fill="#16a34a"/>'
    '<path d="M18 33l10 10 18-22" fill="none" stroke="#fff" '
    'stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>'
    "</svg>"
)


def lti_icon(request):
    """Public tool icon (SVG) for LMS tool registration / deep-link items."""
    resp = HttpResponse(_LTI_ICON_SVG, content_type="image/svg+xml")
    resp["Cache-Control"] = "public, max-age=86400"
    return resp


def deep_link_respond(request):
    """Posts the chosen (or newly created) set back to the platform."""
    if request.method != "POST" or not request.user.is_authenticated:
        return HttpResponse(status=405 if request.method != "POST" else 403)
    launch_id = request.POST.get("launch_id", "")
    message_launch = DjangoMessageLaunch.from_cache(
        launch_id, request, build_tool_conf(), launch_data_storage=launch_storage()
    )
    if not message_launch.is_deep_link_launch():
        return HttpResponse("Not a deep linking launch.", status=400)

    launch_data = message_launch.get_launch_data()
    platform = platform_for(launch_data)
    room = _ensure_room(platform, launch_data, request.user)

    new_title = (request.POST.get("new_title") or "").strip()
    if new_title:
        question_set = QuestionSet.objects.create(room=room, title=new_title[:200])
    else:
        question_set = room.question_sets.filter(
            pk=request.POST.get("question_set")
        ).first()
        if question_set is None:
            return HttpResponse("Fragenset nicht gefunden.", status=400)

    resource = DeepLinkResource()
    resource.set_url(request.build_absolute_uri(reverse("lti-launch")))
    resource.set_custom_params({"set": str(question_set.pk)})
    resource.set_title(question_set.title)
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    resource.set_icon_url(f"{base}/lti/icon.svg")
    html = message_launch.get_deep_link().output_response_form([resource])
    return HttpResponse(html)


class LtiPlatformViewSet(BaseLtiPlatformViewSet):
    """Paket-CRUD mit abstimmbars Admin-Permission."""

    permission_classes: ClassVar = [IsAdmin]


class LtiToolInfoView(BaseLtiToolInfoView):
    permission_classes: ClassVar = [IsAdmin]
