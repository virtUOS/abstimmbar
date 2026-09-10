# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Synchronous AI grading for the anonymous Lernkontrolle (#75 Phase 3).

Unlike the live path (deferred, SSE-refreshed), a self-check answer is graded
in the request: the stateless viewer has no run/SSE to poll. Two in-process
guards keep that safe and cheap — a bounded dedup cache (identical answers to
the same question are graded once) and a per-set sliding-window rate limit
whose ceiling is admin-configurable (0 = unlimited, the local-model default)."""
import threading
import time
from collections import OrderedDict, deque

from common.models import SiteConfig

from .ai_evaluation import _canonical_text, classify

_CACHE_MAX = 512
_WINDOW = 60.0

_lock = threading.Lock()
_cache = OrderedDict()  # (question_id, text_key) -> (verdict, note)
_windows = {}           # set_id -> deque[timestamp]


def _reset_for_tests():
    with _lock:
        _cache.clear()
        _windows.clear()


def grade(question, answer):
    """Return (verdict, note) for one free-text answer, cached per
    (question, normalized answer). Cache miss calls the shared classifier."""
    key = (question.pk, answer.strip().casefold())
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit
    verdict, note = classify(
        _canonical_text(question, "text"),
        question.evaluation_hint,
        answer,
        question.evaluation_categories,
        model_solution=question.model_solution,
    )
    with _lock:
        _cache[key] = (verdict, note)
        _cache.move_to_end(key)
        while len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return verdict, note


def allow(set_id):
    """Sliding-window admission for one Lernkontrolle. Reads the live ceiling
    from SiteConfig each call so an admin change takes effect at once.
    0 (or negative) = unlimited."""
    limit = SiteConfig.load().self_check_ai_per_minute
    if limit <= 0:
        return True
    now = time.monotonic()
    with _lock:
        window = _windows.setdefault(set_id, deque())
        cutoff = now - _WINDOW
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        return True
