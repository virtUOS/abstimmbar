# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Live side of the mind-map question kind (stage 1).

All participants build ONE shared tree per run and question. Identical terms
under the same parent (``rooms.mindmap.text_key``) merge into one node whose
count is its number of contributions. Contributions reference only the opaque
participant token (anonymity by design): the token is used for the
per-person cap and for withdrawing one's own term, and is never exposed.

Writes (add/withdraw/seed materialisation) are serialised per run by locking
the Run row, so caps, depth checks and the "nothing hangs below" rule are
race-free; the unique constraints on MindmapNode/MindmapContribution are the
backstop. The tree is built with a bounded number of queries (nodes, counts,
descriptions) and assembled in Python.
"""
from collections import defaultdict

import nh3
from django.db import IntegrityError, transaction
from django.db.models import Count, Q

from common.i18n_fields import translated_map
from rooms.mindmap import (
    MINDMAP_DESCRIPTION_MAX,
    MINDMAP_TEXT_MAX,
    clean_seed,
    normalize_text,
    text_key,
)

from .models import MindmapContribution, MindmapNode, Run

MINDMAP_MAX_NODES = 300
MINDMAP_MAX_DESCRIPTIONS = 3
ROOT_LABEL_MAX = 80


class MindmapError(Exception):
    """A refused participant action: ``detail`` + HTTP ``status``."""

    def __init__(self, detail, status=400):
        super().__init__(detail)
        self.detail = detail
        self.status = status


def answered_runs_q():
    """Runs that collected answers: votes or mind-map contributions (use with
    ``.distinct()``)."""
    return Q(votes__isnull=False) | Q(mindmap_nodes__contributions__isnull=False)


def run_has_contributions(run):
    return MindmapContribution.objects.filter(node__run=run).exists()


def _lock_run(run):
    Run.objects.select_for_update().filter(pk=run.pk).first()


def root_label(question):
    """{de, en} root label: the authored ``mindmap_root``, else the plain
    (markup-free, shortened) question text."""
    label = translated_map(question, "mindmap_root")
    if any(label.values()):
        return label
    result = {}
    for lang, html in translated_map(question, "text").items():
        plain = " ".join(nh3.clean(html or "", tags=set()).split())
        if len(plain) > ROOT_LABEL_MAX:
            plain = plain[: ROOT_LABEL_MAX - 1].rstrip() + "…"
        result[lang] = plain
    return result


def ensure_seed(run, question):
    """Materialise the question's predefined branches for this run, once.

    Idempotent: a run that already has seeded nodes is left alone (later
    edits of the seed only affect new runs). Serialised via the Run row lock.
    """
    if not question.mindmap_seed:
        return
    if MindmapNode.objects.filter(run=run, question=question, seeded=True).exists():
        return
    seed = clean_seed(question.mindmap_seed, question.mindmap_depth, strict=False)
    if not seed:
        return
    with transaction.atomic():
        _lock_run(run)
        if MindmapNode.objects.filter(run=run, question=question, seeded=True).exists():
            return

        def walk(entries, parent):
            for entry in entries:
                key = text_key(entry["text"])
                node = MindmapNode.objects.filter(
                    run=run, question=question, parent=parent, text_key=key
                ).first()
                if node is None:
                    node = MindmapNode.objects.create(
                        run=run, question=question, parent=parent,
                        text=entry["text"], text_key=key,
                        description=entry["description"], seeded=True,
                    )
                else:
                    node.seeded = True
                    node.description = node.description or entry["description"]
                    node.save(update_fields=["seeded", "description"])
                walk(entry["children"], node)

        walk(seed, None)


def build_tree(run, question, *, presenter):
    """The mind-map payload for one run/question.

    Participant form (``presenter=False``): hidden nodes and their subtrees
    are left out entirely. Presenter form: every node, each with ``hidden``
    (only the explicitly hidden node is flagged; its subtree is implicitly
    hidden). ``total`` = number of nodes in the returned tree.
    """
    rows = list(
        MindmapNode.objects.filter(run=run, question=question)
        .order_by("created_at", "pk")
        .values("id", "parent_id", "text", "text_key", "description", "seeded", "hidden")
    )
    ids = [row["id"] for row in rows]
    counts = {}
    descriptions = defaultdict(list)
    if ids:
        counts = dict(
            MindmapContribution.objects.filter(node_id__in=ids)
            .order_by()
            .values_list("node_id")
            .annotate(n=Count("id"))
        )
        if question.mindmap_descriptions:
            for row in rows:
                if row["description"]:
                    descriptions[row["id"]].append(row["description"])
            for node_id, text in (
                MindmapContribution.objects.filter(node_id__in=ids)
                .exclude(description="")
                .order_by("created_at", "pk")
                .values_list("node_id", "description")
            ):
                descriptions[node_id].append(text)

    children = defaultdict(list)
    for row in rows:
        children[row["parent_id"]].append(row)

    total = 0

    def unique_descriptions(node_id):
        seen, result = set(), []
        for text in descriptions.get(node_id, ()):
            key = text.casefold()
            if key not in seen:
                seen.add(key)
                result.append(text)
            if len(result) >= MINDMAP_MAX_DESCRIPTIONS:
                break
        return result

    def walk(parent_id):
        nonlocal total
        result = []
        for row in children.get(parent_id, ()):
            if row["hidden"] and not presenter:
                continue
            total += 1
            node = {
                "id": row["id"],
                "text": row["text"],
                "key": row["text_key"],
                "count": counts.get(row["id"], 0),
                "descriptions": unique_descriptions(row["id"]),
                "seeded": row["seeded"],
            }
            if presenter:
                node["hidden"] = row["hidden"]
            node["children"] = walk(row["id"])
            result.append(node)
        return result

    nodes = walk(None)
    return {
        "root": {"label": root_label(question)},
        "depth": question.mindmap_depth,
        "max_per_person": question.mindmap_max_per_person,
        "descriptions": question.mindmap_descriptions,
        "highlight_duplicates": question.mindmap_highlight_duplicates,
        "max_nodes": MINDMAP_MAX_NODES,
        "total": total,
        "nodes": nodes,
    }


def preview_tree(question):
    """Participant-form tree of the predefined branches without a run — for
    the editor preview (#74). Nothing is stored: ids are negative and local."""
    seed = clean_seed(question.mindmap_seed, question.mindmap_depth, strict=False)
    next_id = 0

    def walk(entries):
        nonlocal next_id
        result = []
        for entry in entries:
            next_id -= 1
            result.append({
                "id": next_id,
                "text": entry["text"],
                "key": text_key(entry["text"]),
                "count": 0,
                "descriptions": (
                    [entry["description"]]
                    if question.mindmap_descriptions and entry["description"]
                    else []
                ),
                "seeded": True,
                "children": walk(entry["children"]),
            })
        return result

    nodes = walk(seed)
    return {
        "root": {"label": root_label(question)},
        "depth": question.mindmap_depth,
        "max_per_person": question.mindmap_max_per_person,
        "descriptions": question.mindmap_descriptions,
        "highlight_duplicates": question.mindmap_highlight_duplicates,
        "max_nodes": MINDMAP_MAX_NODES,
        "total": -next_id,
        "nodes": nodes,
    }


def contributor_count(run, question):
    """Distinct participants who contributed (the "votes" of a mind map)."""
    return (
        MindmapContribution.objects.filter(node__run=run, node__question=question)
        .values("token")
        .distinct()
        .count()
    )


def own_node_ids(run, question, token):
    return list(
        MindmapContribution.objects.filter(
            node__run=run, node__question=question, token=token
        )
        .order_by("created_at", "pk")
        .values_list("node_id", flat=True)
    )


def _parse_id(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def add_term(run, question, token, parent, text, description=""):
    """Add (or merge) a participant's term. Returns ``(node, merged)``;
    raises MindmapError."""
    text = normalize_text(text)
    if not text:
        raise MindmapError("Empty term.")
    if len(text) > MINDMAP_TEXT_MAX:
        raise MindmapError("Term too long.")
    description = (
        " ".join(str(description or "").split()) if question.mindmap_descriptions else ""
    )
    if len(description) > MINDMAP_DESCRIPTION_MAX:
        raise MindmapError("Description too long.")
    parent_id = None
    if parent is not None:
        parent_id = _parse_id(parent)
        if parent_id is None:
            raise MindmapError("Unknown parent.")
    key = text_key(text)

    ensure_seed(run, question)
    with transaction.atomic():
        _lock_run(run)
        tree = {
            node_id: (pid, hidden)
            for node_id, pid, hidden in MindmapNode.objects.filter(
                run=run, question=question
            ).values_list("id", "parent_id", "hidden")
        }
        level = 1
        if parent_id is not None:
            # The parent and all its ancestors must exist and be visible.
            current, guard = parent_id, 0
            while current is not None:
                if current not in tree or tree[current][1] or guard > 50:
                    raise MindmapError("Unknown parent.")
                level += 1
                current = tree[current][0]
                guard += 1
        if level > question.mindmap_depth:
            raise MindmapError("Maximum depth reached.")

        node = MindmapNode.objects.filter(
            run=run, question=question, parent_id=parent_id, text_key=key
        ).first()
        if node is not None and node.contributions.filter(token=token).exists():
            raise MindmapError("Already added.", 409)
        cap = question.mindmap_max_per_person
        if cap and MindmapContribution.objects.filter(
            node__run=run, node__question=question, token=token
        ).count() >= cap:
            raise MindmapError("Maximum reached.", 409)
        merged = node is not None
        if node is None:
            if len(tree) >= MINDMAP_MAX_NODES:
                raise MindmapError("The mind map is full.", 409)
            node = MindmapNode.objects.create(
                run=run, question=question, parent_id=parent_id, text=text, text_key=key
            )
        try:
            with transaction.atomic():
                MindmapContribution.objects.create(
                    node=node, token=token, description=description
                )
        except IntegrityError as error:
            raise MindmapError("Already added.", 409) from error
    return node, merged


def remove_term(run, question, token, node):
    """Withdraw the caller's own contribution. Returns True when the node
    itself was deleted (last contribution of a non-seeded node)."""
    node_id = _parse_id(node)
    with transaction.atomic():
        _lock_run(run)
        node = (
            MindmapNode.objects.filter(pk=node_id, run=run, question=question).first()
            if node_id is not None
            else None
        )
        if node is None:
            raise MindmapError("Unknown term.", 404)
        contribution = node.contributions.filter(token=token).first()
        if contribution is None:
            raise MindmapError("Not your term.", 403)
        if node.children.exists():
            raise MindmapError("Terms hang below this one.", 409)
        contribution.delete()
        if not node.seeded and not node.contributions.exists():
            node.delete()
            return True
    return False


def set_hidden(run, question, node, hidden):
    """Presenter moderation: hide/unhide a node (its subtree with it).
    Returns False for an unknown node."""
    node_id = _parse_id(node)
    if node_id is None:
        return False
    return bool(
        MindmapNode.objects.filter(pk=node_id, run=run, question=question).update(
            hidden=bool(hidden)
        )
    )


def csv_rows(tree):
    """``(path, count)`` per visible node, depth-first ("Wind > Rotor")."""
    rows = []

    def walk(nodes, prefix):
        for node in nodes:
            path = f"{prefix} > {node['text']}" if prefix else node["text"]
            rows.append((path, node["count"]))
            walk(node["children"], path)

    walk(tree["nodes"], "")
    return rows
