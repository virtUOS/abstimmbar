# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Prompts and server-side validation for the optional AI summary of
free-text answers (open_text): condense equivalent answers into short key
statements with counts, and group those statements (automatic themes, or the
question's own grouping criterion applied in a separate second call on the
finished statements, so the criterion never changes the statements).

Same contract as the word-cloud optimisation (``ai_wordcloud``): the model
only *groups* the numbered answers we send and names the groups; every count
is recomputed from the original aggregation (``words_with_counts``), so an
invented or repeated id simply drops out and can never inflate a tally. The
output shape is identical to ``ai_wordcloud.apply_optimization`` so the
presenter renders both with the same components:
``{merged: [{text, count, variants, keys}], clusters: [{label, count, words}]}``
(``text`` = statement label, ``variants`` = the original answer texts,
``keys`` = the answers' moderation keys)."""
import json

from basicbar_integrations import ai
from django.conf import settings
from django.utils import translation

from common.i18n_fields import resolve_translated_text, translated_map

from .ai_report import _plain
from .ai_wordcloud import OTHER_CLUSTER

LABEL_MAX = 80
CLUSTER_MAX = 60
ANSWER_MAX = 500   # characters per answer sent to the model
INPUT_MAX = 200    # answers per request (most frequent first)
ELLIPSIS = "…"
# Answers the model left out (or gave no label) are pooled under this label —
# never shown verbatim on the beamer (privacy: verbatim only in "Original").
LEFTOVER_LABEL = "Weitere Einzelantworten"

# Examples deliberately from a neutral domain (course feedback), not from any
# particular question, so the model learns the principle, not a topic.
RULE_EQUIVALENT = (
    "- Fasse Antworten mit derselben Kernaussage zu EINER Kernaussage "
    "zusammen, auch wenn sie ganz unterschiedlich formuliert, unterschiedlich "
    "ausführlich oder aus anderer Perspektive geschrieben sind. Entscheidend "
    "ist, was gemeint ist, nicht der Wortlaut. Beispiele (Feedback zu einer "
    "Vorlesung) für jeweils EINE Kernaussage:\n"
    "  • „Die Folien sind zu voll“ + „zu viel Text auf den Slides“\n"
    "  • „Tempo zu hoch“ + „es geht zu schnell“ + „man kommt beim "
    "Mitschreiben nicht hinterher“\n"
    "  • „Mikrofon ist hinten kaum zu hören“ + „akustisch schlecht zu "
    "verstehen“\n"
    "  Getrennt bleiben Antworten mit verschiedenen Kernaussagen, z. B. "
    "„mehr Beispiele“ und „der Praxisbezug fehlt“ oder „Tempo zu hoch“ und "
    "„Stoff ist zu schwer“ (benachbarte Punkte oder Ursache und Folge sind "
    "verschiedene Aussagen). Jede Kernaussage enthält genau EINEN Gedanken: "
    "Braucht das Label „und“, „durch“ oder „ermöglicht“, um mehrere Antworten "
    "abzudecken, sind es meist zwei Kernaussagen."
)
RULE_SIMILAR = (
    "- Fasse großzügig zusammen: Antworten, die denselben Aspekt betreffen, "
    "bilden EINE Kernaussage — auch verwandte Punkte, die sich ergänzen oder "
    "auseinander folgen (Beispiele aus Feedback zu einer Vorlesung: „mehr "
    "Beispiele“ + „der Praxisbezug fehlt“ + „Übungsaufgaben aus dem Alltag“ "
    "→ mehr Anwendungsbezug; „Folien sind zu voll“ + „Schrift zu klein“ → "
    "Folien schwer lesbar). Antworten zu klar verschiedenen Aspekten bleiben "
    "getrennt."
)


STATEMENTS_FIRST = (
    "Arbeite in zwei getrennten Schritten:\n"
    "Schritt 1 — Kernaussagen bilden: Fasse die Antworten AUSSCHLIESSLICH "
    "nach der folgenden Regel zu Kernaussagen zusammen; ein "
    "Gruppierungskriterium spielt dafür keine Rolle."
)
CLUSTER_ONLY = (
    "Schritt 2 — Gruppieren: Ordne erst danach jeder fertigen Kernaussage "
    "einen \"cluster\" zu. Das Gruppieren verändert die Kernaussagen nicht "
    "(keine Kernaussage wird dafür zusammengelegt, geteilt oder umformuliert)."
)
CORRECTNESS_RULE = (
    "- Fragt das Kriterium nach Richtigkeit (z. B. korrekt/falsch, "
    "richtig/teilweise/falsch), dann beurteile jede Kernaussage inhaltlich "
    "an der Frage und — falls angegeben — an der Musterlösung und dem "
    "Bewertungshinweis: Eine Kernaussage, die sinngemäß der Musterlösung "
    "entspricht, ist korrekt, auch wenn sie anders formuliert oder knapper "
    "ist. „Neutral“ bzw. „unklar“ nur, wenn sie die Frage weder richtig noch "
    "falsch beantwortet."
)
POLES_RULE = (
    "- Nennt das Kriterium mehrere Seiten oder Pole (z. B. „A vs. B“, "
    "„Vorteile/Nachteile“), dann ist JEDE Seite eine eigene Gruppe, benannt "
    "nach der Seite (z. B. „Vorteil für A“, „Vorteil für B“). Prüfe jede "
    "Kernaussage einzeln: Welcher Seite kommt sie HAUPTSÄCHLICH zugute bzw. "
    "welcher entspricht sie am ehesten? Verteile die Kernaussagen auf die "
    "Seiten; lege nicht alles auf eine Seite, nur weil es dort auch "
    "irgendwie passt."
)


def summary_system(*, merge_similar=False):
    """System prompt for the key statements (step 1). ``merge_similar``
    (question.wordcloud_merge_concepts) also merges answers with a similar
    core message; off = only equivalent answers. Statements are formed by the
    merge rule alone and get an automatic theme as ``cluster``. A presenter's
    grouping criterion is deliberately NOT part of this prompt: it is applied
    in a separate call (``grouping_system``) on the finished statements, so
    it can never change how answers are condensed."""
    return (
        "Du fasst die Freitext-Antworten einer Umfrage aus einer "
        "Lehrveranstaltung zu Kernaussagen zusammen. Du erhältst eine "
        "nummerierte Liste von Antworten mit Häufigkeiten.\n"
        + STATEMENTS_FIRST
        + "\n"
        + (RULE_SIMILAR if merge_similar else RULE_EQUIVALENT)
        + "\n"
        + CLUSTER_ONLY
        + "\n"
        "Regeln:\n"
        "- Jede Kernaussage listet in \"members\" die Nummern (\"id\") der "
        "Antworten, die sie zusammenfasst. Verwende nur vorgegebene "
        "Nummern; erfinde keine.\n"
        "- Jede Antwort gehört zu höchstens einer Kernaussage. Eine Antwort, "
        "die mit keiner anderen übereinstimmt, bildet eine eigene Kernaussage "
        "(auch z. B. „weiß nicht“ oder ein genannter Nachteil).\n"
        f"- \"label\" formuliert die Kernaussage knapp und neutral auf "
        f"Deutsch (höchstens {LABEL_MAX} Zeichen), ohne wörtliche Zitate, "
        "Namen oder persönliche Angaben aus den Antworten.\n"
        "- Bewerte die Antworten nicht (richtig/falsch spielt keine Rolle).\n"
        "- \"cluster\" ist ein kurzer thematischer Oberbegriff (1–3 "
        "Wörter). Kernaussagen zum selben Thema bekommen denselben "
        "\"cluster\"-Text; bilde wenige Themen.\n"
        "- Zähle oder gewichte nichts; die Häufigkeiten werden separat "
        "berechnet.\n"
        "- Antworte ausschließlich mit JSON."
    )


def grouping_system(grouping):
    """System prompt for step 2: assign the finished key statements to groups
    derived from the presenter's criterion. The statements are fixed."""
    return (
        "Du ordnest Kernaussagen aus einer Umfrage in einer "
        "Lehrveranstaltung Gruppen zu. Die Kernaussagen stehen fest: Du "
        "veränderst, teilst oder verbindest sie nicht.\n"
        f"Gruppierungskriterium: „{grouping.strip()}“.\n"
        "Regeln:\n"
        "- Leite aus dem Kriterium wenige aussagekräftige Gruppen ab.\n"
        + POLES_RULE
        + "\n"
        + CORRECTNESS_RULE
        + "\n"
        "- Kernaussagen, die zu keiner Gruppe passen, kommen in die Gruppe "
        f"\"{OTHER_CLUSTER}\".\n"
        f"- Gruppennamen höchstens {CLUSTER_MAX} Zeichen. Jede Kernaussage "
        "gehört zu genau einer Gruppe; verwende nur vorgegebene Nummern.\n"
        "- Antworte ausschließlich mit JSON."
    )


def question_context(question):
    """The question's own context for both prompts: its text as plain text in
    the content-canonical language (#33 — this also runs on a worker thread,
    whose active language is not the canonical one), plus the plain
    ``model_solution`` and ``evaluation_hint`` (empty when unset)."""
    with translation.override(settings.MODELTRANSLATION_DEFAULT_LANGUAGE):
        text = resolve_translated_text(translated_map(question, "text"))
    return {
        "question": _plain(text),
        "model_solution": _plain(question.model_solution),
        "hint": _plain(question.evaluation_hint),
    }


def context_block(context):
    """Prompt lines for ``question_context`` (empty without context);
    model solution and evaluation hint only when set."""
    if not context:
        return ""
    lines = []
    if context.get("question"):
        lines.append(f"Frage: {context['question']}")
    if context.get("model_solution"):
        lines.append(f"Musterlösung: {context['model_solution']}")
    if context.get("hint"):
        lines.append(f"Bewertungshinweis: {context['hint']}")
    return "\n".join(lines) + "\n\n" if lines else ""


def build_grouping_prompt(statements, context=None):
    """User prompt for step 2: the statements (``merged``), numbered from 1,
    after the question context (``question_context``)."""
    payload = [
        {"id": i, "text": st["text"], "count": st["count"]}
        for i, st in enumerate(statements, start=1)
    ]
    return (
        context_block(context)
        + "Kernaussagen:\n"
        + json.dumps(payload, ensure_ascii=False)
        + "\n\nGib JSON in genau dieser Form zurück:\n"
        '{"clusters": [{"label": "Vorteil für A", "members": [1, 3]}, '
        '{"label": "Vorteil für B", "members": [2]}]}'
    )


def _truncate(text, limit):
    return text if len(text) <= limit else text[: limit - 1] + ELLIPSIS


def build_summary_prompt(words, context=None):
    """User prompt: the question context (``question_context``, to understand
    the answers), then the (moderated) answers, numbered from 1 in input
    order."""
    payload = [
        {"id": i, "text": _truncate(str(w["text"]), ANSWER_MAX), "count": w["count"]}
        for i, w in enumerate(words[:INPUT_MAX], start=1)
    ]
    return (
        context_block(context)
        + "Antworten (mit Häufigkeit):\n"
        + json.dumps(payload, ensure_ascii=False)
        + "\n\nGib JSON in genau dieser Form zurück (das Beispiel zeigt nur das "
        "Format — was zusammengefasst wird, bestimmen allein die Regeln):\n"
        '{"statements": ['
        '{"label": "Vortragstempo ist zu hoch", "cluster": "Tempo", '
        '"members": [1, 4]}, '
        '{"label": "Mehr Beispiele gewünscht", "cluster": "Inhalt", '
        '"members": [2]}]}'
    )


def _as_id(value):
    """A 1-based answer id from the model (int or numeric string), else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def apply_summary(words, data):
    """Turn the model's statements into validated key statements + clusters.

    `words` is the ``words_with_counts`` output ([{text, count, keys}, …]) in
    the order sent by ``build_summary_prompt`` (id = position + 1). Unknown,
    out-of-range or repeated ids are ignored. Answers the model left out and
    statements without a label are pooled into ONE statement
    ``LEFTOVER_LABEL`` (cluster "Weitere", sorted last) — no answer text ever
    becomes a label — so the counts always sum to the total.
    """
    words = list(words[:INPUT_MAX])
    consumed = set()
    statements = []
    leftover = []
    raw = data.get("statements") if isinstance(data, dict) else None
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        members = item.get("members")
        if not isinstance(members, list):
            continue
        idxs = []
        for member in members:
            num = _as_id(member)
            if num is None or not 1 <= num <= len(words):
                continue
            if num - 1 in consumed:
                continue
            consumed.add(num - 1)
            idxs.append(num - 1)
        if not idxs:
            continue
        label = str(item.get("label") or "").strip()[:LABEL_MAX]
        if not label:
            leftover.extend(idxs)
            continue
        cluster = str(item.get("cluster") or "").strip()[:CLUSTER_MAX] or OTHER_CLUSTER
        statements.append(_statement(words, idxs, label, cluster))

    leftover += [i for i in range(len(words)) if i not in consumed]
    if leftover:
        statements.append(
            _statement(words, sorted(leftover), LEFTOVER_LABEL, OTHER_CLUSTER)
        )

    merged = sorted((_public(s) for s in statements), key=_statement_order)
    return {
        "clusters": _cluster_list((st["cluster"], _public(st)) for st in statements),
        "merged": merged,
    }


def _statement_order(statement):
    """By count, the pooled leftover statement always last."""
    return (statement["text"] == LEFTOVER_LABEL, -statement["count"])


def apply_grouping(summary, data):
    """Re-cluster finished key statements (``summary["merged"]``, numbered
    from 1 as in ``build_grouping_prompt``) by the model's step-2 answer
    ``{clusters: [{label, members: [ids]}]}``. The statements themselves stay
    exactly as they are; unknown/repeated ids are ignored and unassigned
    statements land in "Weitere"."""
    statements = list(summary["merged"])
    assigned = {}
    raw = data.get("clusters") if isinstance(data, dict) else None
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("members"), list):
            continue
        label = str(item.get("label") or "").strip()[:CLUSTER_MAX] or OTHER_CLUSTER
        for member in item["members"]:
            num = _as_id(member)
            if num is not None and 1 <= num <= len(statements) and num - 1 not in assigned:
                assigned[num - 1] = label
    pairs = (
        (
            OTHER_CLUSTER if st["text"] == LEFTOVER_LABEL
            else assigned.get(i, OTHER_CLUSTER),
            _public(st),
        )
        for i, st in enumerate(statements)
    )
    return {"clusters": _cluster_list(pairs), "merged": statements}


def summarize(words, *, grouping="", merge_similar=False, context=None, chat_json):
    """Key statements (step 1) and, only with a grouping criterion, a separate
    re-clustering of those fixed statements (step 2). ``context`` is
    ``question_context(question)`` (sent to both steps); ``chat_json`` is
    ``ai.chat_json``. An ``ai.AIError`` in step 1 propagates (the caller
    reports the failure); one in step 2 falls back to the step-1 statements
    with their automatic themes."""
    summary = apply_summary(
        words,
        chat_json(
            summary_system(merge_similar=merge_similar),
            build_summary_prompt(words, context),
        ),
    )
    if grouping and grouping.strip() and summary["merged"]:
        try:
            data = chat_json(
                grouping_system(grouping),
                build_grouping_prompt(summary["merged"], context),
            )
        except ai.AIError:
            return summary  # keep the statements, auto themes instead
        summary = apply_grouping(summary, data)
    return summary


def _cluster_list(pairs):
    """[(cluster label, statement)] → cluster list, biggest first, the
    catch-all "Weitere" always last; statements by count within a cluster."""
    clusters = {}
    for name, st in pairs:
        clusters.setdefault(name, []).append(st)
    cluster_list = [
        {
            "label": name,
            "count": sum(s["count"] for s in items),
            "words": sorted(items, key=_statement_order),
        }
        for name, items in clusters.items()
    ]
    cluster_list.sort(key=lambda c: (c["label"] == OTHER_CLUSTER, -c["count"]))
    return cluster_list


def _statement(words, idxs, label, cluster):
    keys = []
    for i in idxs:
        word = words[i]
        for key in word.get("keys") or [str(word["text"]).casefold()]:
            if str(key) not in keys:
                keys.append(str(key))
    return {
        "text": label,
        "cluster": cluster,
        "count": sum(words[i]["count"] for i in idxs),
        "variants": [words[i]["text"] for i in idxs],
        "keys": keys,
    }


def _public(statement):
    return {
        "text": statement["text"], "count": statement["count"],
        "variants": list(statement["variants"]), "keys": list(statement["keys"]),
    }
