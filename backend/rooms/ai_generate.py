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
# Short names for the focus/priority sentence (KIND_LABELS are too verbose there).
KIND_SHORT = {
    "single_choice": "Single Choice",
    "multiple_choice": "Multiple Choice",
    "true_false": "Wahr/Falsch",
    "open_text": "Freitext",
}
TEXT_MAX = 1000
OPTION_MAX = 500
MAX_OPTIONS = 8

LEVELS = ("mixed", "basics", "deep")
DEFAULT_LEVEL = "mixed"
# How much heavier a focused (priority) type weighs than a normal one in the
# target type distribution. 3 makes one focus among four types ~50 % / ~17 %.
FOCUS_WEIGHT = 3

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
        "stütze dich ausschließlich auf das Material. Sofern die Lehrperson "
        "nichts anderes vorgibt, deckst du unterschiedliche kognitive "
        "Anforderungen ab – nicht nur Faktenwissen, sondern auch Analyse, "
        "Reflexion und Transfer; Freitextfragen sollen zum Denken anregen "
        "statt nur den Text nachzuerzählen. Zusätzliche Vorgaben der "
        "Lehrperson setzt du verbindlich um; sie haben Vorrang vor diesen "
        "allgemeinen Hinweisen, nicht aber vor der Treue zum Material und dem "
        "Antwortformat. Bei Choice-Fragen sind "
        "die Antwortoptionen kurz und eindeutig; markiere die richtige(n) "
        "Antwort(en) korrekt (Single Choice: genau eine richtige). "
        "Gib bei Freitextfragen zusätzlich eine kurze Musterlösung an. "
        "Wenn das Material nicht als zusammenhängender, auswertbarer "
        "Lehrinhalt taugt, erfinde keine Fragen, sondern gib eine leere "
        "Fragenliste und einen kurzen Grund zurück. "
        "Antworte auf Deutsch und ausschließlich mit JSON."
    )


# Bounds for the "do not repeat" list of follow-up calls (#309): enough
# stems to steer the model away from repeats without crowding out the material.
AVOID_MAX_ITEMS = 40
AVOID_STEM_CHARS = 150


def _page_block(count, page_plan, page_label):
    """How to spread the questions over the pages/slides of this part (#304),
    plus a note on how the extraction marks tables, charts and notes (#305).
    Empty for unstructured (pasted) text."""
    if not page_label:
        return ""
    plural = "Folien" if page_label == "Folie" else "Seiten"
    block = (
        f"Das Material ist in {plural} gegliedert; jede beginnt mit einer Zeile "
        f"„=== {page_label} N ===“. Tabellen stehen zeilenweise (Spalten durch "
        "„|“ getrennt, erste Zeile = Kopfzeile), Diagramme mit Titel und Werten "
        "(„Diagramm:“), Sprechernotizen sind mit „Sprechernotizen:“ "
        "gekennzeichnet. Beziehe all das wie normalen Inhalt ein, auch mit "
        "konkreten Zahlen.\n"
    )
    if page_plan and sum(n for _, n in page_plan) == count:
        split = ", ".join(f"{page_label} {page}: {n}" for page, n in page_plan)
        block += (
            f"Verteile die Fragen so auf die {plural}: {split}. Jede Frage "
            f"bezieht sich auf die angegebene {page_label}.\n"
        )
    else:
        block += (
            f"Verteile die Fragen möglichst gleichmäßig über die {plural} dieses "
            "Materials, statt dich auf eine einzelne zu konzentrieren.\n"
        )
    return block + "\n"


