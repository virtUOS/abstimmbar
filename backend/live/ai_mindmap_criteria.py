# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""AI colouring of a live mind map by teacher-defined criteria (stage 3,
part 2, "Thematische Färbung").

The question carries up to six bilingual criteria (``Question.mindmap_criteria``,
``rooms.mindmap.clean_criteria``). While the presenter has colouring switched
on for a ``(run, question)`` (persisted: ``MindmapPhase.ai_criteria_active``)
and the question's AI switch (``wordcloud_ai_enabled``) is on, a background
pass sends the visible terms that lack a valid classification to the LLM,
which assigns each at most one criterion (the best fitting) or none. The
result is stored per node (``MindmapNode.ai_criterion``) together with the
criteria fingerprint (``ai_criteria_fp``) and the node's ``text_key`` at
classification time (``ai_text_key``): a criteria change invalidates every
node, a rename only that node, so already classified terms are never re-sent.
A merge keeps the target's classification (the source row disappears); a
move keeps it too (the term is unchanged — deliberately not re-classified).
A term the model leaves out of its reply is retried (behind fresh terms) and
only stored as "none" after ``OMISSIONS_MAX`` omissions.

Same machinery as ``ai_wordcloud_live`` (ADR-0003, single process, no task
broker): single-flight worker loop on a small ``ThreadPoolExecutor`` with a
trailing pass, at most one LLM call every ``MIN_INTERVAL`` seconds, at most
``BATCH_MAX`` terms per call. Only scheduler bookkeeping lives in memory
(running/dirty/errors/omissions). Capacity: a loop holds its worker through
the LLM call and the throttle sleep, so with ``max_workers=2`` a third map
coloured at the same moment waits its turn. Request handlers only call
``schedule`` (one indexed query, no LLM call); the LLM is called outside any
transaction and the write happens under the run lock, only for nodes whose
``text_key`` is still the one that was classified. After an AI error one
delayed retry (``RETRY_DELAY``) is scheduled; any tree change or switching
colouring on again retries too.

Only question text, criteria, terms, descriptions and their paths go to the
LLM — never participant tokens. ``classify_pass`` is synchronous and takes an
injectable ``chat_json`` so tests can drive it directly.
"""
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from basicbar_integrations import ai
from django.db import connections, transaction

from rooms.mindmap import criteria_fingerprint, seed_langs

from .ai_freetext_summary import context_block, question_context

logger = logging.getLogger(__name__)

MIN_INTERVAL = 4.0  # seconds between LLM passes for the same map
BATCH_MAX = 150  # terms per LLM call
OMISSIONS_MAX = 2  # a term left out this often is stored as "none"
RETRY_DELAY = 30.0  # seconds before the one automatic retry after an AI error
DESCRIPTION_MAX = 200
PATH_SEPARATOR = " › "
# Short error codes for the beamer (``mindmap.criteria.error``).
ERROR_AI = "ai_error"  # the AI call failed (timeout, provider down, …)
ERROR_REPLY = "invalid_reply"  # the reply had no usable assignment

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ai-mm-crit")
_lock = threading.Lock()
_errors = {}  # (run_id, question_id) -> error code of the last pass
_running = set()  # keys with a worker loop in flight
_dirty = set()  # keys whose map changed while a loop was running
_omissions = {}  # (run_id, question_id) -> {(node_id, text_key, fp): count}
_retried = set()  # keys whose one automatic retry after an AI error is used
_timer = threading.Timer  # (patched in tests)


def _close_connections():
    # Return a worker/timer thread's pooled connection (skip a
    # mid-transaction one, as TestCase wraps each test in an atomic block).
    for conn in connections.all():
        if not conn.in_atomic_block:
            conn.close()


def is_active(run_id, question_id):
    """Colouring is on for this map: the presenter's (persisted) switch and
    the question's AI switch."""
    from .models import MindmapPhase

    return MindmapPhase.objects.filter(
        run_id=run_id, question_id=question_id, ai_criteria_active=True,
        question__wordcloud_ai_enabled=True,
    ).exists()


def get_error(run_id, question_id):
    with _lock:
        return _errors.get((run_id, question_id))


