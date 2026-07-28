# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Live AI word-cloud views during a run.

While the presenter shows an AI view (consolidated or grouped), the raw terms
are periodically sent to the LLM, which merges spelling variants/synonyms and
assigns each group to a cluster (auto-themes, or the question's own grouping
criterion). Counts are always recomputed server-side (see ``ai_wordcloud``);
the model only groups/labels.

Capacity: the computation only runs for a ``(run, question)`` the presenter has
marked active (toggled to an AI view). New votes trigger a *throttled* recompute
— at most one LLM call every ``MIN_INTERVAL`` seconds, plus a trailing one when
the burst settles — so a room of participants never fans out into one call per
vote. No task broker (ADR-0003, single process): a small ``ThreadPoolExecutor``
plus an in-memory result store, read by ``state.py`` for the presenter payload.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from basicbar_integrations import ai
from django.db import connections

from . import ai_wordcloud

MIN_INTERVAL = 4.0  # seconds between LLM recomputes for the same word cloud

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ai-wc")
_lock = threading.Lock()
_active = set()          # {(run_id, question_id)} currently shown as an AI view
_results = {}            # (run_id, question_id) -> {merged, clusters, pending, ...}
_running = set()         # keys with a worker loop in flight
_dirty = set()           # keys that got new votes while a loop was running


def is_active(run_id, question_id):
    with _lock:
        return (run_id, question_id) in _active


def get_result(run_id, question_id):
    """The latest AI view for the presenter payload, or None when inactive."""
    with _lock:
        result = _results.get((run_id, question_id))
        return dict(result) if result else None


def set_active(run_id, question_id, room_id, on):
    """Toggle the live AI computation for one word cloud (presenter view)."""
    key = (run_id, question_id)
    if on:
        if not ai.is_enabled():
            return
        with _lock:
            _active.add(key)
            # Show a wait state until the first result lands.
            _results.setdefault(
                key, {"merged": [], "clusters": [], "pending": True}
            )
        schedule(run_id, question_id, room_id)
    else:
        # Keep the computed result warm (#75): only stop the live recompute,
        # don't drop the cache — so switching views later is instant.
        with _lock:
            _active.discard(key)
            _dirty.discard(key)


def ensure_result(run_id, question_id, room_id):
    """Compute the AI view once, eagerly — e.g. when the vote closes (#75) —
    so the presenter can switch to it without waiting. The result is then kept
    warm for the rest of the run. No-op if already computed or AI is disabled."""
    if not ai.is_enabled():
        return
    key = (run_id, question_id)
    with _lock:
        current = _results.get(key)
        if current is not None and not current.get("pending"):
            return  # already computed and warm
        _results.setdefault(key, {"merged": [], "clusters": [], "pending": True})
        if key in _running:
            return
        _running.add(key)
    _executor.submit(_run_loop, run_id, question_id, room_id)


def schedule(run_id, question_id, room_id):
    """New votes arrived — recompute if this word cloud is being shown as an AI
    view. Single-flight per key with a trailing recompute (throttled)."""
    if not ai.is_enabled():
        return
    key = (run_id, question_id)
    with _lock:
        if key not in _active:
            return
        if key in _running:
            _dirty.add(key)  # fold into the running loop's trailing pass
            return
        _running.add(key)
    _executor.submit(_run_loop, run_id, question_id, room_id)


def _run_loop(run_id, question_id, room_id):
    key = (run_id, question_id)
    try:
        while True:
            _compute(run_id, question_id, room_id)
            with _lock:
                if key in _active and key in _dirty:
                    _dirty.discard(key)
                else:
                    _running.discard(key)
                    return
            # Throttle: batch the votes that arrived during the compute.
            time.sleep(MIN_INTERVAL)
    finally:
        with _lock:
            _running.discard(key)
            _dirty.discard(key)


def _compute(run_id, question_id, room_id):
    """One LLM pass: raw terms → consolidated + grouped, stored for the payload."""
    from rooms.models import Question, Room

    from .models import Run
    from .results import words_with_counts
    from .state import broadcast

    key = (run_id, question_id)
    try:
        run = Run.objects.filter(pk=run_id).first()
        question = Question.objects.filter(pk=question_id).first()
        if run is None or question is None:
            return
        words = words_with_counts(run, question, limit=200)
        if not words:
            result = {"merged": [], "clusters": [], "pending": False}
        else:
            try:
                data = ai.chat_json(
                    ai_wordcloud.optimize_system(question.wordcloud_grouping),
                    ai_wordcloud.build_optimize_prompt(words),
                )
                optimized = ai_wordcloud.apply_optimization(words, data)
                result = {
                    "merged": optimized["merged"],
                    "clusters": optimized["clusters"],
                    "pending": False,
                }
            except ai.AIError:
                result = {"merged": [], "clusters": [], "pending": False}
        with _lock:
            # Always store (kept warm, #75); set_active(off) no longer drops it.
            _results[key] = result
        room = Room.objects.filter(pk=room_id).first()
        if room is not None:
            broadcast(room, debounce=True)
    finally:
        # Return the worker's pooled connection (skip a mid-transaction one, as
        # TestCase wraps each test in an atomic block).
        for conn in connections.all():
            if not conn.in_atomic_block:
                conn.close()
