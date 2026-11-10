# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Site-content API: public reads (branding, landing text, footer pages,
data-collection registry) and staff-only management."""
from typing import ClassVar

from basicbar_integrations.metrics import MetricsView as BaseMetricsView
from django.shortcuts import get_object_or_404
from rest_framework import parsers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.permissions import IsAdmin

from .data_collection import COLLECTED, NOT_COLLECTED
from .models import Page, SiteConfig
from .serializers import (
    PageDetailSerializer,
    PageLinkSerializer,
    PageManageSerializer,
    SiteConfigSerializer,
)

MAX_LOGO_BYTES = 5 * 1024 * 1024


# --- public reads (no auth) --------------------------------------------------


class SiteView(APIView):
    """Branding + landing text for any visitor (header logo, pre-login page)."""

    permission_classes: ClassVar = []

    def get(self, request):
        return Response(SiteConfigSerializer(SiteConfig.load(), context={"request": request}).data)


class FooterPagesView(APIView):
    permission_classes: ClassVar = []

    def get(self, request):
        pages = Page.objects.filter(is_published=True, show_in_footer=True)
        return Response(PageLinkSerializer(pages, many=True).data)


class PageDetailView(APIView):
    permission_classes: ClassVar = []

    def get(self, request, slug):
        page = get_object_or_404(Page, slug=slug, is_published=True)
        return Response(PageDetailSerializer(page).data)


class DataCollectionView(APIView):
    """The privacy page's auto-generated data inventory (from code)."""

    permission_classes: ClassVar = []

    def get(self, request):
        return Response({"collected": COLLECTED, "not_collected": NOT_COLLECTED})


# --- staff management --------------------------------------------------------


