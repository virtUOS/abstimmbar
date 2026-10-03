# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Prompts and server-side validation for the optional AI word-cloud
optimisation (merge spelling variants/synonyms/similar concepts as
configured per question, form thematic clusters).

The model only *groups* the words we send; it never supplies counts. We
recompute every count from the original aggregation, so a hallucinated or
mistyped member simply drops out and can never inflate a tally."""
import json

LABEL_MAX = 100
CLUSTER_MAX = 60
OTHER_CLUSTER = "Weitere"


# Merge rule blocks for the consolidated view; which ones the prompt carries
# depends on the question's wordcloud_merge_* switches. Case is always merged.
RULE_CASE = (
    "- Unterschiede nur in der Groß-/Kleinschreibung (z. B. „Haus“/„haus“)."
)
RULE_VARIANTS = (
    "- Schreibvarianten und Tippfehler desselben Wortes, auch Umschreibungen "
    "von Umlauten und ß (z. B. „müde“/„muede“/„mühde“)."
)
RULE_SYNONYMS = (
    "- Wortformen desselben Wortes — Singular/Plural, Beugungsformen und "
    "Ableitungen mit gleicher Kernbedeutung (z. B. „einsam“/„Einsamkeit“) — "
    "sowie eindeutig bedeutungsgleiche Synonyme (z. B. „Fahrrad“/„Velo“)."
)
RULE_CONCEPTS = (
    "- Verschiedene Wörter für dasselbe alltägliche Konzept auf derselben "
    "Begriffsebene (z. B. „Gebäude“/„Haus“/„Wohnung“). Wähle dafür als "
    "\"label\" einen gemeinsamen, treffenden Begriff."
)
KEEP_VARIANTS_APART = (
    "- Schreibvarianten und Tippfehler (z. B. „müde“/„muede“/„mühde“) "
    "bleiben GETRENNT, jede Schreibweise bildet ihre eigene Gruppe."
)
KEEP_SYNONYMS_APART = (
    "- Unterschiedliche Wortformen und Synonyme (z. B. „einsam“/„Einsamkeit“, "
    "„Fahrrad“/„Velo“) bleiben GETRENNT."
)
RESTRAINT_STRICT = (
    "WICHTIG — sei sehr zurückhaltend: Verschiedene Begriffe bleiben "
    "GETRENNT, auch wenn sie thematisch verwandt sind oder zur selben "
    "Kategorie gehören. NICHT zusammenfassen z. B.: „Katze“ und „Hund“; "
    "„Gehen“ und „Laufen“; „Baum“ und „Weg“. Im Zweifel NICHT "
    "zusammenfassen. Die meisten Begriffe bilden ihre eigene Gruppe mit "
    "nur einem \"members\"-Eintrag. Das thematische Zusammenfassen "
    "passiert getrennt über \"cluster\", nicht über die Gruppen."
)
RESTRAINT_CONCEPTS = (
    "WICHTIG — bleibe trotzdem zurückhaltend: Fasse nur zusammen, was "
    "dasselbe Konzept bezeichnet. Begriffe, die lediglich thematisch "
    "verwandt sind oder zusammen vorkommen, bleiben GETRENNT, z. B. „Hund“ "
    "und „Leine“; „Baum“ und „Weg“; „Schule“ und „Lehrer“. Im Zweifel NICHT "
    "zusammenfassen. Das thematische Zusammenfassen passiert getrennt über "
    "\"cluster\", nicht über die Gruppen."
)


def merge_flags(question):
    """The question's consolidation switches as ``optimize_system`` kwargs."""
    return {
        "merge_variants": question.wordcloud_merge_variants,
        "merge_synonyms": question.wordcloud_merge_synonyms,
        "merge_concepts": question.wordcloud_merge_concepts,
    }


def optimize_system(
    grouping="", *, merge_variants=True, merge_synonyms=True, merge_concepts=False
):
    """System prompt for cleanup + clustering. ``grouping`` (optional) is the
    presenter's own grouping criterion; empty falls back to automatic themes.
    The ``merge_*`` flags choose what the consolidated view may merge
    (spelling variants/typos, word forms + synonyms, similar concepts); with
    all off only case variants are merged."""
    if grouping and grouping.strip():
        cluster_rule = (
            "- \"cluster\" ordnet die Gruppe nach folgendem Kriterium ein: "
            f"„{grouping.strip()}“. Bilde daraus wenige aussagekräftige "
            "Gruppen; Begriffe, die nicht passen, bekommen den cluster "
            f"\"{OTHER_CLUSTER}\".\n"
        )
    else:
        cluster_rule = (
            "- \"cluster\" ist ein kurzer thematischer Oberbegriff (1–3 "
            "Wörter). Gruppen zum selben Thema bekommen denselben "
            "\"cluster\"-Text.\n"
        )
    merge_rules = [RULE_CASE]
    keep_apart = []
    if merge_variants:
        merge_rules.append(RULE_VARIANTS)
    else:
        keep_apart.append(KEEP_VARIANTS_APART)
    if merge_synonyms:
        merge_rules.append(RULE_SYNONYMS)
    else:
        keep_apart.append(KEEP_SYNONYMS_APART)
    if merge_concepts:
        merge_rules.append(RULE_CONCEPTS)
    keep_apart_text = (
        "Ausdrücklich NICHT zusammenfassen:\n" + "\n".join(keep_apart) + "\n"
        if keep_apart
        else ""
    )
    label_rule = (
        "- \"label\" ist die bevorzugte, korrekt geschriebene Form der "
        "Gruppe (eine der Varianten oder eine korrigierte Schreibweise"
        + ("; bei ähnlichen Konzepten der gemeinsame Begriff" if merge_concepts else "")
        + ").\n"
    )
    return (
        "Du bereinigst die Ergebnisse einer Wortwolke aus einer "
        "Lehrveranstaltung. Du erhältst eine Liste von Begriffen mit "
        "Häufigkeiten.\n"
        "Fasse Begriffe NUR in diesen Fällen zu einer Gruppe zusammen:\n"
        + "\n".join(merge_rules)
        + "\n"
        + keep_apart_text
        + (RESTRAINT_CONCEPTS if merge_concepts else RESTRAINT_STRICT)
        + "\n"
        "Regeln:\n"
        "- Verwende als \"members\" ausschließlich die vorgegebenen "
        "Begriffe, exakt so geschrieben; erfinde keine neuen.\n"
        "- Jeder Begriff darf in höchstens einer Gruppe vorkommen.\n"
        + label_rule
        + cluster_rule
        + "- Zähle oder gewichte nichts; die Häufigkeiten werden separat "
        "berechnet.\n"
        "- Antworte ausschließlich mit JSON."
    )


