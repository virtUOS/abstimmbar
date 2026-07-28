# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Site-content API: public reads (branding, landing text, footer pages,
data-collection registry) and staff-only management."""
from typing import ClassVar

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
            return Response({"detail": "Nur Bilddateien (auch SVG)."}, status=400)
        if file.size > MAX_LOGO_BYTES:
            return Response({"detail": "Logo überschreitet 5 MB."}, status=400)
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
