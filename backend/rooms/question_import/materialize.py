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

from .core import (
    _IMG_RE,
    _KEPT_SRC_RE,
    _SRC_RE,
    IMPORT_IMAGE_PREFIX,
    ImportImage,
    ImportResult,
    _attr,
    has_image,
    plain,
)


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


def _materialize(draft: dict, store: _Store) -> bool:
    """Store and rewrite the images of one draft; True if one was lost."""
    used: list = []
    draft["text"], lost = _rewrite_html(draft.get("text") or "", store, used)
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
    credits = {}
    for uploaded in used:
        if has_credit(uploaded) and uploaded.file.url not in credits:
            credits[uploaded.file.url] = credit_dict(uploaded, uploaded.file.url)
    if credits:
        draft["image_credits"] = list(credits.values())
    return lost


def _still_valid(draft: dict) -> bool:
    """Drop options left with neither text nor image, then check what the
    readers require of a question: a text (or image), at least two options
    for choice/ordering kinds, and a correct answer for choice kinds that
    had one."""
    options = draft.get("options") or []
    had_correct = any(o.get("is_correct") for o in options)
    options = [o for o in options if (o.get("text") or "").strip() or o.get("image")]
    draft["options"] = options
    text = draft.get("text") or ""
    if not (plain(text) or has_image(text)):
        return False
    if draft.get("kind") in _OPTION_KINDS:
        if len(options) < 2:
            return False
        if had_correct and not any(o.get("is_correct") for o in options):
            return False
    return True


_OPTION_KINDS = ("single_choice", "multiple_choice", "ordering")


def materialize_images(result: ImportResult, user) -> None:
    """Store the images the finalized drafts reference, rewrite references.

    An image that cannot be stored is removed (``<img>`` stripped, option
    ``image`` = ""); a draft that thereby no longer forms a valid question is
    dropped and reported as ``invalid``. A kept draft that lost an image is
    reported as ``image_dropped`` once, unless reading already did. Drafts
    with credited images get ``image_credits`` for the review preview.
    """
    store = _Store(result.images, user)
    kept: list[dict] = []
    for index, draft in enumerate(result.drafts):
        reported = index in result.image_reported
        if not _materialize(draft, store):
            kept.append(draft)
        elif _still_valid(draft):
            kept.append(draft)
            if not reported:
                result.skip("image_dropped")
        else:
            result.skip("invalid")
            if reported:
                result._unskip("image_dropped")  # question itself skipped
    result.drafts = kept
    result.image_reported = set()