def build_generate_prompt(
    text, count, kinds, level=DEFAULT_LEVEL, guidance="", focus_kinds=(), avoid=(),
    page_plan=(), page_label="",
):
    allowed = [k for k in ALLOWED_KINDS if k in kinds] or list(ALLOWED_KINDS)
    kind_lines = "\n".join(f"- {k}: {KIND_LABELS[k]}" for k in allowed)
    hint = _LEVEL_HINTS.get(level, _LEVEL_HINTS[DEFAULT_LEVEL])
    # Type distribution: give the model an explicit target ratio (it follows a
    # concrete percentage far better than a vague "mostly X"). A focused type
    # (the teacher's priority) weighs FOCUS_WEIGHT, others weigh 1 — so one focus
    # among four types lands at ~50 %, the rest ~17 % each. An all-focus set
    # carries no priority, so it falls back to an even split.
    focus = [k for k in allowed if k in (focus_kinds or ())]
    if len(focus) >= len(allowed):
        focus = []
    weights = {k: (FOCUS_WEIGHT if k in focus else 1) for k in allowed}
    total_weight = sum(weights.values())
    mix = ", ".join(
        f"{KIND_SHORT[k]} ~{round(100 * weights[k] / total_weight)} %" for k in allowed
    )
    focus_block = (
        "Verteile die Fragetypen in deiner Antwort möglichst nach diesem "
        f"Verhältnis: {mix}.\n\n"
    )
    # Optional free-text wishes from the teacher (#84). Binding (#306): they
    # come right after the material — the last thing before the output
    # format — and override the type mix, the cognitive level and the page
    # spread; only material fidelity, the allowed kinds, the count and the
    # JSON format stay fixed.
    guidance = (guidance or "").strip()
    guidance_block = ""
    if guidance:
        hint += (
            " (Gilt nur, soweit die verbindlichen Vorgaben der Lehrperson unten "
            "nichts anderes verlangen.)"
        )
        guidance_block = (
            "Verbindliche Vorgaben der Lehrperson – setze sie bei der Auswahl "
            "und Formulierung der Fragen um:\n"
            f"{guidance}\n"
            "Diese Vorgaben haben Vorrang vor den obigen Hinweisen zur "
            "Verteilung der Fragetypen, zur kognitiven Ausrichtung und zur "
            "Verteilung über das Material; verlangen sie z. B. Fragen zu "
            "konkreten Fakten oder Zahlen, stelle solche Fragen. Unverändert "
            "gelten nur: Fragen ausschließlich aus dem Material, nur die "
            f"erlaubten Fragetypen, genau {count} Fragen und das JSON-Format "
            "unten.\n\n"
        )
    # Follow-up calls for the same material list what is already there, so
    # the model adds new questions instead of repeating earlier ones (#309).
    avoid_block = ""
    stems = [" ".join(str(a).split())[:AVOID_STEM_CHARS] for a in (avoid or ())]
    stems = [s for s in stems if s][-AVOID_MAX_ITEMS:]
    if stems:
        avoid_block = (
            "Diese Fragen gibt es bereits – wiederhole sie nicht und formuliere "
            "keine inhaltsgleichen Varianten, sondern neue Fragen zu anderen "
            "Aspekten des Materials:\n"
            + "\n".join(f"- {s}" for s in stems)
            + "\n\n"
        )
    # Where a question came from (#304): only asked for when the material
    # carries page markers; shown to the teacher in the review list.
    source_field = '"source_page": 1, ' if page_label else ""
    source_note = (
        f'"source_page" ist die Nummer der {page_label}, auf die sich die Frage '
        "bezieht. "
        if page_label else ""
    )
    return (
        f"Erzeuge genau {count} Fragen. Erlaubte Fragetypen:\n{kind_lines}\n\n"
        f"{focus_block}"
        f"Kognitive Ausrichtung: {hint}\n\n"
        f"{_page_block(count, page_plan, page_label)}"
        f"{avoid_block}"
        "Material:\n"
        f"{text}\n\n"
        f"{guidance_block}"
        "Gib JSON in genau dieser Form zurück:\n"
        '{"questions": [{"kind": "single_choice", "text": "Fragetext", '
        f"{source_field}"
        '"options": [{"text": "Antwort", "is_correct": true}, '
        '{"text": "Antwort", "is_correct": false}]}], '
        '"unsuitable_reason": ""}\n'
        f"{source_note}"
        'Bei "open_text" lasse "options" weg oder leer und gib zusätzlich '
        '"model_solution": "..." an – eine knappe Musterlösung (Referenz- '
        'bzw. Idealantwort) in derselben Sprache wie die Frage. Bei '
        '"true_false" ist '
        '"text" die zu bewertende Aussage und "correct" ein Boolean (true, '
        'wenn die Aussage zutrifft); "options" entfällt. Setze '
        '"unsuitable_reason" nur, wenn sich aus dem Material keine sinnvollen '
        'Fragen bilden lassen; dann bleibt "questions" leer.'
    )


def _source_page(item, pages):
    """The question's ``source_page`` if it names one of ``pages``, else
    None (missing, malformed or out of range — tolerated, #304)."""
    value = item.get("source_page")
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return value if isinstance(value, int) and value in pages else None


def build_drafts(data, kinds, count, pages=()):
    pages = set(pages or ())
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
        page = _source_page(item, pages)
        if page is not None:
            drafts[-1]["source_page"] = page
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
