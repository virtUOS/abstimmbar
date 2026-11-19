# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Shared core of the question import (#323): result type, text helpers, limits.

Texts are never shortened or rephrased: whatever exceeds a limit is skipped
and reported instead.
"""
from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field

from django.conf import settings
from django.utils.translation import gettext
from lxml import etree

from rooms.sanitize import clean_html

FORMATS = ("simple", "gift", "h5p", "ilias")

MAX_QUESTIONS = 200
MAX_OPTIONS = 20
OPTION_TEXT_MAX = 500
QUESTION_TEXT_MAX = 10_000


@dataclass
class ImportResult:
    format: str
    drafts: list[dict] = field(default_factory=list)
    skipped: dict[tuple[str, str], int] = field(default_factory=dict)

    def skip(self, reason: str, detail: str = "", n: int = 1) -> None:
        key = (reason, detail)
        self.skipped[key] = self.skipped.get(key, 0) + n

    def skipped_list(self) -> list[dict]:
        return [
            {"reason": r, "detail": d, "count": c}
            for (r, d), c in sorted(self.skipped.items())
        ]


class ImportFailed(Exception):
    """File/text not readable -> 400 with str(exc) as message."""


def html_paragraphs(text: str) -> str:
    """Escape plain text; blank lines become paragraphs, newlines ``<br>``."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    return "".join(
        "<p>" + "<br>".join(html_lib.escape(ln.strip()) for ln in p.strip().split("\n")) + "</p>"
        for p in paragraphs
    )


_TAG_RE = re.compile(r"<[^>]*>")
_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)


def has_image(html: str) -> bool:
    return bool(_IMG_RE.search(html or ""))


def strip_images(html: str) -> str:
    return _IMG_RE.sub("", html or "")


def clean_without_images(raw: str) -> tuple[str, bool]:
    """Sanitize HTML without images; returns (html, an image was dropped).

    Strips again after sanitizing because the sanitizer allows ``img`` and
    normalizes tricks like ``<im<img>g`` or ``<image>`` into one.
    """
    raw = raw or ""
    stripped = strip_images(raw)
    html = clean_html(stripped)
    cleaned = strip_images(html)
    return cleaned.strip(), stripped != raw or cleaned != html


def plain(html_or_text: str) -> str:
    """Strip tags, resolve entities, trim whitespace."""
    return html_lib.unescape(_TAG_RE.sub("", html_or_text or "")).strip()


def true_false_labels() -> tuple[str, str]:
    if getattr(settings, "CONTENT_DEFAULT_LANGUAGE", "de") == "en":
        return ("True", "False")
    return ("Wahr", "Falsch")


def finalize(result: ImportResult, allowed_kinds: tuple[str, ...]) -> ImportResult:
    """Apply limits; skipped questions are reported, texts are never altered."""
    kept: list[dict] = []
    for draft in result.drafts:
        options = draft.get("options") or []
        if (
            draft["kind"] == "single_choice"
            and not draft.get("binary_choice")
            and sum(bool(o.get("is_correct")) for o in options) > 1
        ):
            # e.g. ILIAS single choice with several positive answers: the
            # editor only accepts that as multiple choice; texts stay verbatim.
            draft["kind"] = "multiple_choice"
        if draft["kind"] not in allowed_kinds:
            result.skip("not_allowed_in_set", draft["kind"])
        elif len(options) > MAX_OPTIONS:
            result.skip("too_many_options")
        elif any(len(o["text"]) > OPTION_TEXT_MAX for o in options):
            result.skip("option_too_long")
        elif len(draft["text"]) > QUESTION_TEXT_MAX:
            result.skip("text_too_long")
        else:
            kept.append(draft)
    if len(kept) > MAX_QUESTIONS:
        result.skip("over_limit", n=len(kept) - MAX_QUESTIONS)
        kept = kept[:MAX_QUESTIONS]
    result.drafts = kept
    return result


def safe_xml(data: bytes) -> etree._Element:
    """Parse untrusted XML: no DTD loading, no network, no entity expansion.

    Documents declaring entities (XXE, billion laughs) are rejected outright;
    an external-only DOCTYPE (as in every ILIAS export) is accepted.
    """
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, load_dtd=False)
    try:
        root = etree.fromstring(data, parser)
    except (etree.LxmlError, ValueError, TypeError) as exc:
        raise ImportFailed(gettext("The file is not valid XML.")) from exc
    if root is None:
        raise ImportFailed(gettext("The file is not valid XML."))
    dtd = root.getroottree().docinfo.internalDTD
    has_entities = dtd is not None and any(True for _ in dtd.iterentities())
    if has_entities or any(isinstance(el, etree._Entity) for el in root.iter()):
        raise ImportFailed(gettext("The XML file declares entities, which are not allowed."))
    return root
