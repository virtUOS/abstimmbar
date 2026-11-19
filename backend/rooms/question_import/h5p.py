# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Reader for H5P packages (#323), see the design spec, format 3."""
from __future__ import annotations

import json
import re
import zipfile

from django.utils.translation import gettext

from . import safezip
from .core import (
    ImportFailed,
    ImportResult,
    clean_without_images,
    plain,
    scrub_text,
    true_false_labels,
)

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


def _question_html(raw, result: ImportResult) -> str:
    html, dropped = clean_without_images(_text(raw))
    if dropped:
        result.skip("image_dropped")
    return html


def _solution_text(raw: str) -> str:
    return plain(_BREAK_RE.sub("\n", raw))


def _has_media(params: dict) -> bool:
    media = params.get("media")
    return isinstance(media, dict) and bool(media.get("type"))


def _add_choice(result, text_html, options, source, params=None):
    if not text_html or len(options) < 2 or any(not o["text"] for o in options):
        result.skip("invalid", source)
        return
    n_correct = sum(o["is_correct"] for o in options)
    if n_correct == 0:
        result.skip("invalid", source)
        return
    if params is not None and _has_media(params):
        result.skip("image_dropped")
    result.drafts.append({
        "kind": "multiple_choice" if n_correct > 1 else "single_choice",
        "text": text_html,
        "options": options,
    })


def _multichoice(params: dict, result: ImportResult) -> None:
    answers = params.get("answers")
    options = [
        {"text": plain(_text(a.get("text"))), "is_correct": bool(a.get("correct"))}
        for a in (answers if isinstance(answers, list) else [])
        if isinstance(a, dict)
    ]
    _add_choice(result, _question_html(params.get("question"), result), options, "H5P.MultiChoice", params)


def _truefalse(params: dict, result: ImportResult) -> None:
    text = _question_html(params.get("question"), result)
    if not text or str(params.get("correct")).lower() not in ("true", "false"):
        result.skip("invalid", "H5P.TrueFalse")
        return
    if _has_media(params):
        result.skip("image_dropped")
    yes, no = true_false_labels()
    is_true = str(params["correct"]).lower() == "true"
    result.drafts.append({
        "kind": "single_choice",
        "text": text,
        "options": [{"text": yes, "is_correct": is_true}, {"text": no, "is_correct": not is_true}],
        "binary_choice": True,
    })


def _singlechoiceset(params: dict, result: ImportResult) -> None:
    for choice in _list(params.get("choices"), "H5P.SingleChoiceSet", result):
        if not isinstance(choice, dict):
            result.skip("invalid", "H5P.SingleChoiceSet")
            continue
        answers = choice.get("answers")
        options = [
            {"text": plain(_text(a)), "is_correct": i == 0}
            for i, a in enumerate(answers if isinstance(answers, list) else [])
        ]
        _add_choice(result, _question_html(choice.get("question"), result), options, "H5P.SingleChoiceSet")


def _essay(params: dict, result: ImportResult) -> None:
    text = _question_html(params.get("taskDescription"), result)
    if not text:
        result.skip("invalid", "H5P.Essay")
        return
    draft = {"kind": "open_text", "text": text, "options": []}
    solution = params.get("solution")
    sample = _solution_text(_text(solution.get("sample"))) if isinstance(solution, dict) else ""
    if sample:
        draft["model_solution"] = sample
    result.drafts.append(draft)


_HANDLERS = {
    "H5P.MultiChoice": _multichoice,
    "H5P.TrueFalse": _truefalse,
    "H5P.SingleChoiceSet": _singlechoiceset,
    "H5P.Essay": _essay,
}


def _walk(library, params, result: ImportResult, depth: int = 0) -> None:
    name = _text(library).split(" ")[0]
    if not name or not isinstance(params, dict) or depth > MAX_DEPTH:
        result.skip("invalid", name or "H5P")
        return
    handler = _HANDLERS.get(name)
    if handler:
        handler(params, result)
    elif name == "H5P.QuestionSet":
        for q in _list(params.get("questions"), "H5P.QuestionSet", result):
            if isinstance(q, dict):
                _walk(q.get("library"), q.get("params"), result, depth + 1)
    elif name == "H5P.Column":
        for item in _list(params.get("content"), "H5P.Column", result):
            inner = item.get("content") if isinstance(item, dict) else None
            if isinstance(inner, dict):
                _walk(inner.get("library"), inner.get("params"), result, depth + 1)
    else:
        result.skip("unsupported_type", name)


def parse(zf: zipfile.ZipFile) -> ImportResult:
    meta = _json(zf, "h5p.json")
    content = _json(zf, "content/content.json")
    library = meta.get("mainLibrary") if isinstance(meta, dict) else None
    result = ImportResult(format="h5p")
    _walk(library, content, result)
    return result
