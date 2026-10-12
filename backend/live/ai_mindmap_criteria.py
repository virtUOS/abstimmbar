# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""AI colouring of a live mind map by teacher-defined criteria (stage 3,
part 2, "Thematische Färbung").

The question carries up to six bilingual criteria (``Question.mindmap_criteria``,
``rooms.mindmap.clean_criteria``). While the presenter has colouring switched
on for a ``(run, question)``, a background pass sends the visible terms that
lack a valid classification to the LLM, which assigns each at most one
criterion (the best fitting) or none. The result is stored per node
(``MindmapNode.ai_criterion``) together with the criteria fingerprint
(``ai_criteria_fp``) and the node's ``text_key`` at classification time
(``ai_text_key``): a criteria change invalidates every node, a rename only that
node, so already classified terms are never re-sent. A merge keeps the
target's classification (the source row disappears).

Same machinery as ``ai_wordcloud_live`` (ADR-0003, single process, no task
broker): an in-memory active flag per key, single-flight worker loop on a small
``ThreadPoolExecutor`` with a trailing pass, at most one LLM call every
``MIN_INTERVAL`` seconds, at most ``BATCH_MAX`` terms per call. Request
handlers only call ``schedule`` (cheap, no LLM call, no DB work); the LLM is
called outside any transaction and the write happens under the run lock,
only for nodes whose ``text_key`` is still the one that was classified.

