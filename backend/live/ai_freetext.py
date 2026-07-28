# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Prompt and validation for the optional AI evaluation of free-text answers:
sort each distinct answer into one of the question's categories (a chosen
scale — correctness, sentiment, or free labels). Non-destructive.

The model only *labels* the answers we send. We recompute counts from the
original aggregation and coerce any unknown label to the middle category;
answers the model skips fall back the same way — so a stray label can never
invent an answer or a tally."""
import json

from .ai_report import _plain

# Default scale (correctness) — kept for existing questions and as a fallback.
VERDICTS = ("korrekt", "unklar", "falsch")
NOTE_MAX = 200
REFERENCE_MAX = 2000


def clean_categories(categories):
    """A safe ordered list of 2–5 non-empty category labels (else the default
    correctness scale). Trims, de-duplicates case-insensitively, caps at 40
    chars to match Vote.ai_verdict."""
    result, seen = [], set()
    for raw in categories or []:
        label = str(raw).strip()[:40]
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            result.append(label)
    if not 2 <= len(result) <= 5:
        return list(VERDICTS)
    return result


def middle_category(categories):
    """The fallback bucket for unsure/unmatched answers — the middle label,
    which is „unklar"/„neutral" for the two presets."""
    cats = clean_categories(categories)
    return cats[len(cats) // 2]


def evaluate_system(categories):
    cats = clean_categories(categories)
    listed = " · ".join(f'"{c}"' for c in cats)
    return (
        "Du ordnest freie Textantworten von Teilnehmenden auf eine Frage aus "
        "einer Lehrveranstaltung jeweils genau EINER der folgenden Kategorien "
        f"zu: {listed}. "
        "Ist eine erwartete Antwort bzw. ein Kriterium angegeben, richte dich "
        "danach; sonst beurteile anhand der Frage. Passt keine Kategorie "
        f"eindeutig oder bist du unsicher, nutze \"{middle_category(cats)}\". "
        "Gib je Antwort optional eine sehr kurze Begründung. Verwende als "
        "\"text\" exakt die vorgegebenen Antworten und als \"verdict\" genau "
        "eine der Kategorien. Antworte ausschließlich mit JSON."
    )


def build_evaluate_prompt(question_text, reference, answers, categories):
    cats = clean_categories(categories)
    lines = [f"Frage: {_plain(question_text) or '(ohne Fragentext)'}"]
    if reference:
        lines.append(f"Erwartete Antwort / Kriterium: {reference}")
    lines.append(f"Kategorien: {', '.join(cats)}")
    lines.append("Antworten:")
    lines.append(json.dumps([a["text"] for a in answers], ensure_ascii=False))
    lines.append("")
    lines.append(
        'Gib JSON zurück: {"items": [{"text": "<Antwort>", '
        '"verdict": "<eine der Kategorien>", "note": "kurze Begründung"}]}'
    )
    return "\n".join(lines)


def apply_evaluation(answers, data, categories):
    """Group the answers by validated category, recomputing counts locally."""
    cats = clean_categories(categories)
    valid = {c.casefold(): c for c in cats}
    fallback = middle_category(cats)

    index = {}
    for entry in answers:
        key = entry["text"].casefold()
        if key in index:
            index[key]["count"] += entry["count"]
        else:
            index[key] = {"text": entry["text"], "count": entry["count"]}

    consumed = set()
    buckets = {c: [] for c in cats}
    items = data.get("items") if isinstance(data, dict) else None
    for item in items or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("text", "")).strip().casefold()
        if key not in index or key in consumed:
            continue
        consumed.add(key)
        verdict = valid.get(str(item.get("verdict", "")).strip().casefold(), fallback)
        buckets[verdict].append(
            {
                "text": index[key]["text"],
                "count": index[key]["count"],
                "note": str(item.get("note", "")).strip()[:NOTE_MAX],
            }
        )

    # Answers the model ignored fall into the fallback category.
    for key, entry in index.items():
        if key not in consumed:
            buckets[fallback].append(
                {"text": entry["text"], "count": entry["count"], "note": ""}
            )

    groups = [
        {
            "verdict": verdict,
            "count": sum(i["count"] for i in buckets[verdict]),
            "items": sorted(buckets[verdict], key=lambda i: -i["count"]),
        }
        for verdict in cats
    ]
    return {"groups": groups, "categories": cats}
