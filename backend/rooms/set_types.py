# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Declarative rules per QuestionSet.type (#75): which question kinds a set of
each type may contain, whether free text needs a model solution, and how the
set is run. Adding a new set type is one entry here (+ the frontend mirror in
`frontend/src/setTypes.ts`). Kept as data, not scattered if-branches."""

from .models import Question, QuestionSet

_ALL_KINDS = tuple(kind for kind, _ in Question.Kind.choices)

SET_TYPES = {
    QuestionSet.SetType.LIVE_POLL: {
        "run_mode": "live",
        "allowed_kinds": _ALL_KINDS,
        "open_text_requires_solution": False,
    },
    QuestionSet.SetType.SELF_PACED: {
        "run_mode": "self_paced",
        "allowed_kinds": _ALL_KINDS,
        "open_text_requires_solution": False,
    },
    QuestionSet.SetType.SELF_CHECK: {
        # Only kinds with an auto-checkable answer / shown solution.
        "run_mode": None,  # standing link, no teacher-started run (Phase 3)
        "allowed_kinds": ("single_choice", "multiple_choice", "ordering", "open_text"),
        "open_text_requires_solution": True,
    },
}


def _rules(set_type):
    return SET_TYPES.get(set_type, SET_TYPES[QuestionSet.SetType.LIVE_POLL])


def allowed_kinds(set_type) -> tuple:
    return _rules(set_type)["allowed_kinds"]


def requires_solution(set_type) -> bool:
    return _rules(set_type)["open_text_requires_solution"]


def run_mode(set_type):
    return _rules(set_type)["run_mode"]
