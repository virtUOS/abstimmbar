# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Prompts and server-side validation for the optional AI summary of
free-text answers (open_text): condense equivalent answers into short key
statements with counts, and group those statements (automatic themes or the
question's own grouping criterion).

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

from .ai_wordcloud import OTHER_CLUSTER

LABEL_MAX = 80
CLUSTER_MAX = 60
ANSWER_MAX = 500   # characters per answer sent to the model
INPUT_MAX = 200    # answers per request (most frequent first)
ELLIPSIS = "…"

RULE_EQUIVALENT = (
    "- Fasse NUR Antworten zusammen, die inhaltlich dasselbe aussagen — "
    "also gleichbedeutend sind, auch wenn sie anders formuliert oder "
    "geschrieben sind (z. B. „Man kennt die Namen nicht“ / „Keine Namen“). "
    "Antworten, die verschiedene Aspekte nennen, bleiben GETRENNT, auch wenn "
    "sie thematisch verwandt sind. Im Zweifel NICHT zusammenfassen."
)
RULE_SIMILAR = (
    "- Fasse Antworten zusammen, die dieselbe oder eine sehr ähnliche "
    "Kernaussage treffen, auch wenn sie unterschiedlich ausführlich sind "
    "oder leicht unterschiedliche Nuancen setzen. Antworten mit klar "
    "verschiedenen Kernaussagen bleiben GETRENNT; das thematische Ordnen "
    "passiert getrennt über \"cluster\"."
)


def summary_system(grouping="", *, merge_similar=False):
    """System prompt for key statements + grouping. ``grouping`` (optional) is
    the presenter's grouping criterion; empty falls back to automatic themes.
    ``merge_similar`` (question.wordcloud_merge_concepts) also merges answers
    with a similar core message; off = only equivalent answers."""
    if grouping and grouping.strip():
        cluster_rule = (
            "- \"cluster\" ordnet die Aussage nach folgendem Kriterium ein: "
            f"„{grouping.strip()}“. Bilde daraus wenige aussagekräftige "
            "Gruppen; Aussagen, die nicht passen, bekommen den cluster "
            f"\"{OTHER_CLUSTER}\".\n"
        )
    else:
        cluster_rule = (
            "- \"cluster\" ist ein kurzer thematischer Oberbegriff (1–3 "
            "Wörter). Aussagen zum selben Thema bekommen denselben "
            "\"cluster\"-Text; bilde wenige Themen.\n"
        )
    return (
        "Du fasst die Freitext-Antworten einer Umfrage aus einer "
        "Lehrveranstaltung zu Kernaussagen zusammen. Du erhältst eine "
        "nummerierte Liste von Antworten mit Häufigkeiten.\n"
        "Zusammenfassen:\n"
        + (RULE_SIMILAR if merge_similar else RULE_EQUIVALENT)
        + "\n"
        "Regeln:\n"
        "- Jede Kernaussage listet in \"members\" die Nummern (\"id\") der "
        "Antworten, die sie zusammenfasst. Verwende nur vorgegebene "
        "Nummern; erfinde keine.\n"
        "- Jede Antwort gehört zu höchstens einer Kernaussage. Antworten, die "
        "mit keiner anderen übereinstimmen, bilden eine eigene Kernaussage.\n"
        f"- \"label\" formuliert die Kernaussage knapp und neutral auf "
        f"Deutsch (höchstens {LABEL_MAX} Zeichen), ohne wörtliche Zitate, "
        "Namen oder persönliche Angaben aus den Antworten.\n"
        "- Bewerte die Antworten nicht (richtig/falsch spielt keine Rolle).\n"
        + cluster_rule
        + "- Zähle oder gewichte nichts; die Häufigkeiten werden separat "
        "berechnet.\n"
        "- Antworte ausschließlich mit JSON."
    )


def _truncate(text, limit):
    return text if len(text) <= limit else text[: limit - 1] + ELLIPSIS


def build_summary_prompt(words):
    """User prompt: the (moderated) answers, numbered from 1 in input order."""
    payload = [
        {"id": i, "text": _truncate(str(w["text"]), ANSWER_MAX), "count": w["count"]}
        for i, w in enumerate(words[:INPUT_MAX], start=1)
    ]
    return (
        "Antworten (mit Häufigkeit):\n"
        + json.dumps(payload, ensure_ascii=False)
        + "\n\nGib JSON in genau dieser Form zurück (das Beispiel zeigt nur das "
        "Format — was zusammengefasst wird, bestimmen allein die Regeln):\n"
        '{"statements": ['
        '{"label": "Teilnehmende bleiben unerkannt", "cluster": "Anonymität", '
        '"members": [1, 4]}, '
        '{"label": "Ehrlichere Antworten", "cluster": "Qualität", '
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
    out-of-range or repeated ids are ignored; answers the model left out keep
    their own statement (label = truncated answer, cluster "Weitere"), so the
    counts always sum to the total.
    """
    words = list(words[:INPUT_MAX])
    consumed = set()
    statements = []
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
            top = max(idxs, key=lambda i: words[i]["count"])
            label = _truncate(str(words[top]["text"]), LABEL_MAX)
        cluster = str(item.get("cluster") or "").strip()[:CLUSTER_MAX] or OTHER_CLUSTER
        statements.append(_statement(words, idxs, label, cluster))

    for i, word in enumerate(words):
        if i not in consumed:
            statements.append(_statement(
                words, [i], _truncate(str(word["text"]), LABEL_MAX), OTHER_CLUSTER
            ))

    clusters = {}
    for st in statements:
        clusters.setdefault(st["cluster"], []).append(_public(st))
    cluster_list = [
        {
            "label": name,
            "count": sum(s["count"] for s in items),
            "words": sorted(items, key=lambda s: -s["count"]),
        }
        for name, items in clusters.items()
    ]
    # Biggest clusters first; the catch-all "Weitere" always sinks to the end.
    cluster_list.sort(key=lambda c: (c["label"] == OTHER_CLUSTER, -c["count"]))
    merged = sorted((_public(s) for s in statements), key=lambda s: -s["count"])
    return {"clusters": cluster_list, "merged": merged}


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
