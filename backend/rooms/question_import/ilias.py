# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Reader for ILIAS test/pool exports in QTI 1.2 (#323), see the design spec, format 4.

Supports both the legacy question type names ("SINGLE CHOICE QUESTION") and
the current ``ass*`` ids ILIAS writes today. Correctness is derived from
``resprocessing``: a label is correct if a ``respcondition`` with a positive
``setvar`` matches it with a ``varequal`` that is not inside ``<not>``.
"""
from __future__ import annotations

import math
import zipfile

from django.utils.translation import gettext

from . import safezip
from .core import (
    MAX_OPTIONS,
    QUESTION_TEXT_MAX,
    ImportFailed,
    ImportResult,
    clean_without_images,
    has_image,
    html_paragraphs,
    plain,
    safe_xml,
    strip_images,
)

QTI_MAX = 20 * 1024 * 1024
DETAIL_MAX = 80

_KINDS = {
    "SINGLE CHOICE QUESTION": "single_choice",
    "assSingleChoice": "single_choice",
    "MULTIPLE CHOICE QUESTION": "multiple_choice",
    "assMultipleChoice": "multiple_choice",
    "TEXT QUESTION": "open_text",
    "assTextQuestion": "open_text",
    "ORDERING QUESTION": "ordering",
    "assOrderingQuestion": "ordering",
}
_IMAGE_ORDERING = ("OQP", "OQNP")


def find_qti(zf: zipfile.ZipFile) -> str | None:
    for name in safezip.names(zf):
        base = name.replace("\\", "/").rsplit("/", 1)[-1].lower()
        if base.endswith(".xml") and (base.endswith("qti.xml") or "_qti_" in base):
            return name
    return None


def looks_like_qti(data: bytes) -> bool:
    try:
        return safe_xml(data).tag == "questestinterop"
    except ImportFailed:
        return False


def parse(zf: zipfile.ZipFile) -> ImportResult:
    name = find_qti(zf)
    if name is None:
        raise ImportFailed(gettext("The archive contains no ILIAS question export (qti.xml)."))
    return parse_xml(safezip.read(zf, name, QTI_MAX))


def parse_xml(data: bytes) -> ImportResult:
    root = safe_xml(data)
    if root.tag != "questestinterop":
        raise ImportFailed(gettext("The XML file is not an ILIAS QTI export."))
    result = ImportResult(format="ilias")
    for item in root.iter("item"):
        _item(item, result)
    return result


# -- helpers -----------------------------------------------------------------

def _text(el) -> str:
    return "".join(el.itertext()) if el is not None else ""


def _detail(qtype: str) -> str:
    return (qtype or "unknown")[:DETAIL_MAX]


def _question_type(item) -> str:
    for field in item.iterfind("itemmetadata/qtimetadata/qtimetadatafield"):
        if _text(field.find("fieldlabel")).strip() == "QUESTIONTYPE":
            return _text(field.find("fieldentry")).strip()
    return ""


def _iter_outside(root, tags: tuple[str, ...], skip) -> list:
    """Descendants of ``root`` with a tag in ``tags``, in document order, not
    inside any element for which ``skip(tag)`` is true.

    One linear walk instead of an ancestor walk per element, which is
    O(elements x depth) on deeply nested, wide files.
    """
    found = []
    stack = list(reversed(root))
    while stack:
        el = stack.pop()
        tag = el.tag
        if not isinstance(tag, str) or skip(tag):
            continue
        if tag in tags:
            found.append(el)
        stack.extend(reversed(el))
    return found


def _is_response(tag: str) -> bool:
    return tag.startswith("response_")


def _index(value: str) -> int | None:
    """Non-negative ASCII integer of bounded length, else None."""
    if not value or len(value) > 6 or not value.isascii() or not value.isdigit():
        return None
    return int(value)


def _question_html(presentation) -> tuple[str, bool]:
    """Question text from the material outside any response element."""
    if presentation is None:
        return "", False
    image = False
    parts = []
    length = 0
    for el in _iter_outside(presentation, ("mattext", "matimage"), _is_response):
        if el.tag == "matimage":
            image = True
            continue
        if el.get("label") == "answerdepth" or length > QUESTION_TEXT_MAX:
            # Past the limit the question is skipped as text_too_long anyway.
            continue
        raw = _text(el)
        if (el.get("texttype") or "").lower() == "text/xhtml":
            html, dropped = clean_without_images(raw)
            image = image or dropped
            parts.append(html)
        elif raw.strip():
            parts.append(html_paragraphs(raw))
        else:
            continue
        length += len(parts[-1])
    return "".join(parts).strip(), image


def _labels(response) -> list[tuple[str, str, bool]]:
    """(ident, plain text, has image) per response_label, in document order."""
    labels = []
    for label in response.iter("response_label"):
        raw_parts, image = [], label.find(".//matimage") is not None
        for mt in label.iter("mattext"):
            if mt.get("label") == "answerdepth":
                continue
            raw = _text(mt)
            if (mt.get("texttype") or "").lower() == "text/xhtml":
                if has_image(raw):
                    raw = strip_images(raw)
                    image = True
                raw = plain(raw)
            raw_parts.append(raw.strip())
        labels.append(((label.get("ident") or "").strip(), "".join(raw_parts).strip(), image))
    return labels


def _more_than(iterable, limit: int) -> bool:
    return any(i >= limit for i, _ in enumerate(iterable))


def _points(rc) -> float | None:
    """Sum of Add/Set setvars; None if the condition sets no score at all."""
    total, seen = 0.0, False
    for sv in rc.iter("setvar"):
        seen = True
        if (sv.get("action") or "Add") not in ("Add", "Set"):
            continue
        try:
            value = float(_text(sv).strip())
        except ValueError:
            continue
        if math.isfinite(value):
            total += value
    return total if seen else None


def _plain_varequals(rc):
    cv = rc.find("conditionvar")
    if cv is None:
        return []
    return _iter_outside(cv, ("varequal",), lambda tag: tag == "not")


def _correct_idents(item) -> set[str]:
    idents = set()
    for rc in item.iterfind("resprocessing/respcondition"):
        points = _points(rc)
        if points is None or points <= 0:
            continue
        idents.update(_text(ve).strip() for ve in _plain_varequals(rc))
    return idents


def _solution_order(item, labels) -> list[int] | None:
    """Label positions in solution order, or None if the solution is unusable.

    The varequal text names the label (legacy: its ident; current ILIAS: its
    0-based position), the ``index`` attribute is its rank in the solution.
    """
    by_ident = {ident: i for i, (ident, _, _) in enumerate(labels)}
    ranks: dict[int, int] = {}
    used: set[int] = set()
    for rc in item.iterfind("resprocessing/respcondition"):
        if _points(rc) is None:  # feedback-only conditions
            continue
        for ve in _plain_varequals(rc):
            content = _text(ve).strip()
            rank = _index((ve.get("index") or "").strip())
            pos = by_ident.get(content, _index(content))
            if pos is None or pos >= len(labels) or rank is None:
                return None
            if pos in ranks or rank in used:
                return None
            ranks[pos] = rank
            used.add(rank)
    if len(ranks) != len(labels):
        return None
    return sorted(ranks, key=ranks.__getitem__)


def _item(item, result: ImportResult) -> None:
    qtype = _question_type(item)
    kind = _KINDS.get(qtype)
    if kind is None:
        result.skip("unsupported_type", _detail(qtype))
        return
    presentation = item.find("presentation")
    text, image = _question_html(presentation)
    if not text:
        result.skip("invalid", _detail(qtype))
        return
    if kind == "open_text":
        result.add({"kind": kind, "text": text, "options": []}, image)
        return

    response = presentation.find(".//response_lid")
    if response is not None and _more_than(response.iter("response_label"), MAX_OPTIONS):
        result.skip("too_many_options")  # bail out before reading every label
        return
    labels = _labels(response) if response is not None else []
    if kind == "ordering" and (
        (response is not None and response.get("ident") in _IMAGE_ORDERING)
        or any(img for _, _, img in labels)
    ):
        result.skip("unsupported_type", _detail(f"{qtype} (image)"))
        return
    if any(not t and img for _, t, img in labels):
        result.skip("unsupported_type", _detail(f"{qtype} (image)"))
        return
    if len(labels) < 2 or any(not t for _, t, _ in labels):
        result.skip("invalid", _detail(qtype))
        return

    if kind == "ordering":
        order = _solution_order(item, labels)
        if order is None:
            result.skip("invalid", _detail(qtype))
            return
        options = [{"text": labels[i][1], "is_correct": False} for i in order]
    else:
        correct = _correct_idents(item)
        options = [{"text": t, "is_correct": ident in correct} for ident, t, _ in labels]
        image = image or any(img for _, _, img in labels)
    result.add({"kind": kind, "text": text, "options": options}, image)