def set_active(run_id, question_id, room_id, on):
    """Switch the live colouring of one map on/off (presenter; persisted).
    Switching on (again) clears a previous error and schedules a pass — the
    beamer's "try again". Returns False when AI is not configured (on)."""
    from .models import MindmapPhase

    key = (run_id, question_id)
    if on and not ai.is_enabled():
        return False
    phase, _ = MindmapPhase.objects.get_or_create(run_id=run_id, question_id=question_id)
    if phase.ai_criteria_active != on:
        phase.ai_criteria_active = on
        phase.save(update_fields=["ai_criteria_active"])
    with _lock:
        _errors.pop(key, None)
        _retried.discard(key)
        if not on:
            _dirty.discard(key)
            _omissions.pop(key, None)
    if on:
        schedule(run_id, question_id, room_id)
    return True


def schedule(run_id, question_id, room_id):
    """The map (or its criteria) changed — classify what is new if colouring
    is on. Cheap no-op otherwise (one indexed query); single-flight per key
    with a trailing pass. Safe to call from request handlers (no LLM call)."""
    if not ai.is_enabled() or not is_active(run_id, question_id):
        return
    key = (run_id, question_id)
    with _lock:
        if key in _running:
            _dirty.add(key)  # folded into the running loop's trailing pass
            return
        _running.add(key)
    _executor.submit(_run_loop, run_id, question_id, room_id)


def criteria_changed(question_id):
    """The question's criteria were saved (editor) — re-classify every map
    of this question that is currently coloured (unfinished runs)."""
    from .models import MindmapPhase, Run

    rows = list(
        MindmapPhase.objects.filter(question_id=question_id, ai_criteria_active=True)
        .exclude(run__phase=Run.Phase.FINISHED)
        .values_list("run_id", "run__question_set__room_id")
    )
    with _lock:
        for run_id, _room in rows:
            _omissions.pop((run_id, question_id), None)
    for run_id, room_id in rows:
        schedule(run_id, question_id, room_id)


def _still_on(run_id, question_id):
    try:
        return ai.is_enabled() and is_active(run_id, question_id)
    finally:
        _close_connections()


def _run_loop(run_id, question_id, room_id):
    key = (run_id, question_id)
    try:
        while True:
            more = classify_pass(run_id, question_id, room_id)
            on = _still_on(run_id, question_id)
            with _lock:
                if on and (key in _dirty or more):
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


def _delayed_retry(run_id, question_id, room_id):
    try:
        schedule(run_id, question_id, room_id)
    finally:
        _close_connections()


def _retry_later(key, room_id):
    """One automatic retry ``RETRY_DELAY`` seconds after an AI error (a map
    that has gone quiet would otherwise keep its hint until the next change).
    Reset by a successful pass or by switching colouring on again."""
    with _lock:
        if key in _retried:
            return
        _retried.add(key)
    timer = _timer(RETRY_DELAY, _delayed_retry, args=(*key, room_id))
    timer.daemon = True
    timer.start()


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
    visible terms not (yet) classified while colouring is on. ``active`` is
    false while the question's AI switch is off."""
    active = is_active(run.pk, question.pk)
    result = {"active": active, "items": question.mindmap_criteria or [], "pending": 0}
    if active and question.mindmap_criteria:
        valid = valid_assignments(run, question)
        _annotate(tree["nodes"], valid)
        result["pending"] = sum(1 for node in _visible(tree["nodes"]) if node["id"] not in valid)
    error = get_error(run.pk, question.pk)
    if error:
        result["error"] = error
    elif result["pending"]:
        # Self-healing (e.g. after a restart, or criteria saved in the
        # editor): terms are waiting but no pass may be queued. Cheap no-op
        # while a loop runs (folded into its trailing pass).
        schedule(run.pk, question.pk, run.question_set.room_id)
    return result


