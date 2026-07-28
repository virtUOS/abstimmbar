# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Prompt for the optional AI short report of one run's results.

We feed the model the already-aggregated, anonymous numbers (option counts,
Likert split, top word-cloud/free-text terms) and ask for a compact German
Markdown summary. The model must not invent figures; it only phrases what we
send. The report is display-only — nothing is stored back."""
import re

from common.i18n_fields import resolve_translated_text

KIND_LABELS = {
    "single_choice": "Single Choice",
    "multiple_choice": "Multiple Choice",
    "yes_no": "Ja/Nein",
    "likert": "Likert-Skala",
    "word_cloud": "Wortwolke",
    "open_text": "Freitext",
}
TOP_WORDS = 15
REPORT_MAX = 4000


def _plain(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def report_system():
    return (
        "Du erstellst einen kurzen, sachlichen Kurzbericht über die "
        "Ergebnisse einer Umfrage aus einer Lehrveranstaltung. Antworte auf "
        "Deutsch in Markdown und kompakt (höchstens ~150 Wörter): eine Zeile "
        "Überblick, danach wenige Stichpunkte zu Auffälligkeiten (klare "
        "Mehrheiten, Uneinigkeit, häufige Freitext-Themen, auffällige "
        "Verteilungen). Verwende ausschließlich die angegebenen Zahlen und "
        "Begriffe und erfinde nichts. Antworte ausschließlich mit JSON der "
        'Form {"report": "..."}.'
    )


def build_report_prompt(set_title, results):
    lines = [
        f"Fragenset: {set_title}",
        f"Antworten insgesamt: {results['votes_total']}",
        "",
    ]
    for question in results["questions"]:
        label = KIND_LABELS.get(question["kind"], question["kind"])
        # question["text"]/option["text"] may be a {de, en} map (#33 MR2,
        # options_with_counts) or a plain string; resolve either to one
        # canonical string — the model must never see a dict.
        text = _plain(resolve_translated_text(question["text"])) or "(ohne Fragentext)"
        lines.append(
            f"Frage {question['position'] + 1} [{label}]: {text} "
            f"— {question['votes']} Antworten"
        )
        for option in question.get("options") or []:
            mark = " (richtige Antwort)" if option.get("is_correct") else ""
            option_text = resolve_translated_text(option["text"])
            lines.append(f"  - {option_text}: {option['count']}{mark}")
        likert = question.get("likert")
        if likert:
            lines.append(
                f"  Zustimmung {likert['agree_pct']} % / Neutral "
                f"{likert['neutral_pct']} % / Ablehnung {likert['disagree_pct']} % "
                f"(Enthaltungen {likert['abstentions']})"
            )
        words = question.get("words") or []
        if words:
            top = ", ".join(f"{w['text']} ({w['count']})" for w in words[:TOP_WORDS])
            lines.append(f"  Begriffe: {top}")
    lines.append("")
    lines.append(
        'Gib den Kurzbericht als JSON zurück: {"report": "<Markdown-Text>"}.'
    )
    return "\n".join(lines)
