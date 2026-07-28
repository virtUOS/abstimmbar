# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Prompt builders for the question-editor AI assistance (distractors,
rephrasing). All prompts demand strict JSON; the model output is re-validated
in the views (never trusted)."""

_SYSTEM = (
    "Du bist ein Assistent für Lehrende und hilfst, Quizfragen zu verbessern. "
    "Antworte AUSSCHLIESSLICH mit striktem JSON in der geforderten Form, ohne "
    "weiteren Text, ohne Markdown. Verwende dieselbe Sprache wie die Frage."
)


def distractors_system():
    return _SYSTEM


def build_distractors_prompt(question, correct, existing, count):
    """Ask for `count` plausible-but-wrong answer options."""
    correct_block = "\n".join(f"- {c}" for c in correct) or "(keine markiert)"
    existing_block = "\n".join(f"- {e}" for e in existing) or "(keine)"
    return (
        f"Frage:\n{question}\n\n"
        f"Richtige Antwort(en):\n{correct_block}\n\n"
        f"Bereits vorhandene Antwortoptionen:\n{existing_block}\n\n"
        f"Erzeuge {count} plausible, aber eindeutig FALSCHE Antwortoptionen "
        "(Distraktoren) für diese Frage. Kurz und klar, keine Dopplungen der "
        "vorhandenen Optionen, keine richtige Antwort. "
        'Antworte als JSON: {"distractors": ["...", "..."]}'
    )


def rephrase_system():
    return _SYSTEM


def build_rephrase_prompt(question):
    """Ask for a few clearer rephrasings of the question text."""
    return (
        f"Frage:\n{question}\n\n"
        "Formuliere die Frage in 3 Varianten klarer und knapper, ohne den "
        "Sinn oder den Schwierigkeitsgrad zu verändern. "
        'Antworte als JSON: {"variants": ["...", "...", "..."]}'
    )
