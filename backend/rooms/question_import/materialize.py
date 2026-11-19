# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Store the images kept by the question import (#336).

The readers leave ``/media/_import/<n>`` placeholders in the drafts' question
HTML and option ``image``; this module stores the images that kept drafts
actually reference as uploads of the importing person and swaps in their
/media/ URLs. Only ``<img src>`` attributes and option ``image`` are
rewritten: a placeholder string anywhere else stays as it is.
"""
from __future__ import annotations

import html as html_lib
import re

from rooms.image_credits import apply_credit, credit_dict, has_credit
from rooms.images import store_image_bytes

from .core import _IMG_RE, _KEPT_SRC_RE, _SRC_RE, IMPORT_IMAGE_PREFIX, ImportImage, _attr


class _Store:
    """Stores each referenced placeholder once; failures are cached too."""

    def __init__(self, images: dict[str, ImportImage], user):
        self.images = images
        self.user = user
        self.uploads: dict[str, object] = {}  # placeholder -> UploadedImage | None

    def get(self, placeholder: str):
        if placeholder not in self.uploads:
            img = self.images.get(placeholder)
            uploaded = store_image_bytes(img.data, img.filename, self.user) if img else None
            if uploaded is not None:
                apply_credit(uploaded, img.credit)
            self.uploads[placeholder] = uploaded
        return self.uploads[placeholder]


def _rewrite_html(value: str, store: _Store, used: list) -> tuple[str, bool]:
    """(html with placeholder images stored or stripped, an image was lost)."""
    lost = False

    def replace(m: re.Match) -> str:
        nonlocal lost
        tag = m.group(0)
        src_m = _KEPT_SRC_RE.search(tag)
        if not src_m:
            # Not in the sanitizer's canonical form: never rewritten, and
            # removed if it still points at a placeholder.
            if _attr(_SRC_RE, tag).strip().startswith(IMPORT_IMAGE_PREFIX):
                lost = True
                return ""
            return tag
        src = html_lib.unescape(src_m.group(1))
        if not src.startswith(IMPORT_IMAGE_PREFIX):
            return tag
        uploaded = store.get(src)
        if uploaded is None:
            lost = True
            return ""
        used.append(uploaded)
        url = html_lib.escape(uploaded.file.url)
        return f"{tag[:src_m.start(1)]}{url}{tag[src_m.end(1):]}"

    cut = value.rfind(">") + 1
    return _IMG_RE.sub(replace, value[:cut]) + value[cut:], lost


def materialize_images(
    drafts: list[dict], images: dict[str, ImportImage], user
) -> tuple[list[dict], int]:
    """Store the images referenced by ``drafts`` and rewrite their references.

    Returns (drafts, number of drafts that lost an image). An image that
    cannot be stored is removed (``<img>`` stripped, option ``image`` = "").
    Drafts with credited images get ``image_credits`` for the review preview.
    """
    store = _Store(images, user)
    dropped = 0
    for draft in drafts:
        used: list = []
        text, lost = _rewrite_html(draft.get("text") or "", store, used)
        draft["text"] = text
        for option in draft.get("options") or []:
            image = option.get("image") or ""
            if not image.startswith(IMPORT_IMAGE_PREFIX):
                continue
            uploaded = store.get(image)
            if uploaded is None:
                option["image"] = ""
                lost = True
            else:
                option["image"] = uploaded.file.url
                used.append(uploaded)
        dropped += lost
        credits = {}
        for uploaded in used:
            if has_credit(uploaded) and uploaded.file.url not in credits:
                credits[uploaded.file.url] = credit_dict(uploaded, uploaded.file.url)
        if credits:
            draft["image_credits"] = list(credits.values())
    return drafts, dropped