class SiteManageView(APIView):
    permission_classes: ClassVar = [IsAdmin]

    def get(self, request):
        return Response(
            SiteConfigSerializer(SiteConfig.load(), context={"request": request}).data
        )

    def put(self, request):
        config = SiteConfig.load()
        # landing_text/closing_info are {"de", "en"} maps (#33 MR2); the
        # serializer's TranslatedMapMixin also still accepts a legacy plain
        # string (written to the canonical language only).
        serializer = SiteConfigSerializer(
            config, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class SiteLogoView(APIView):
    permission_classes: ClassVar = [IsAdmin]
    parser_classes: ClassVar = [parsers.MultiPartParser]

    def post(self, request):
        file = request.FILES.get("file")
        if file is None:
            return Response({"detail": "Keine Datei."}, status=400)
        is_image = (file.content_type or "").startswith("image/")
        is_svg = file.name.lower().endswith(".svg")
        if not (is_image or is_svg):
            return Response({"detail": "Only image files (including SVG)."}, status=400)
        if file.size > MAX_LOGO_BYTES:
            return Response({"detail": "The logo exceeds 5 MB."}, status=400)
        config = SiteConfig.load()
        if config.logo:
            config.logo.delete(save=False)
        config.logo = file
        config.save()
        return Response(
            SiteConfigSerializer(config, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request):
        config = SiteConfig.load()
        if config.logo:
            config.logo.delete(save=False)
            config.logo = None
            config.save()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminStatsView(APIView):
    """Staff-only JSON metrics for the React admin stats page (task 3 of the
    admin-stats-prometheus feature). Thin wrapper around ``common.stats``."""

    permission_classes: ClassVar = [IsAdmin]

    def get(self, request):
        import datetime

        from django.utils import timezone

        from . import stats

        today = timezone.localdate()

        def _parse(value):
            try:
                return datetime.date.fromisoformat(value)
            except (TypeError, ValueError):
                return None

        # Explicit from/to range wins; otherwise a `days` window ending today.
        frm = _parse(request.query_params.get("from"))
        to = _parse(request.query_params.get("to"))
        if frm:
            until = min(to or today, today)
            since = min(frm, until)
            # Cap the window so a huge range can't hammer the DB.
            since = max(since, until - datetime.timedelta(days=365))
        else:
            try:
                days = int(request.query_params.get("days", 30))
            except (TypeError, ValueError):
                days = 30
            days = max(1, min(365, days))
            until = today
            since = today - datetime.timedelta(days=days - 1)
        return Response({
            "totals": stats.totals(),
            "daily": stats.daily(since, until),
            "from": since.isoformat(),
            "to": until.isoformat(),
            "days": (until - since).days + 1,
            "committee": _committee_activity(),
        })


def _committee_activity():
    """Running meetings / open secret ballots. Mirrors
    ``committees.status.activity`` but resolves the models through the app
    registry so ``common`` never imports ``committees`` (two tiny counts)."""
    from django.apps import apps

    meeting = apps.get_model("rooms", "QuestionSet")
    ballot = apps.get_model("committees", "Ballot")
    return {
        "meetings_running": meeting.objects.filter(
            type="meeting", meeting_state="started",
        ).count(),
        "secret_ballots_open": ballot.objects.filter(status="open", secret=True).count(),
    }


class MetricsView(BaseMetricsView):
    """Prometheus exporter, top-level ``GET /metrics`` (deliberately outside
    ``/api/`` — a scrape target, not an app API route). Token check (404
    without ``METRICS_TOKEN``, 401 for a wrong bearer token) and the text
    format come from basicbar-integrations; this class only supplies the
    gauges: ``common.stats.totals()``, today's DailyModeSession counts and
    the committee activity."""

    def collect(self, gauges):
        from django.db.models import Count
        from django.utils import timezone

        from accounts.models import DailyModeSession

        from . import stats

        t = stats.totals()
        gauges.gauge("abstimmbar_rooms", "Total rooms", t["rooms"])
        gauges.gauge("abstimmbar_rooms_lti", "Rooms created via LTI", t["rooms_lti"])
        gauges.gauge("abstimmbar_users", "Registered users", t["users"])
        gauges.gauge("abstimmbar_question_sets", "Question sets by type",
                     labels=[({"type": k}, v) for k, v in t["sets_by_type"].items()])
        gauges.gauge("abstimmbar_questions", "Questions by kind",
                     labels=[({"kind": k}, v) for k, v in t["questions_by_kind"].items()])
        gauges.gauge("abstimmbar_runs", "Runs (presented sets) by set type",
                     labels=[({"type": k}, v) for k, v in t["runs_by_type"].items()])
        gauges.gauge("abstimmbar_participants", "Distinct participants who voted",
                     t["participants"])
        gauges.gauge("abstimmbar_questions_run", "Distinct questions voted on",
                     t["questions_run"])
        tour = t["tour"]
        gauges.gauge("abstimmbar_tour_events", "Guided-tour events by kind and mode",
                     labels=[({"kind": k, "mode": m}, tour[k][m])
                             for k in ("started", "completed", "aborted")
                             for m in ("easy", "pro")])
        gauges.gauge("abstimmbar_tour_starts", "Guided-tour starts by source",
                     labels=[({"source": s}, v) for s, v in tour["by_source"].items()])
        gauges.gauge("abstimmbar_tour_users_seen",
                     "Users who finished or dismissed the guided tour", tour["users_seen"])
        today = timezone.localdate()
        sess = {r["mode"]: r["n"] for r in
                DailyModeSession.objects.filter(date=today)
                .values("mode").annotate(n=Count("id"))}
        gauges.gauge("abstimmbar_sessions_today", "Active sessions today by mode",
                     labels=[({"mode": m}, sess.get(m, 0)) for m in ("easy", "pro")])
        committee = _committee_activity()
        gauges.gauge("abstimmbar_committee_meetings_running", "Committee meetings in progress",
                     committee["meetings_running"])
        gauges.gauge("abstimmbar_committee_secret_ballots_open", "Open secret committee ballots",
                     committee["secret_ballots_open"])


class ManagePageViewSet(viewsets.ModelViewSet):
    queryset = Page.objects.all()
    serializer_class = PageManageSerializer
    permission_classes: ClassVar = [IsAdmin]
    pagination_class = None  # small admin list — return a plain array

    def perform_create(self, serializer):
        highest = Page.objects.order_by("-footer_order").first()
        serializer.save(footer_order=(highest.footer_order + 1) if highest else 0)

    @action(detail=False, methods=["post"])
    def reorder(self, request):
        order = request.data.get("order") or []
        for index, page_id in enumerate(order):
            Page.objects.filter(pk=page_id).update(footer_order=index)
        return Response({"status": "ok"})
