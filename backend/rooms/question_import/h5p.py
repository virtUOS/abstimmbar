# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Reader for H5P packages (#323), see the design spec, format 3."""
from __future__ import annotations

import json
import re
import zipfile

from django.utils.translation import gettext

from rooms.images import MAX_IMAGE_BYTES

from . import safezip
from .core import (
    MAX_OPTIONS,
    ImportFailed,
    ImportImage,
    ImportResult,
    clean_keeping_images,
    has_image,
    image_alts,
    image_srcs,
    img_tag,
    import_filename,
    is_package_path,
    plain,
    scrub_text,
    true_false_labels,
)
from .licenses import h5p_credit

JSON_MAX = 5 * 1024 * 1024
MAX_DEPTH = 12
_BREAK_RE = re.compile(r"</p\s*>|<br\s*/?>", re.IGNORECASE)


def is_h5p(zf: zipfile.ZipFile) -> bool:
    return "h5p.json" in safezip.names(zf)


def _scrub(value):
    """NUL/lone surrogates can enter via JSON escapes (\\u0000, \\ud800)."""
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, dict):
        return {_scrub(k): _scrub(v) for k, v in value.items()}
    return value


def _json(zf: zipfile.ZipFile, name: str):
    raw = safezip.read(zf, name, JSON_MAX)
    try:
        return _scrub(json.loads(raw.decode("utf-8-sig")))
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise ImportFailed(gettext("%(name)s is not valid JSON.") % {"name": name}) from exc


def _list(value, source: str, result: ImportResult) -> list:
    if isinstance(value, list):
        return value
    if value not in (None, [], ""):
        result.skip("invalid", source)
    return []


def _text(value) -> str:
    return value if isinstance(value, str) else ""


class _Images:
    """Images of one package (#336): read from ``content/`` on first reference,
    registered as side-channel ``ImportImage`` with a placeholder src."""

    def __init__(self, zf: zipfile.ZipFile, result: ImportResult):
        self.zf = zf
        self.result = result
        self.resolved: dict[str, str] = {}  # package path -> placeholder or ""

    def add(self, path, alt: str = "", credit: dict | None = None) -> str:
        """Placeholder src for ``content/<path>``, or "" (missing, unsafe,
        too large, or the import already holds MAX_IMPORT_IMAGES)."""
        path = _text(path).strip()
        if not is_package_path(path):
            return ""
        name = "content/" + path
        if name in self.resolved:
            src = self.resolved[name]
            if src and credit and not self.result.images[src].credit:
                # first met inline, now as ``media`` with its metadata
                self.result.images[src].credit = credit
            return src
        if self.result.images_full():
            return ""  # not cached: dedupe of earlier paths still applies
        try:
            data = safezip.read(self.zf, name, MAX_IMAGE_BYTES)
        except ImportFailed:
            data = b""
        src = self.result.add_image(
            ImportImage(data=data, filename=import_filename(path), alt=alt, credit=credit or {}), key=name,
        ) if data else ""
        self.resolved[name] = src
        return src

    def media(self, params: dict) -> tuple[str, bool]:
        """(``<p><img></p>`` of the question's ``media`` image, dropped)."""
        media = params.get("media")
        if not isinstance(media, dict) or not media.get("type"):
            return "", False
        mtype = media["type"]
        if not isinstance(mtype, dict) or not _text(mtype.get("library")).startswith("H5P.Image "):
            return "", True  # video/audio etc. are not taken over
        mparams = mtype.get("params") if isinstance(mtype.get("params"), dict) else {}
        file = mparams.get("file") if isinstance(mparams.get("file"), dict) else {}
        alt = "" if _is_true(mparams.get("decorative")) else _text(mparams.get("alt")).strip()
        src = self.add(file.get("path"), alt, _credit(mtype, file))
        if not src:
            return "", True
        return f"<p>{img_tag(src, alt)}</p>", False

    def html(self, raw) -> tuple[str, bool]:
        """Sanitized HTML with inline images resolved; (html, dropped)."""
        return clean_keeping_images(_text(raw), self.add)

    def option(self, raw) -> tuple[str, str, str, bool]:
        """(plain text, option image, its alt, dropped) of an answer: its first
        image becomes the option image, further ones are dropped."""
        raw = _text(raw)
        if not has_image(raw):
            return plain(raw), "", "", False  # verbatim, as before (#323)
        html, dropped = self.html(raw)
        srcs = image_srcs(html)
        unique = list(dict.fromkeys(srcs))
        alt = image_alts(html)[0] if srcs else ""
        return plain(html), unique[0] if unique else "", alt, dropped or len(unique) > 1


def _credit(mtype: dict, file: dict) -> dict:
    """Credit from the content metadata, else the older ``copyright`` object."""
    meta = mtype.get("metadata")
    if isinstance(meta, dict):
        credit = h5p_credit(meta, meta.get("license"), meta.get("licenseVersion"), meta.get("licenseExtras"))
    else:
        credit = {}
    # Sub-content metadata usually carries a title only; without author or
    # license ("has credit") the older copyright object may know more.
    old = file.get("copyright")
    if not (credit.get("author") or credit.get("license")) and isinstance(old, dict):
        old_credit = h5p_credit(old, old.get("license"), old.get("version"), "")
        if old_credit.get("author") or old_credit.get("license"):
            return old_credit
    return credit