def build_optimize_prompt(words):
    payload = [{"text": w["text"], "count": w["count"]} for w in words]
    return (
        "Begriffe (mit Häufigkeit):\n"
        + json.dumps(payload, ensure_ascii=False)
        + "\n\nGib JSON in genau dieser Form zurück (die meisten Gruppen haben "
        "nur einen \"members\"-Eintrag; das Beispiel zeigt nur das Format — "
        "was zusammengefasst wird, bestimmen allein die Regeln):\n"
        '{"groups": ['
        '{"label": "Fahrrad", "cluster": "Verkehr", '
        '"members": ["Fahrrad", "Farrad", "Velo"]}, '
        '{"label": "Baum", "cluster": "Natur", "members": ["Baum"]}]}'
    )


def _extend_unique(target, items):
    """Append `items` to `target` in order, skipping ones already present."""
    for item in items:
        if item not in target:
            target.append(item)
    return target


def apply_optimization(words, data):
    """Turn the model's grouping into validated clusters.

    `words` is the ``words_with_counts`` output ([{text, count, keys}, …]).
    Counts are always recomputed from `words`; the model's role is purely
    to decide which raw spellings belong together and how to name them.
    Every output word carries ``keys``: the casefold raw keys of all input
    words it stands for (a manual merge contributes all its keys), so the
    presenter can moderate (hide/merge) AI words like raw ones.
    """
    index = {}
    for entry in words:
        key = entry["text"].casefold()
        raw_keys = [str(k) for k in (entry.get("keys") or [key])]
        # Aggregation already merges case variants, but stay defensive.
        if key in index:
            index[key]["count"] += entry["count"]
            _extend_unique(index[key]["keys"], raw_keys)
        else:
            index[key] = {
                "text": entry["text"], "count": entry["count"],
                "keys": _extend_unique([], raw_keys),
            }

    consumed = set()
    groups = []
    raw_groups = data.get("groups") if isinstance(data, dict) else None
    for group in raw_groups or []:
        if not isinstance(group, dict):
            continue
        members = group.get("members")
        if not isinstance(members, list):
            continue
        variants, count, keys = [], 0, []
        for member in members:
            key = str(member).strip().casefold()
            if key in index and key not in consumed:
                consumed.add(key)
                variants.append(index[key]["text"])
                count += index[key]["count"]
                _extend_unique(keys, index[key]["keys"])
        if not variants:
            continue
        label = str(group.get("label", "")).strip()[:LABEL_MAX]
        if not label:
            # Fall back to the most frequent raw spelling in the group.
            label = max(variants, key=lambda v: index[v.casefold()]["count"])
        cluster = str(group.get("cluster", "")).strip()[:CLUSTER_MAX] or OTHER_CLUSTER
        groups.append(
            {"label": label, "cluster": cluster, "count": count,
             "variants": variants, "keys": keys}
        )

    # Any word the model ignored keeps its own entry under "Weitere".
    for key, entry in index.items():
        if key not in consumed:
            groups.append(
                {
                    "label": entry["text"],
                    "cluster": OTHER_CLUSTER,
                    "count": entry["count"],
                    "variants": [entry["text"]],
                    "keys": list(entry["keys"]),
                }
            )

    clusters = {}
    for group in groups:
        clusters.setdefault(group["cluster"], []).append(
            {"text": group["label"], "count": group["count"],
             "variants": group["variants"], "keys": list(group["keys"])}
        )

    cluster_list = [
        {
            "label": name,
            "count": sum(w["count"] for w in items),
            "words": sorted(items, key=lambda w: -w["count"]),
        }
        for name, items in clusters.items()
    ]
    # Biggest clusters first; the catch-all "Weitere" always sinks to the end.
    cluster_list.sort(key=lambda c: (c["label"] == OTHER_CLUSTER, -c["count"]))

    merged = sorted(
        (
            {"text": g["label"], "count": g["count"],
             "variants": g["variants"], "keys": list(g["keys"])}
            for g in groups
        ),
        key=lambda w: -w["count"],
    )
    return {"clusters": cluster_list, "merged": merged}
