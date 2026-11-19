# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Reader for ILIAS test/pool exports in QTI 1.2 (#323), see the design spec, format 4.

Supports both the legacy question type names ("SINGLE CHOICE QUESTION") and
the current ``ass*`` ids ILIAS writes today. Correctness is derived from
``resprocessing``: a label is correct if a ``respcondition`` with a positive
``setvar`` matches it with a ``varequal`` that is not inside ``<not>``.
"""
from __future__ import annotations

import base64
import binascii
import math
import zipfile

from django.utils.translation import gettext

from rooms.images import MAX_IMAGE_BYTES

from . import safezip
from .core import (
    IMAGE_ALT_MAX,
    MAX_OPTIONS,
    QUESTION_TEXT_MAX,
    ImportFailed,
    ImportImage,
    ImportResult,
    clean_keeping_images,
    has_image,
    html_paragraphs,
    image_alts,
    image_srcs,
    img_tag,
    import_filename,
    is_package_path,
    plain,
    safe_xml,
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
    base = name.rsplit("/", 1)[0] + "/" if "/" in name else ""
    return parse_xml(safezip.read(zf, name, QTI_MAX), zf, base)


def parse_xml(data: bytes, zf: zipfile.ZipFile | None = None, base: str = "") -> ImportResult:
    """``zf``/``base``: the archive and the QTI file's directory, against which
    ``uri`` images resolve; a bare XML upload keeps only base64 images."""
    root = safe_xml(data)
    if root.tag != "questestinterop":
        raise ImportFailed(gettext("The XML file is not an ILIAS QTI export."))
    result = ImportResult(format="ilias")
    files = _Files(zf, base, result)
    for item in root.iter("item"):
        _item(item, result, _ItemImages(item, files))
    return result


# -- images (#336) -------------------------------------------------------------

# base64 of MAX_IMAGE_BYTES plus line breaks
_B64_MAX = MAX_IMAGE_BYTES * 4 // 3 + MAX_IMAGE_BYTES // 38 + 16


class _Files:
    """Images read from the archive, once per path, as placeholders."""

    def __init__(self, zf, base: str, result: ImportResult):
        self.zf = zf
        self.base = base
        self.result = result
        self.resolved: dict[str, str] = {}

    def add(self, uri: str) -> str:
        uri = (uri or "").strip()
        if self.zf is None or not is_package_path(uri):
            return ""
        name = self.base + uri
        if name in self.resolved:
            return self.resolved[name]
        if self.result.images_full():
            return ""
        try:
            data = safezip.read(self.zf, name, MAX_IMAGE_BYTES)
        except ImportFailed:
            data = b""
        src = self.result.add_image(ImportImage(data=data, filename=import_filename(uri)), key=name) if data else ""
        self.resolved[name] = src
        return src


class _ItemImages:
    """Images of one item: ``matimage`` (base64 or ``uri``) and ``<img>`` in
    XHTML mattext, whose src names a matimage label (ILIAS media objects) or
    a path. ILIAS carries no license data, so no credit."""

    def __init__(self, item, files: _Files):
        self.files = files
        self.by_label = {}
        for el in item.iter("matimage"):
            self.by_label.setdefault((el.get("label") or "").strip(), el)
        self.consumed: set = set()
        self.done: dict = {}  # matimage element -> placeholder or ""

    def matimage(self, el) -> str:
        if el not in self.done:
            self.done[el] = self._read(el)
        return self.done[el]

    def _read(self, el) -> str:
        if (el.get("embedded") or "").lower() == "base64":
            encoded = _text(el)
            if len(encoded) > _B64_MAX or self.files.result.images_full():
                return ""
            try:
                data = base64.b64decode("".join(encoded.split()), validate=True)
            except (binascii.Error, ValueError):
                return ""
            if not data or len(data) > MAX_IMAGE_BYTES:
                return ""
            name = import_filename(el.get("label") or "", el.get("imagtype") or "")
            return self.files.result.add_image(ImportImage(data=data, filename=name))
        return self.files.add(el.get("uri") or "")

    def inline(self, src: str) -> str:
        el = self.by_label.get(src.strip())
        if el is not None:
            self.consumed.add(el)
            return self.matimage(el)
        return self.files.add(src)

    def html(self, raw: str) -> tuple[str, bool]:
        return clean_keeping_images(raw, self.inline)


def _no_images(raw: str) -> tuple[str, bool]:
    """Like _ItemImages.html, but drops every image (nothing is read)."""
    return clean_keeping_images(raw, lambda src: "")


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


def _question_html(presentation, images: _ItemImages) -> tuple[str, bool]:
    """Question text from the material outside any response element; a
    matimage not already shown by an inline ``<img>`` follows at its place."""
    if presentation is None:
        return "", False
    image = False
    parts: list = []
    length = 0
    for el in _iter_outside(presentation, ("mattext", "matimage"), _is_response):
        if el.tag == "matimage":
            parts.append(el)  # resolved below, once inline references are known
            continue
        if el.get("label") == "answerdepth" or length > QUESTION_TEXT_MAX:
            # Past the limit the question is skipped as text_too_long anyway.
            continue
        raw = _text(el)
        if (el.get("texttype") or "").lower() == "text/xhtml":
            html, dropped = images.html(raw)
            image = image or dropped
            parts.append(html)
        elif raw.strip():
            parts.append(html_paragraphs(raw))
        else:
            continue
        length += len(parts[-1])
    out = []
    for part in parts:
        if isinstance(part, str):
            out.append(part)
        elif part not in images.consumed:
            src = images.matimage(part)
            if src:
                out.append(f"<p>{img_tag(src)}</p>")
            else:
                image = True
    return "".join(out).strip(), image


def _labels(response, images: _ItemImages | None) -> list[tuple[str, str, str, str, bool]]:
    """(ident, plain text, option image, its alt, image dropped) per response_label, in
    document order. The first image becomes the option image; without
    ``images`` (ordering) nothing is read and every image counts as dropped."""
    html_of = images.html if images is not None else _no_images
    labels = []
    for label in response.iter("response_label"):
        raw_parts, srcs, alts, dropped = [], [], [], False
        for el in label.iter("mattext", "matimage"):
            if el.tag == "matimage":
                src = images.matimage(el) if images is not None else ""
                if src:
                    srcs.append(src)
                    alts.append((el.get("alt") or "").strip())
                else:
                    dropped = True
                continue
            if el.get("label") == "answerdepth":
                continue
            raw = _text(el)
            if (el.get("texttype") or "").lower() == "text/xhtml":
                if has_image(raw):
                    html, lost = html_of(raw)
                    srcs += image_srcs(html)
                    alts += image_alts(html)
                    dropped = dropped or lost
                    raw = html
                raw = plain(raw)
            raw_parts.append(raw.strip())
        # inline <img> + its own matimage: one image, the first non-empty alt
        alt_of: dict[str, str] = {}
        for src, alt in zip(srcs, alts):
            alt_of[src] = alt_of.get(src) or alt
        srcs = list(alt_of)
        image = srcs[0] if srcs else ""
        dropped = dropped or len(srcs) > 1
        labels.append((
            (label.get("ident") or "").strip(), "".join(raw_parts).strip(),
            image, alt_of[image][:IMAGE_ALT_MAX] if image else "", dropped,
        ))
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
    by_ident = {ident: i for i, (ident, *_) in enumerate(labels)}
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


def _item(item, result: ImportResult, images: _ItemImages) -> None:
    qtype = _question_type(item)
    kind = _KINDS.get(qtype)
    if kind is None:
        result.skip("unsupported_type", _detail(qtype))
        return
    presentation = item.find("presentation")
    text, image = _question_html(presentation, images)
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
    # Picture ordering stays unsupported, so its images are never read.
    labels = _labels(response, None if kind == "ordering" else images) if response is not None else []
    if kind == "ordering" and (
        (response is not None and response.get("ident") in _IMAGE_ORDERING)
        or any(lost for *_, lost in labels)
    ):
        result.skip("unsupported_type", _detail(f"{qtype} (image)"))
        return
    if any(not t and not img and lost for _, t, img, _, lost in labels):
        result.skip("unsupported_type", _detail(f"{qtype} (image)"))
        return
    if len(labels) < 2 or any(not (t or img) for _, t, img, _, _ in labels):
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
        options = []
        for ident, t, img, alt, lost in labels:
            option = {"text": t, "is_correct": ident in correct}
            if img:
                option["image"] = img
                if alt:
                    option["image_alt"] = alt
            options.append(option)
            image = image or lost
    result.add({"kind": kind, "text": text, "options": options}, image)

