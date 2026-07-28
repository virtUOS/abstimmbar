# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Prompts and server-side validation for the optional AI word-cloud
optimisation (merge spelling variants/synonyms, form thematic clusters).

The model only *groups* the words we send; it never supplies counts. We
recompute every count from the original aggregation, so a hallucinated or
mistyped member simply drops out and can never inflate a tally."""
import json

LABEL_MAX = 100
CLUSTER_MAX = 60
OTHER_CLUSTER = "Weitere"


def optimize_system(grouping=""):
    """System prompt for cleanup + clustering. ``grouping`` (optional) is the
    presenter's own grouping criterion; empty falls back to automatic themes."""
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
    return (
        "Du bereinigst die Ergebnisse einer Wortwolke aus einer "
        "Lehrveranstaltung. Du erhältst eine Liste von Begriffen mit "
        "Häufigkeiten.\n"
        "Fasse zu einer Gruppe NUR zusammen, was dasselbe Wort meint: "
        "unterschiedliche Schreibweisen, Tippfehler, Groß-/Kleinschreibung, "
        "Singular/Plural und Beugungsformen sowie eindeutig bedeutungsgleiche "
        "Synonyme (z. B. „Fahrrad“/„Velo“).\n"
        "WICHTIG — sei sehr zurückhaltend: Verschiedene Begriffe bleiben "
        "GETRENNT, auch wenn sie thematisch verwandt sind oder zur selben "
        "Kategorie gehören. NICHT zusammenfassen z. B.: „Katze“ und „Hund“; "
        "„Gehen“ und „Laufen“; „Baum“ und „Weg“. Im Zweifel NICHT "
        "zusammenfassen. Die meisten Begriffe bilden ihre eigene Gruppe mit "
        "nur einem \"members\"-Eintrag. Das thematische Zusammenfassen "
        "passiert getrennt über \"cluster\", nicht über die Gruppen.\n"
        "Regeln:\n"
        "- Verwende als \"members\" ausschließlich die vorgegebenen "
        "Begriffe, exakt so geschrieben; erfinde keine neuen.\n"
        "- Jeder Begriff darf in höchstens einer Gruppe vorkommen.\n"
        "- \"label\" ist die bevorzugte, korrekt geschriebene Form der "
        "Gruppe (eine der Varianten oder eine korrigierte Schreibweise).\n"
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
        "nur einen \"members\"-Eintrag; mehrere nur bei echten Dubletten):\n"
        '{"groups": ['
        '{"label": "Fahrrad", "cluster": "Verkehr", '
        '"members": ["Fahrrad", "Farrad", "Velo"]}, '
        '{"label": "Baum", "cluster": "Natur", "members": ["Baum"]}]}'
    )


def apply_optimization(words, data):
    """Turn the model's grouping into validated clusters.

    `words` is the ``words_with_counts`` output ([{text, count}, …]).
    Counts are always recomputed from `words`; the model's role is purely
    to decide which raw spellings belong together and how to name them.
    """
    index = {}
    for entry in words:
        key = entry["text"].casefold()
        # Aggregation already merges case variants, but stay defensive.
        if key in index:
            index[key]["count"] += entry["count"]
        else:
            index[key] = {"text": entry["text"], "count": entry["count"]}

    consumed = set()
    groups = []
    raw_groups = data.get("groups") if isinstance(data, dict) else None
    for group in raw_groups or []:
        if not isinstance(group, dict):
            continue
        members = group.get("members")
        if not isinstance(members, list):
            continue
        variants, count = [], 0
        for member in members:
            key = str(member).strip().casefold()
            if key in index and key not in consumed:
                consumed.add(key)
                variants.append(index[key]["text"])
                count += index[key]["count"]
        if not variants:
            continue
        label = str(group.get("label", "")).strip()[:LABEL_MAX]
        if not label:
            # Fall back to the most frequent raw spelling in the group.
            label = max(variants, key=lambda v: index[v.casefold()]["count"])
        cluster = str(group.get("cluster", "")).strip()[:CLUSTER_MAX] or OTHER_CLUSTER
        groups.append(
            {"label": label, "cluster": cluster, "count": count, "variants": variants}
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
                }
            )

    clusters = {}
    for group in groups:
        clusters.setdefault(group["cluster"], []).append(
            {"text": group["label"], "count": group["count"], "variants": group["variants"]}
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
            {"text": g["label"], "count": g["count"], "variants": g["variants"]}
            for g in groups
        ),
        key=lambda w: -w["count"],
    )
    return {"clusters": cluster_list, "merged": merged}
