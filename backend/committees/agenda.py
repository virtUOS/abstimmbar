# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Agenda outline of a committee meeting: TOP numbers and vote labels.

Sections and questions share one position space. A section opens a TOP; the
questions that belong to it (``question.section_id``) are its votes. A
question outside any open section forms a TOP of its own. A TOP with exactly
one vote labels it with the TOP number ("3"), with several "3a", "3b", ….
"""

from dataclasses import dataclass

from django.conf import settings
from django.utils import translation

from common.i18n_fields import resolve_translated_text, translated_map
from rooms.models import QuestionSet


@dataclass(frozen=True)
class Top:
    number: int
    section_id: int | None
    title: str
    description: str
    question_ids: tuple[int, ...]


def _canonical(value) -> str:
    with translation.override(settings.MODELTRANSLATION_DEFAULT_LANGUAGE):
        return resolve_translated_text(value)


def suffix(index: int) -> str:
    """0 -> "a", 25 -> "z", 26 -> "aa", 27 -> "ab"."""
    out = ""
    n = index + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(ord("a") + rem) + out
    return out


def tops(meeting: QuestionSet) -> list[Top]:
    # Section rows sort before question rows at equal position, then by id.
    rows = [(s.position, 0, s.pk, s) for s in meeting.sections.all()]
    rows += [(q.position, 1, q.pk, q) for q in meeting.questions.all()]
    rows.sort(key=lambda r: r[:3])

    # Each entry: [section | None, [question ids]]
    groups: list[list] = []
    open_section_id = None
    for _pos, kind, _pk, obj in rows:
        if kind == 0:
            groups.append([obj, []])
            open_section_id = obj.pk
        elif open_section_id is not None and obj.section_id == open_section_id:
            groups[-1][1].append(obj.pk)
        else:
            groups.append([None, [obj.pk]])
            open_section_id = None

    result = []
    for number, (section, qids) in enumerate(groups, start=1):
        if section is None:
            result.append(Top(number, None, "", "", tuple(qids)))
        else:
            result.append(Top(
                number,
                section.pk,
                _canonical(translated_map(section, "title")),
                section.description,
                tuple(qids),
            ))
    return result


def labels(meeting: QuestionSet) -> dict[int, str]:
    out: dict[int, str] = {}
    for top in tops(meeting):
        if len(top.question_ids) == 1:
            out[top.question_ids[0]] = str(top.number)
        else:
            for i, qid in enumerate(top.question_ids):
                out[qid] = f"{top.number}{suffix(i)}"
    return out


def top_of(meeting: QuestionSet, question_id: int) -> Top | None:
    return next((t for t in tops(meeting) if question_id in t.question_ids), None)


def top_by_section(meeting: QuestionSet, section_id: int) -> Top | None:
    return next((t for t in tops(meeting) if t.section_id == section_id), None)
