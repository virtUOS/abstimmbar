# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Live evaluation of free-text answers during a run.

When a participant submits an answer to an ``open_text`` question that has
``ai_evaluate`` on, the vote is stored unclassified and the work is handed to
a small thread pool. Identical answers (same casefolded ``text_key``) share a
single model call, and the presenter view refreshes over SSE as verdicts land.

No task broker (ADR-0003 keeps the stack single-process and dependency-light):
a bounded ``ThreadPoolExecutor`` handles classroom-sized bursts; excess work
queues. A DB connection opened in a worker is returned as soon as it is done,
and the SSE broadcast is debounced so a wave of completions collapses into a
couple of snapshots."""
from concurrent.futures import ThreadPoolExecutor

from basicbar_integrations import ai
from django.conf import settings
from django.db import connections

from common.i18n_fields import translated_map

from .ai_freetext import clean_categories, evaluate_system, middle_category
from .ai_report import _plain

_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="ai-eval")


def _canonical_text(obj, base):
    """A translatable field resolved to the content-canonical language (#33
    MR2), bypassing Django's *active* language. This runs on a
    ``ThreadPoolExecutor`` worker, which never ran ``LocaleMiddleware``, so
    ``translation.get_language()`` (and anything built on it, including
    ``resolve_translated_text``) falls back to ``settings.LANGUAGE_CODE``
    ("en") rather than the content's actual canonical language — silently
    feeding the LLM the wrong-language text whenever an English variant
    happens to exist. Read the {de, en} map directly and pick the canonical
    language explicitly instead."""
    m = translated_map(obj, base)
    return m.get(settings.MODELTRANSLATION_DEFAULT_LANGUAGE) or next(
        (t for t in m.values() if t), ""
    )


def classify(question_text, hint, answer, categories):
    """One model call for a single answer → (verdict, note). The verdict is
    coerced to one of ``categories``; any failure or unknown label degrades to
    the middle category so a run never stalls on the LLM."""
    cats = clean_categories(categories)
    valid = {c.casefold(): c for c in cats}
    fallback = middle_category(cats)
    lines = [f"Frage: {_plain(question_text) or '(ohne Fragentext)'}"]
    if hint:
        lines.append(f"Erwartete Antwort / Kriterium: {hint}")
    lines.append(f"Antwort: {answer}")
    lines.append(
        'Gib JSON zurück: {"verdict": "<eine der Kategorien>", '
        '"note": "kurze Begründung"}'
    )
    try:
        data = ai.chat_json(evaluate_system(cats), "\n".join(lines))
    except ai.AIError:
        return fallback, ""
    verdict = valid.get(str(data.get("verdict", "")).strip().casefold(), fallback)
    return verdict, str(data.get("note", "")).strip()[:200]


def evaluate_vote(vote_id, room_id):
    """Worker body: classify one pending vote (reusing an existing verdict for
    the same answer), label all duplicates, then refresh the presenter."""
    from rooms.models import Room

    from .models import Vote
    from .state import broadcast

    try:
        vote = Vote.objects.select_related("question", "run").filter(pk=vote_id).first()
        if vote is None or vote.ai_verdict:
            return
        siblings = Vote.objects.filter(
            run_id=vote.run_id, question_id=vote.question_id, text_key=vote.text_key
        )
        done = siblings.exclude(ai_verdict="").first()
        if done is not None:
            verdict, note = done.ai_verdict, done.ai_note
        else:
            verdict, note = classify(
                _canonical_text(vote.question, "text"),
                vote.question.evaluation_hint,
                vote.text,
                vote.question.evaluation_categories,
            )
        # One call labels every still-pending duplicate of this answer.
        siblings.filter(ai_verdict="").update(ai_verdict=verdict, ai_note=note)
        room = Room.objects.filter(pk=room_id).first()
        if room is not None:
            broadcast(room, debounce=True)
    finally:
        # Give the worker's pooled connection back. Skip any connection that
        # is mid-transaction (e.g. TestCase wraps each test in one) — closing
        # it there would break the surrounding block.
        for conn in connections.all():
            if not conn.in_atomic_block:
                conn.close()


def schedule(vote_id, room_id):
    """Queue background evaluation of one vote (no-op when AI is disabled)."""
    if not ai.is_enabled():
        return
    _executor.submit(evaluate_vote, vote_id, room_id)
