# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Format detection for the question import (#323).

Returns the reader's raw result; the caller applies ``core.finalize`` with the
set's allowed kinds.
"""
from __future__ import annotations

import re

from django.utils.translation import gettext

from . import gift, h5p, ilias, safezip, simple
from .core import ImportFailed, ImportResult, scrub_text

# Pasted text and text files (simple/GIFT): 200 questions fit many times over;
# the cap keeps one request from occupying the single backend process.
TEXT_MAX_CHARS = 1_000_000

_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06")
_ZIP_EXTENSIONS = (".zip", ".h5p")
# Same question marker as the simple reader: a line "F:"/"Q:" wins over any
# GIFT-like braces inside the question text. ``[^\S\n]`` instead of ``\s``:
# whitespace that may span lines makes the MULTILINE search quadratic.
_SIMPLE_QUESTION_RE = re.compile(r"^[^\S\n]*[FQ][^\S\n]*:", re.IGNORECASE | re.MULTILINE)


def decode(data: bytes) -> str:
    """UTF-8 (BOM allowed), else Windows-1252; never raises."""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    return scrub_text(text)


def read_text(text: str) -> ImportResult:
    if len(text) > TEXT_MAX_CHARS:
        raise ImportFailed(gettext("The text is longer than 1 MB."))
    text = scrub_text(text)
    if _SIMPLE_QUESTION_RE.search(text.replace("\r\n", "\n").replace("\r", "\n")):
        return simple.parse(text)
    if gift.looks_like_gift(text):
        return gift.parse(text)
    return simple.parse(text)


def read_upload(data: bytes, filename: str) -> ImportResult:
    name = (filename or "").lower()
    if data.startswith(_ZIP_MAGIC) or name.endswith(_ZIP_EXTENSIONS):
        zf = safezip.open_zip(data)
        if h5p.is_h5p(zf):
            return h5p.parse(zf)
        return ilias.parse(zf)
    if name.endswith(".xml") or (data.lstrip(b"\xef\xbb\xbf \t\r\n")[:1] == b"<" and ilias.looks_like_qti(data)):
        return ilias.parse_xml(data)
    return read_text(decode(data))