def attach_stored(run, question, tree, *, require_active=False):
    """Add ``criterion`` to every node of ``tree`` and ``tree["criteria"] =
    {"items": […]}`` when at least one term has a (valid) criterion. With
    ``require_active`` (participants) only while colouring is switched on;
    the results page and CSV show stored classifications regardless.
    Returns whether it did."""
    if not question.mindmap_criteria:
        return False
    if require_active and not is_active(run.pk, question.pk):
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
    """``{id: index|None}`` for the ids in ``ids`` the reply assigns
    (criterion numbers 1…count → index 0…count-1; null → None). Ids the
    reply leaves out (or answers malformed) are missing from the dict. None
    when the reply holds no well-formed assignment at all."""
    raw = data.get("assignments") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return None
    wanted = set(ids)
    result = {}
    for item in raw:
        if not isinstance(item, dict) or not _is_int(item.get("id")):
            continue
        node_id = item["id"]
        if node_id not in wanted or node_id in result:
            continue
        criterion = item.get("criterion")
        if criterion is None:
            result[node_id] = None
        elif _is_int(criterion) and 1 <= criterion <= count:
            result[node_id] = criterion - 1
    if not result and wanted:
        return None
    return result


def _write(run, question, fp, batch, assignments):
    """Store the batch's classification (``assignments`` = ``{id: index|
    None}`` for the nodes to write) under the run lock — only while the
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
            if term["id"] not in assignments:
                continue
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
            _retried.discard(key)


def _broadcast(room_id):
    from rooms.models import Room

    from .state import broadcast

    room = Room.objects.filter(pk=room_id).first() if room_id else None
    if room is not None:
        broadcast(room, debounce=True)


def _omission_key(term, fp):
    return (term["id"], term["key"], fp)


def classify_pass(run_id, question_id, room_id=None, *, chat_json=None):
    """One LLM pass over the next ``BATCH_MAX`` unclassified visible terms
    (terms the model left out before come after fresh ones). Returns True
    when more terms remain after a pass that made progress (the loop then
    continues). Nothing is sent while the question's AI switch is off or
    (without an injected ``chat_json``) AI is not configured. Errors are
    stored for the beamer, never raised. Must not be called inside a
    transaction (it calls the LLM)."""
    from rooms.models import Question

    from .mindmap import build_tree
    from .models import Run

    if chat_json is None:
        if not ai.is_enabled():
            return False
        chat_json = ai.chat_json
    key = (run_id, question_id)
    try:
        run = Run.objects.filter(pk=run_id).first()
        question = Question.objects.filter(pk=question_id).first()
        if run is None or question is None or not question.wordcloud_ai_enabled:
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
        with _lock:
            omitted = dict(_omissions.get(key, {}))
        # Stable: fresh terms first, then those the model left out before.
        terms.sort(key=lambda term: omitted.get(_omission_key(term, fp), 0))
        batch = terms[:BATCH_MAX]
        system, user = build_prompt(question, criteria, batch)
        try:
            reply = chat_json(system, user)
        except ai.AIError:
            _set_error(key, ERROR_AI)
            _broadcast(room_id)
            _retry_later(key, room_id)
            return False
        assignments = parse_assignments(reply, [term["id"] for term in batch], len(criteria))
        if assignments is None:
            _set_error(key, ERROR_REPLY)
            _broadcast(room_id)
            return False
        retry = 0
        with _lock:
            counts = _omissions.setdefault(key, {})
            for term in batch:
                okey = _omission_key(term, fp)
                if term["id"] in assignments:
                    counts.pop(okey, None)
                    continue
                counts[okey] = counts.get(okey, 0) + 1
                if counts[okey] >= OMISSIONS_MAX:
                    assignments[term["id"]] = None  # give up: no criterion
                    counts.pop(okey)
                else:
                    retry += 1
        written = _write(run, question, fp, batch, assignments)
        _set_error(key, None)
        _broadcast(room_id)
        return written > 0 and (len(terms) > len(batch) or retry > 0)
    except Exception:
        # Anything unexpected (DB error, odd reply …): surface it as an AI
        # error on the beamer instead of leaving "pending" forever.
        logger.exception("Mind-map AI colouring failed (run %s, question %s)", *key)
        _set_error(key, ERROR_AI)
        try:
            _broadcast(room_id)
        except Exception:
            logger.exception("Broadcast after a failed colouring pass failed")
        return False
    finally:
        _close_connections()