def _question(raw, params: dict | None, images: _Images) -> tuple[str, bool]:
    """(html, an image was dropped); recorded only once the question is kept.
    A ``media`` image goes before the text, only if the question has text."""
    html, dropped = images.html(raw)
    if not html or params is None:
        return html, dropped
    media_html, media_dropped = images.media(params)
    return media_html + html, dropped or media_dropped


def _is_true(value) -> bool:
    """H5P stores flags as booleans, older content as "true"/"false" strings."""
    return value is True or str(value).lower() == "true"


def _too_many(items, result: ImportResult) -> bool:
    """Bail out before processing a huge answer list (finalize would skip it)."""
    if isinstance(items, list) and len(items) > MAX_OPTIONS:
        result.skip("too_many_options")
        return True
    return False


def _solution_text(raw: str) -> str:
    return plain(_BREAK_RE.sub("\n", raw))


def _options(answers, correct, images: _Images) -> tuple[list[dict], bool]:
    """Options from raw answer HTML; ``correct(i, answer)`` -> bool."""
    options, dropped = [], False
    for i, answer in enumerate(answers):
        text, image, alt, lost = images.option(answer if isinstance(answer, str) else answer.get("text"))
        option = {"text": text, "is_correct": correct(i, answer)}
        if image:
            option["image"] = image
            if alt:
                option["image_alt"] = alt
        options.append(option)
        dropped = dropped or lost
    return options, dropped


def _add_choice(result, question, options, source):
    text_html, image = question
    options, option_dropped = options
    if not text_html or len(options) < 2 or any(not (o["text"] or o.get("image")) for o in options):
        result.skip("invalid", source)
        return
    n_correct = sum(o["is_correct"] for o in options)
    if n_correct == 0:
        result.skip("invalid", source)
        return
    result.add({
        "kind": "multiple_choice" if n_correct > 1 else "single_choice",
        "text": text_html,
        "options": options,
    }, image or option_dropped)


def _multichoice(params: dict, result: ImportResult, images: _Images) -> None:
    answers = params.get("answers")
    if _too_many(answers, result):
        return
    answers = [a for a in (answers if isinstance(answers, list) else []) if isinstance(a, dict)]
    options = _options(answers, lambda i, a: _is_true(a.get("correct")), images)
    _add_choice(result, _question(params.get("question"), params, images), options, "H5P.MultiChoice")


def _truefalse(params: dict, result: ImportResult, images: _Images) -> None:
    text, image = _question(params.get("question"), params, images)
    if not text or str(params.get("correct")).lower() not in ("true", "false"):
        result.skip("invalid", "H5P.TrueFalse")
        return
    yes, no = true_false_labels()
    is_true = str(params["correct"]).lower() == "true"
    result.add({
        "kind": "single_choice",
        "text": text,
        "options": [{"text": yes, "is_correct": is_true}, {"text": no, "is_correct": not is_true}],
        "binary_choice": True,
    }, image)


def _singlechoiceset(params: dict, result: ImportResult, images: _Images) -> None:
    for choice in _list(params.get("choices"), "H5P.SingleChoiceSet", result):
        if not isinstance(choice, dict):
            result.skip("invalid", "H5P.SingleChoiceSet")
            continue
        answers = choice.get("answers")
        if _too_many(answers, result):
            continue
        answers = [a if isinstance(a, str) else "" for a in (answers if isinstance(answers, list) else [])]
        options = _options(answers, lambda i, a: i == 0, images)
        _add_choice(result, _question(choice.get("question"), None, images), options, "H5P.SingleChoiceSet")


def _essay(params: dict, result: ImportResult, images: _Images) -> None:
    text, image = _question(params.get("taskDescription"), params, images)
    if not text:
        result.skip("invalid", "H5P.Essay")
        return
    draft = {"kind": "open_text", "text": text, "options": []}
    solution = params.get("solution")
    sample = _solution_text(_text(solution.get("sample"))) if isinstance(solution, dict) else ""
    if sample:
        draft["model_solution"] = sample
    result.add(draft, image)


_HANDLERS = {
    "H5P.MultiChoice": _multichoice,
    "H5P.TrueFalse": _truefalse,
    "H5P.SingleChoiceSet": _singlechoiceset,
    "H5P.Essay": _essay,
}


def _walk(library, params, result: ImportResult, images: _Images, depth: int = 0) -> None:
    name = _text(library).split(" ")[0]
    if not name or not isinstance(params, dict) or depth > MAX_DEPTH:
        result.skip("invalid", name or "H5P")
        return
    handler = _HANDLERS.get(name)
    if handler:
        handler(params, result, images)
    elif name == "H5P.QuestionSet":
        for q in _list(params.get("questions"), "H5P.QuestionSet", result):
            if isinstance(q, dict):
                _walk(q.get("library"), q.get("params"), result, images, depth + 1)
    elif name == "H5P.Column":
        for item in _list(params.get("content"), "H5P.Column", result):
            inner = item.get("content") if isinstance(item, dict) else None
            if isinstance(inner, dict):
                _walk(inner.get("library"), inner.get("params"), result, images, depth + 1)
    else:
        result.skip("unsupported_type", name)


def parse(zf: zipfile.ZipFile) -> ImportResult:
    meta = _json(zf, "h5p.json")
    content = _json(zf, "content/content.json")
    library = meta.get("mainLibrary") if isinstance(meta, dict) else None
    result = ImportResult(format="h5p")
    _walk(library, content, result, _Images(zf, result))
    return result