Only question text, criteria, terms, descriptions and their paths go to the
LLM — never participant tokens. ``classify_pass`` is synchronous and takes an
injectable ``chat_json`` so tests can drive it directly.
"""
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from basicbar_integrations import ai
from django.db import connections, transaction

from rooms.mindmap import criteria_fingerprint, seed_langs

from .ai_freetext_summary import context_block, question_context

MIN_INTERVAL = 4.0  # seconds between LLM passes for the same map
BATCH_MAX = 150  # terms per LLM call
DESCRIPTION_MAX = 200
PATH_SEPARATOR = " › "
# Short error codes for the beamer (``mindmap.criteria.error``).
ERROR_AI = "ai_error"  # the AI call failed (timeout, provider down, …)
ERROR_REPLY = "invalid_reply"  # the reply had no usable assignment

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ai-mm-crit")
_lock = threading.Lock()
_active = {}  # (run_id, question_id) -> room_id while colouring is on
_errors = {}  # (run_id, question_id) -> error code of the last pass
_running = set()  # keys with a worker loop in flight
_dirty = set()  # keys whose map changed while a loop was running


def is_active(run_id, question_id):
    with _lock:
        return (run_id, question_id) in _active


def get_error(run_id, question_id):
    with _lock:
        return _errors.get((run_id, question_id))


def set_active(run_id, question_id, room_id, on):
    """Switch the live colouring of one map on/off (presenter). Switching on
    (again) clears a previous error and schedules a pass — the beamer's
    "try again". Returns False when AI is not configured (nothing changes)."""
    key = (run_id, question_id)
    if on:
        if not ai.is_enabled():
            return False
        with _lock:
            _active[key] = room_id
            _errors.pop(key, None)
        schedule(run_id, question_id, room_id)
        return True
    with _lock:
        _active.pop(key, None)
        _dirty.discard(key)
        _errors.pop(key, None)
    return True


def schedule(run_id, question_id, room_id):
    """The map (or its criteria) changed — classify what is new if colouring
    is on. Cheap no-op otherwise; single-flight per key with a trailing
    pass. Safe to call from request handlers (no DB access, no LLM call)."""
    if not ai.is_enabled():
        return
    key = (run_id, question_id)
    with _lock:
        if key not in _active:
            return
        if key in _running:
            _dirty.add(key)  # folded into the running loop's trailing pass
            return
        _running.add(key)
    _executor.submit(_run_loop, run_id, question_id, room_id)


def criteria_changed(question_id):
    """The question's criteria were saved (editor) — re-classify every map
    of this question that is currently coloured."""
    with _lock:
        keys = [(key, room) for key, room in _active.items() if key[1] == question_id]
    for (run_id, _q), room_id in keys:
        schedule(run_id, question_id, room_id)


def _run_loop(run_id, question_id, room_id):
    key = (run_id, question_id)
    try:
        while True:
            more = classify_pass(run_id, question_id, room_id)
            with _lock:
                if key in _active and (key in _dirty or more):
                    _dirty.discard(key)
                else:
                    # Release ownership exactly once, here.
                    _running.discard(key)
                    _dirty.discard(key)
                    return
            # Throttle: batch the changes that arrived during the pass.
            time.sleep(MIN_INTERVAL)
    except BaseException:
        with _lock:
            _running.discard(key)
            _dirty.discard(key)
        raise


# --- validity, payloads ------------------------------------------------------


def valid_assignments(run, question):
    """``{node_id: index|None}`` for every node of the map whose stored
    classification is valid (current criteria, unchanged term). Nodes
    missing from the dict are unclassified."""
    fp = criteria_fingerprint(question.mindmap_criteria)
    if not fp:
        return {}
    from .models import MindmapNode

    result = {}
    rows = MindmapNode.objects.filter(
        run=run, question=question, ai_criteria_fp=fp
    ).values_list("id", "text_key", "ai_text_key", "ai_criterion")
    count = len(question.mindmap_criteria)
    for node_id, key, ai_key, criterion in rows:
        if key == ai_key:
            result[node_id] = criterion if criterion is not None and criterion < count else None
    return result


def _annotate(nodes, valid):
    """Set ``criterion`` (index or None) on every node of a payload tree."""
    for node in nodes:
        node["criterion"] = valid.get(node["id"])
        _annotate(node["children"], valid)


def _visible(nodes):
    for node in nodes:
        if node.get("hidden"):
            continue
        yield node
        yield from _visible(node["children"])


def presenter_payload(run, question, tree):
    """``mindmap.criteria`` of the presenter payload; with colouring on, also
    ``criterion`` on every node of ``tree`` (presenter form). ``pending`` =
    visible terms not (yet) classified while colouring is on."""
    active = is_active(run.pk, question.pk)
    result = {"active": active, "items": question.mindmap_criteria or [], "pending": 0}
    if active and question.mindmap_criteria:
        valid = valid_assignments(run, question)
        _annotate(tree["nodes"], valid)
        result["pending"] = sum(1 for node in _visible(tree["nodes"]) if node["id"] not in valid)
    error = get_error(run.pk, question.pk)
    if error:
        result["error"] = error
    return result


def attach_stored(run, question, tree):
    """Participant results phase and results page: add ``criterion`` to
    every node of ``tree`` and ``tree["criteria"] = {"items": […]}`` when at
    least one term has a (valid) criterion. Returns whether it did."""
    if not question.mindmap_criteria:
        return False
    valid = valid_assignments(run, question)
    if not any(value is not None for value in valid.values()):
        return False
    _annotate(tree["nodes"], valid)
    tree["criteria"] = {"items": question.mindmap_criteria}
    return True


# --- the classification pass -------------------------------------------------


def pending_terms(tree, valid):
    """Visible terms of a presenter tree without a valid classification, as
    prompt entries (+ the ``key`` used for the stale-write guard)."""
    result = []

    def walk(nodes, path):
        for node in nodes:
            if node.get("hidden"):
                continue
            node_path = [*path, node["text"]]
            if node["id"] not in valid:
                term = {
                    "id": node["id"],
                    "key": node["key"],
                    "text": node["text"],
                    "path": PATH_SEPARATOR.join(node_path),
                }
                description = " / ".join(node.get("descriptions") or [])
                if description:
                    term["description"] = description[:DESCRIPTION_MAX]
                result.append(term)
            walk(node["children"], node_path)

    walk(tree["nodes"], [])
    return result


def _criterion_label(entry):
    _canonical, langs = seed_langs()
    texts = []
    for lang in langs:
        text = (entry.get(lang) or "").strip()
        if text and text.casefold() not in {t.casefold() for t in texts}:
            texts.append(text)
    return " / ".join(texts)


def build_prompt(question, criteria, terms):
    """``(system, user)`` for ``ai.chat_json``: question, numbered criteria
    (from 1) and the terms to classify (id, text, path, description)."""
    system = (
        "Du hilfst Lehrenden, die Begriffe einer gemeinsam von Studierenden "
        "erstellten Mindmap thematisch einzufärben. Du erhältst die Frage, "
        "eine nummerierte Liste von Kriterien und Begriffe (id, text, path = "
        "Pfad von der Wurzel bis zum Begriff, optional description).\n"
        "Ordne jedem Begriff höchstens ein Kriterium zu — das am besten "
        "passende — oder null, wenn keines wirklich passt. Beurteile jeden "
        "Begriff im Zusammenhang mit seinem Pfad.\n"
        "Antworte ausschließlich mit JSON der Form "
        '{"assignments": [{"id": 12, "criterion": 2}, {"id": 15, "criterion": null}]} '
        "und nenne jeden Begriff genau einmal; \"criterion\" ist die Nummer "
        "des Kriteriums oder null."
    )
    numbered = [
        {"nr": index, "text": _criterion_label(entry)}
        for index, entry in enumerate(criteria, start=1)
    ]
    payload = [
        {k: v for k, v in term.items() if k != "key"} for term in terms
    ]
    user = (
        context_block(question_context(question))
        + "Kriterien:\n"
        + json.dumps(numbered, ensure_ascii=False)
        + "\n\nBegriffe:\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    return system, user


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def parse_assignments(data, ids, count):
    """``{id: index|None}`` for every id in ``ids`` from the model's reply
    (criterion numbers 1…count → index 0…count-1; null/invalid → None; a
    term the reply leaves out → None, so it is not re-sent forever). None
    when the reply holds no well-formed assignment at all."""
    raw = data.get("assignments") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return None
    result, seen = {}, 0
    for item in raw:
        if not isinstance(item, dict) or not _is_int(item.get("id")):
            continue
        node_id = item["id"]
        if node_id not in ids or node_id in result:
            continue
        criterion = item.get("criterion")
        if criterion is None:
            result[node_id] = None
        elif _is_int(criterion) and 1 <= criterion <= count:
            result[node_id] = criterion - 1
        else:
            continue
        seen += 1
    if not seen and ids:
        return None
    return {node_id: result.get(node_id) for node_id in ids}


def _write(run, question, fp, batch, assignments):
    """Store the batch's classification under the run lock — only while the
    criteria are unchanged, and per node only while its term is unchanged.
    Returns the number of nodes written."""
    from rooms.models import Question

    from .mindmap import _lock_run
    from .models import MindmapNode

    with transaction.atomic():
        _lock_run(run)
        current = (
            Question.objects.filter(pk=question.pk)
            .values_list("mindmap_criteria", flat=True)
            .first()
        )
        if criteria_fingerprint(current) != fp:
            return 0  # criteria changed meanwhile — their own pass follows
        written = 0
        for term in batch:
            written += MindmapNode.objects.filter(
                pk=term["id"], run=run, question=question, text_key=term["key"]
            ).update(
                ai_criterion=assignments[term["id"]],
                ai_criteria_fp=fp,
                ai_text_key=term["key"],
            )
    return written


def _set_error(key, error):
    with _lock:
        if error:
            _errors[key] = error
        else:
            _errors.pop(key, None)


def _broadcast(room_id):
    from rooms.models import Room

    from .state import broadcast

    room = Room.objects.filter(pk=room_id).first() if room_id else None
    if room is not None:
        broadcast(room, debounce=True)


def classify_pass(run_id, question_id, room_id=None, *, chat_json=None):
    """One LLM pass over the next ``BATCH_MAX`` unclassified visible terms.
    Returns True when more terms remain after a pass that made progress
    (the loop then continues). Errors are stored for the beamer, never
    raised. Must not be called inside a transaction (it calls the LLM)."""
    from rooms.models import Question

    from .mindmap import build_tree
    from .models import Run

    chat_json = chat_json or ai.chat_json
    key = (run_id, question_id)
    try:
        run = Run.objects.filter(pk=run_id).first()
        question = Question.objects.filter(pk=question_id).first()
        if run is None or question is None:
            return False
        criteria = question.mindmap_criteria or []
        fp = criteria_fingerprint(criteria)
        if not fp:
            _set_error(key, None)
            return False
        tree = build_tree(run, question, presenter=True)
        terms = pending_terms(tree, valid_assignments(run, question))
        if not terms:
            return False
        batch = terms[:BATCH_MAX]
        system, user = build_prompt(question, criteria, batch)
        try:
            reply = chat_json(system, user)
        except ai.AIError:
            _set_error(key, ERROR_AI)
            _broadcast(room_id)
            return False
        assignments = parse_assignments(reply, [term["id"] for term in batch], len(criteria))
        if assignments is None:
            _set_error(key, ERROR_REPLY)
            _broadcast(room_id)
            return False
        written = _write(run, question, fp, batch, assignments)
        _set_error(key, None)
        _broadcast(room_id)
        return len(terms) > len(batch) and written > 0
    finally:
        # Return the worker's pooled connection (skip a mid-transaction one,
        # as TestCase wraps each test in an atomic block).
        for conn in connections.all():
            if not conn.in_atomic_block:
                conn.close()
