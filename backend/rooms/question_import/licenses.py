# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""H5P license metadata -> image credit (#336).

The credit dict uses the keys of the JSON transfer ``credit`` (author, title,
source, license, version, text) and fits the limits of
``ImageCreditSerializer``, which validates each field again when the image is
stored. Untrusted input: every value is type-checked, nothing raises.
"""
from __future__ import annotations

import re

from rooms.image_credits import VERSION_RE

# H5P license codes (content metadata and the older ``copyright`` object).
_CODES = {
    "CC BY": "cc-by",
    "CC BY-SA": "cc-by-sa",
    "CC BY-ND": "cc-by-nd",
    "CC BY-NC": "cc-by-nc",
    "CC BY-NC-SA": "cc-by-nc-sa",
    "CC BY-NC-ND": "cc-by-nc-nd",
    "CC0 1.0": "cc0",
    "CC PDM": "pd",
    "PD": "pd",
    "C": "other",
}
# Stored in the canonical content language (CONTENT_DEFAULT_LANGUAGE "de").
ALL_RIGHTS_RESERVED = "Alle Rechte vorbehalten"
AUTHOR_MAX = 200
TITLE_MAX = 300
SOURCE_MAX = 500
TEXT_MAX = 100


def _str(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _authors(metadata: dict) -> str:
    authors = metadata.get("authors")
    names = []
    if isinstance(authors, list):
        names = [_str(a.get("name")) for a in authors if isinstance(a, dict)]
    elif _str(metadata.get("author")):  # older ``copyright`` object
        names = [_str(metadata.get("author"))]
    return ", ".join(n for n in names if n)[:AUTHOR_MAX]


def _source(value) -> str:
    source = _str(value)
    if len(source) > SOURCE_MAX or not source.lower().startswith(("http://", "https://")):
        return ""
    return source


def h5p_credit(metadata: dict, license_code: str, version: str, extras: str) -> dict:
    """Credit dict for an H5P image, or ``{}`` if it carries no information.

    Unknown codes (``U``, ``GNU GPL``, ``ODC PDDL`` …) leave the license
    empty but keep author/title/source. The version is kept only for the CC
    licenses that have one; ``licenseExtras`` only extends the text of ``C``.
    """
    metadata = metadata if isinstance(metadata, dict) else {}
    code = _str(license_code)
    key = _CODES.get(code, "")
    version = _str(version)
    if not key.startswith("cc-by") or not re.fullmatch(VERSION_RE, version):
        version = ""
    text = ""
    if key == "other":
        extra = _str(extras)
        text = f"{ALL_RIGHTS_RESERVED}; {extra}" if extra else ALL_RIGHTS_RESERVED
        text = text[:TEXT_MAX]
    credit = {
        "author": _authors(metadata),
        "title": _str(metadata.get("title"))[:TITLE_MAX],
        "source": _source(metadata.get("source")),
        "license": key,
        "version": version,
        "text": text,
    }
    return credit if any(credit.values()) else {}
