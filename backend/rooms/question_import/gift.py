# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Reader for the Moodle GIFT format (#323), see the design spec, format 2.

Reference: https://docs.moodle.org/en/GIFT_format
"""
from __future__ import annotations

import re

from rooms.sanitize import clean_html

from .core import ImportResult, clean_without_images, html_paragraphs, plain, true_false_labels

_ESCAPABLE = "~=#{}:\\n"
_TITLE_RE = re.compile(r"^\s*::((?:\\.|(?!::).)*)::", re.DOTALL)
_FORMAT_RE = re.compile(r"^\s*\[(html|markdown|plain|moodle)\]", re.IGNORECASE)
_WEIGHT_RE = re.compile(r"^\s*%(-?\d+(?:\.\d+)?)%")
_TITLE_LINE_RE = re.compile(r"^\s*::[^:\n]+::", re.MULTILINE)


def _unescape(s: str) -> str:
    return re.sub(
        r"\\([~=#{}:\\n])", lambda m: "\n" if m.group(1) == "n" else m.group(1), s
    )


def _unescaped(s: str, chars: str) -> list[tuple[int, str]]:
    """Positions of unescaped characters from ``chars``."""
    out: list[tuple[int, str]] = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s) and s[i + 1] in _ESCAPABLE:
            i += 2
            continue
        if c in chars:
            out.append((i, c))
        i += 1
    return out


def _has_arrow(s: str) -> bool:
    return any(s[p + 1 : p + 2] == ">" for p, _ in _unescaped(s, "-"))


def _brace_pairs(s: str) -> list[tuple[int, int]] | None:
    """Top-level unescaped ``{...}`` spans; ``None`` if unbalanced."""
    pairs: list[tuple[int, int]] = []
    depth = 0
    start = 0
    for pos, c in _unescaped(s, "{}"):
        if c == "{":
            if depth == 0:
                start = pos
            depth += 1
        else:
            depth -= 1
            if depth < 0:
                return None
            if depth == 0:
                pairs.append((start, pos))
    return None if depth else pairs


def _blocks(text: str) -> list[tuple[int, str]]:
    """Blank-line separated blocks, minus ``//`` comments and ``$CATEGORY:`` lines."""
    blocks: list[tuple[int, str]] = []
    cur: list[str] = []
    first = 0

    def flush() -> None:
        if cur:
            blocks.append((first, "\n".join(cur)))
            cur.clear()

    for lineno, raw in enumerate(text.split("\n"), start=1):
        line = raw.strip()
        if not line:
            flush()
            continue
        if line.startswith("//") or line.upper().startswith("$CATEGORY:"):
            continue
        if not cur:
            first = lineno
        cur.append(line)
    flush()
    return blocks


def _segments(content: str) -> list[tuple[str, str]]:
    """Split an answer block at unescaped ``=``/``~`` into (marker, raw text)."""
    marks = _unescaped(content, "=~")
    return [
        (m, content[p + 1 : marks[i + 1][0] if i + 1 < len(marks) else len(content)])
        for i, (p, m) in enumerate(marks)
    ]


def _strip_feedback(raw: str) -> str:
    hashes = _unescaped(raw, "#")
    return raw[: hashes[0][0]] if hashes else raw


def _build(lineno: int, body: str, result: ImportResult) -> None:
    detail = f"Zeile {lineno}"
    m = _TITLE_RE.match(body)
    if m:
        body = body[m.end():]
    fmt = "moodle"
    m = _FORMAT_RE.match(body)
    if m:
        fmt = m.group(1).lower()
        body = body[m.end():]
    pairs = _brace_pairs(body)
    if pairs is None:
        result.skip("invalid", detail)
        return
    if not pairs:
        result.skip("unsupported_type", "description")
        return
    start, end = pairs[-1]
    if len(pairs) > 1 or body[end + 1 :].strip():
        result.skip("unsupported_type", "cloze")
        return
    question = body[:start].strip()
    content = body[start + 1 : end]
    for pos, _ in _unescaped(content, "#"):
        if content.startswith("####", pos):
            content = content[:pos]  # general feedback tail
            break
    if not question:
        result.skip("invalid", detail)
        return

    html = _question_html(question, fmt, result)
    stripped = content.strip()
    if stripped.startswith("#"):
        result.skip("unsupported_type", "numerical")
        return
    if any(_has_arrow(_strip_feedback(raw)) for _, raw in _segments(content)):
        result.skip("unsupported_type", "matching")
        return

    flag = _strip_feedback(stripped).strip().upper()
    if flag in ("T", "TRUE", "F", "FALSE"):
        wahr, falsch = true_false_labels()
        right = flag in ("T", "TRUE")
        result.drafts.append({
            "kind": "single_choice",
            "text": html,
            "binary_choice": True,
            "options": [
                {"text": wahr, "is_correct": right},
                {"text": falsch, "is_correct": not right},
            ],
        })
        return
    if not stripped:
        result.drafts.append({"kind": "open_text", "text": html, "options": []})
        return

    segs = _segments(content)
    if not segs:
        result.skip("invalid", detail)
        return
    first_marker = _unescaped(content, "=~")[0][0]
    if _strip_feedback(content[:first_marker]).strip():
        result.skip("invalid", detail)
        return
    options: list[dict] = []
    for marker, raw in segs:
        raw = _strip_feedback(raw)
        weight = None
        w = _WEIGHT_RE.match(raw)
        if w:
            weight = float(w.group(1))
            raw = raw[w.end():]
        text = _unescape(raw).strip()
        if fmt == "html":
            text = plain(text)
        if not text:
            result.skip("invalid", detail)
            return
        is_correct = weight > 0 if weight is not None else marker == "="
        options.append({"text": text, "is_correct": is_correct})

    if all(m == "=" for m, _ in segs):
        result.drafts.append({
            "kind": "open_text",
            "text": html,
            "options": [],
            "model_solution": options[0]["text"],
        })
        return
    if len(options) < 2:
        result.skip("invalid", detail)
        return
    n_correct = sum(o["is_correct"] for o in options)
    result.drafts.append({
        "kind": "multiple_choice" if n_correct > 1 else "single_choice",
        "text": html,
        "options": options,
    })


def _question_html(question: str, fmt: str, result: ImportResult) -> str:
    text = _unescape(question)
    if fmt != "html":
        return clean_html(html_paragraphs(text))
    html, dropped = clean_without_images(text)
    if dropped:
        result.skip("image_dropped")
    return html


def parse(text: str) -> ImportResult:
    result = ImportResult(format="gift")
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    for lineno, body in _blocks(text):
        _build(lineno, body, result)
    return result


def looks_like_gift(text: str) -> bool:
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    if _TITLE_LINE_RE.search(text):
        return True
    for _, body in _blocks(text):
        braces = _unescaped(body.rstrip(), "{}")
        if (
            braces
            and body.rstrip().endswith("}")
            and braces[-1][1] == "}"
            and any(c == "{" for _, c in braces)
        ):
            return True
    return False
