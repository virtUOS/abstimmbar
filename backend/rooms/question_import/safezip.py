# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Defensive ZIP access for the question import (#323).

Never extracts to disk; limits entry count and total declared size, streams
reads with a hard byte cap (declared sizes can lie) and ignores unsafe names.
"""
from __future__ import annotations

import io
import zipfile

from django.utils.translation import gettext

from .core import ImportFailed

MAX_ENTRIES = 500
MAX_TOTAL_BYTES = 30 * 1024 * 1024


def _safe(name: str) -> bool:
    if not name or name.startswith(("/", "\\")) or "\x00" in name:
        return False
    if len(name) > 1 and name[1] == ":":  # Windows drive letter
        return False
    parts = name.replace("\\", "/").split("/")
    return ".." not in parts


def open_zip(data: bytes) -> zipfile.ZipFile:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except (zipfile.BadZipFile, ValueError, OSError, EOFError, NotImplementedError) as exc:
        raise ImportFailed(gettext("The file is not a readable ZIP archive.")) from exc
    if len(infos) > MAX_ENTRIES:
        raise ImportFailed(gettext("The archive contains too many files."))
    if sum(i.file_size for i in infos) > MAX_TOTAL_BYTES:
        raise ImportFailed(gettext("The archive is too large when unpacked."))
    return zf


def names(zf: zipfile.ZipFile) -> list[str]:
    return [i.filename for i in zf.infolist() if not i.is_dir() and _safe(i.filename)]


def read(zf: zipfile.ZipFile, name: str, max_bytes: int) -> bytes:
    if not _safe(name):
        raise ImportFailed(gettext("The archive contains an invalid file name."))
    try:
        info = zf.getinfo(name)
    except KeyError as exc:
        raise ImportFailed(gettext("The file %(name)s is missing in the archive.") % {"name": name}) from exc
    try:
        with zf.open(info) as fh:
            buf = fh.read(max_bytes + 1)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError, EOFError, ValueError) as exc:
        raise ImportFailed(gettext("The archive is damaged or encrypted.")) from exc
    if len(buf) > max_bytes:
        raise ImportFailed(gettext("The file %(name)s in the archive is too large.") % {"name": name})
    return buf
