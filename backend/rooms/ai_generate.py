# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Prompt and validation for generating draft questions from a document's
text (Paket 5). The model proposes questions; we validate every one against
the allowed kinds and repair the answer-key shape (single = exactly one
correct, multiple = at least one) so a malformed suggestion never reaches
the editor. Nothing is persisted here — the teacher reviews and picks."""

ALLOWED_KINDS = ("single_choice", "multiple_choice", "true_false", "open_text")
KIND_LABELS = {
    "single_choice": "Single Choice (genau eine richtige Antwort)",
    "multiple_choice": "Multiple Choice (eine oder mehrere richtige Antworten)",
    "true_false": (
        "Wahr/Falsch (formuliere eine Aussage; die TN entscheiden, ob sie "
        "zutrifft – genau eine der beiden Optionen „Wahr\"/„Falsch\" ist korrekt)"
    ),
    "open_text": "Freitext (offene Antwort, keine Optionen)",
}
TEXT_MAX = 1000
OPTION_MAX = 500
MAX_OPTIONS = 8

LEVELS = ("mixed", "basics", "deep")
DEFAULT_LEVEL = "mixed"

# Prompt guidance per cognitive level (Bloom-inspired). German, since the
# generator prompt and canonical content language are German.
_LEVEL_HINTS = {
    "mixed": (
        "Mische die kognitiven Ebenen bewusst: einige Fragen zu Erinnern und "
        "Verstehen, einige zu Anwenden und Analysieren, und einige zu "
        "Reflexion und Transfer."
    ),
    "basics": (
        "Schwerpunkt auf Erinnern und Verstehen der zentralen Inhalte; "
        "einfache, klare Fragen."
    ),
    "deep": (
        "Schwerpunkt auf Analyse, Reflexion und Transfer; vermeide reine "
        "Reproduktionsfragen."
    ),
}


def generate_system():
    return (
        "Du erstellst aus bereitgestelltem Lehrmaterial Prüfungsfragen für "
        "eine Lehrveranstaltung. Formuliere klare, eigenständige Fragen und "
        "stütze dich ausschließlich auf das Material. Decke unterschiedliche "
        "kognitive Anforderungen ab – nicht nur Faktenwissen, sondern auch "
        "Analyse, Reflexion und Transfer; Freitextfragen sollen zum Denken "
        "anregen statt nur den Text nachzuerzählen. Bei Choice-Fragen sind "
        "die Antwortoptionen kurz und eindeutig; markiere die richtige(n) "
        "Antwort(en) korrekt (Single Choice: genau eine richtige). "
        "Gib bei Freitextfragen zusätzlich eine kurze Musterlösung an. "
        "Wenn das Material nicht als zusammenhängender, auswertbarer "
        "Lehrinhalt taugt, erfinde keine Fragen, sondern gib eine leere "
        "Fragenliste und einen kurzen Grund zurück. "
        "Antworte auf Deutsch und ausschließlich mit JSON."
    )


def build_generate_prompt(text, count, kinds, level=DEFAULT_LEVEL, guidance=""):
    allowed = [k for k in ALLOWED_KINDS if k in kinds] or list(ALLOWED_KINDS)
    kind_lines = "\n".join(f"- {k}: {KIND_LABELS[k]}" for k in allowed)
    hint = _LEVEL_HINTS.get(level, _LEVEL_HINTS[DEFAULT_LEVEL])
    # Optional free-text wishes from the teacher (#84). They steer emphasis
    # and style but must not override the material-fidelity and JSON rules
    # above, so they are framed explicitly as subordinate.
    guidance_block = ""
    if guidance and guidance.strip():
        guidance_block = (
            "Zusätzliche Vorgaben der Lehrperson (befolge sie, soweit sie dem "
            "Material treu bleiben – sie heben die obigen Regeln nicht auf):\n"
            f"{guidance.strip()}\n\n"
        )
    return (
        f"Erzeuge bis zu {count} Fragen. Erlaubte Fragetypen:\n{kind_lines}\n\n"
        f"Kognitive Ausrichtung: {hint}\n\n"
        f"{guidance_block}"
        "Material:\n"
        f"{text}\n\n"
        "Gib JSON in genau dieser Form zurück:\n"
        '{"questions": [{"kind": "single_choice", "text": "Fragetext", '
        '"options": [{"text": "Antwort", "is_correct": true}, '
        '{"text": "Antwort", "is_correct": false}]}], '
        '"unsuitable_reason": ""}\n'
        'Bei "open_text" lasse "options" weg oder leer und gib zusätzlich '
        '"model_solution": "..." an – eine knappe Musterlösung (Referenz- '
        'bzw. Idealantwort) in derselben Sprache wie die Frage. Bei '
        '"true_false" ist '
        '"text" die zu bewertende Aussage und "correct" ein Boolean (true, '
        'wenn die Aussage zutrifft); "options" entfällt. Setze '
        '"unsuitable_reason" nur, wenn sich aus dem Material keine sinnvollen '
        'Fragen bilden lassen; dann bleibt "questions" leer.'
    )


def build_drafts(data, kinds, count):
    allowed = {k for k in ALLOWED_KINDS if k in kinds} or set(ALLOWED_KINDS)
    questions = data.get("questions") if isinstance(data, dict) else None
    drafts = []
    for item in questions or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "")).strip()
        text = str(item.get("text", "")).strip()[:TEXT_MAX]
        if kind not in allowed or not text:
            continue
        if kind == "open_text":
            drafts.append({
                "kind": kind, "text": text, "options": [],
                "model_solution": str(item.get("model_solution", "")).strip()[:2000],
            })
        elif kind == "true_false":
            # A statement + its truth value. Normalise into a plain
            # single_choice draft with the fixed options Wahr/Falsch so the
            # editor and the rest of the pipeline need no special case (#79).
            correct_true = _true_false_correct(item)
            drafts.append({
                "kind": "single_choice",
                "text": text,
                "binary_choice": True,
                "options": [
                    {"text": "Wahr", "is_correct": correct_true},
                    {"text": "Falsch", "is_correct": not correct_true},
                ],
            })
        else:
            options = []
            for raw in item.get("options") or []:
                if not isinstance(raw, dict):
                    continue
                option_text = str(raw.get("text", "")).strip()[:OPTION_MAX]
                if option_text:
                    options.append(
                        {"text": option_text, "is_correct": bool(raw.get("is_correct"))}
                    )
            options = options[:MAX_OPTIONS]
            if len(options) < 2:
                continue  # a choice question needs at least two options
            _fix_answer_key(kind, options)
            drafts.append({"kind": kind, "text": text, "options": options})
        if len(drafts) >= count:
            break
    return drafts


def _true_false_correct(item):
    """Whether a true/false statement is true. Prefers the boolean `correct`
    field; falls back to inspecting an options list if the model used that
    shape instead; defaults to True when nothing is marked."""
    val = item.get("correct")
    if isinstance(val, bool):
        return val
    for raw in item.get("options") or []:
        if not isinstance(raw, dict) or not raw.get("is_correct"):
            continue
        label = str(raw.get("text", "")).strip().lower()
        if label in ("wahr", "true", "ja", "richtig"):
            return True
        if label in ("falsch", "false", "nein", "unwahr"):
            return False
    return True


def _fix_answer_key(kind, options):
    """Guarantee a usable answer key: single = exactly one correct,
    multiple = at least one. The first option is the fallback."""
    correct = [i for i, o in enumerate(options) if o["is_correct"]]
    if kind == "single_choice":
        keep = correct[0] if correct else 0
        for i, option in enumerate(options):
            option["is_correct"] = i == keep
    elif not correct:  # multiple_choice with nothing marked
        options[0]["is_correct"] = True


def unsuitable_reason(data):
    """The model's short reason for declining to produce questions, or ""."""
    if not isinstance(data, dict):
        return ""
    reason = data.get("unsuitable_reason")
    if not isinstance(reason, str):
        return ""
    return reason.strip()[:300]
