# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Reader for the simple text format (#323), see the design spec, format 1."""
from __future__ import annotations

import re

from rooms.sanitize import clean_html

from .core import MAX_OPTIONS, ImportResult, html_paragraphs

_QUESTION_RE = re.compile(r"^[FQ]\s*:\s*(.*)$", re.IGNORECASE)
_SOLUTION_RE = re.compile(r"^[LA]\s*:\s*(.*)$", re.IGNORECASE)
# A marker needs whitespace after it, so "-5 Grad" or "3.14 ist Pi" stay text.
_BULLET_RE = re.compile(r"^([*-])[ \t]+(.*)$")
_NUMBER_RE = re.compile(r"^(\d+)[.)][ \t]+(.*)$")
_BARE_MARKER_RE = re.compile(r"^(?:[*-]|\d+[.)])$")
_FOREIGN_BULLET_RE = re.compile(r"^[•‣◦▪●–—·]")
# Matched against the right-stripped head only: a leading ``\s*`` with
# ``search`` is quadratic on long runs of whitespace.
_MULTI_RE = re.compile(r"\[(?:mehrfach|multiple)\]$", re.IGNORECASE)
_TRUE_FALSE = ({"wahr", "richtig", "true"}, {"falsch", "false"})


class _Q:
    def __init__(self, lineno: int, head: str):
        self.lineno = lineno
        head = head.rstrip()
        m = _MULTI_RE.search(head)
        self.multi = bool(m)
        self.text_lines = [head[: m.start()].rstrip() if m else head]
        self.options: list[tuple[str, str]] = []  # (marker kind, text) kind: "*", "-", "n"
        self.solution: list[str] | None = None
        self.invalid = False


def _build(q: _Q, result: ImportResult) -> None:
    detail = f"Zeile {q.lineno}"
    text = "\n".join(q.text_lines).strip()
    if q.invalid or not text:
        result.skip("invalid", detail)
        return
    html = clean_html(html_paragraphs(text))
    kinds = {k for k, _ in q.options}
    if not q.options:
        draft = {"kind": "open_text", "text": html, "options": []}
        if q.solution:
            draft["model_solution"] = "\n".join(q.solution).strip()
        result.drafts.append(draft)
        return
    if len(q.options) > MAX_OPTIONS:
        result.skip("too_many_options")
        return
    if q.solution is not None or len(q.options) < 2 or ("n" in kinds and len(kinds) > 1):
        result.skip("invalid", detail)
        return
    if kinds == {"n"}:
        result.drafts.append({
            "kind": "ordering",
            "text": html,
            "options": [{"text": t, "is_correct": False} for _, t in q.options],
        })
        return
    options = [{"text": t, "is_correct": k == "*"} for k, t in q.options]
    n_correct = sum(o["is_correct"] for o in options)
    draft = {"kind": "single_choice", "text": html, "options": options}
    if q.multi or n_correct > 1:
        draft["kind"] = "multiple_choice"
    elif len(options) == 2:
        a, b = (t.strip().lower() for _, t in q.options)
        yes, no = _TRUE_FALSE
        if (a in yes and b in no) or (b in yes and a in no):
            draft["binary_choice"] = True
    result.drafts.append(draft)


def parse(text: str) -> ImportResult:
    result = ImportResult(format="simple")
    text = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    current: _Q | None = None
    stray_reported = False
    for lineno, raw in enumerate(text.split("\n"), start=1):
        line = raw.strip()
        if line.startswith(("#", "//")):
            continue
        m = _QUESTION_RE.match(line)
        if m:
            if current:
                _build(current, result)
            current = _Q(lineno, m.group(1).strip())
            stray_reported = False
            continue
        if not line:
            if current and current.solution is None and not current.options:
                current.text_lines.append("")
            continue
        if current is None:
            if not stray_reported:
                result.skip("invalid", f"Zeile {lineno}")
                stray_reported = True
            continue
        if _FOREIGN_BULLET_RE.match(line) or _BARE_MARKER_RE.match(line):
            current.invalid = True
            continue
        m = _SOLUTION_RE.match(line)
        if m:
            if current.options or current.solution is not None:
                current.invalid = True
            else:
                current.solution = [m.group(1).strip()]
            continue
        m = _NUMBER_RE.match(line)
        kind = "n" if m else None
        if not m:
            m = _BULLET_RE.match(line)
            kind = m.group(1) if m else None
        if m:
            if current.solution is not None or not m.group(2).strip():
                current.invalid = True
            else:
                current.options.append((kind, m.group(2).strip()))
            continue
        # plain continuation line
        if current.solution is not None:
            current.solution.append(line)
        elif current.options:
            current.invalid = True
        else:
            current.text_lines.append(line)
    if current:
        _build(current, result)
    return result
