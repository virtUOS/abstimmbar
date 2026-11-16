# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Chunking, dedup and the background worker for async question generation."""
import json
import logging
import math
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib import error as urlerror

from basicbar_integrations import ai
from django.conf import settings
from django.db import connections

from common.documents import PAGE_MARKER_RE, page_marker

from . import ai_generate
from .models import GenerationJob

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ai-gen")

# Output budget per AI call (#309): a generous estimate per question (German
# JSON with options or a model solution) plus fixed overhead, never above the
# configured AI_MAX_TOKENS. Too tight a budget would truncate the JSON.
_TOKENS_PER_QUESTION = 500
_TOKENS_OVERHEAD = 500


def call_max_tokens(count):
    return min(settings.AI_MAX_TOKENS, _TOKENS_OVERHEAD + _TOKENS_PER_QUESTION * count)


# User-facing reasons for a run that produced nothing (#302). Short and free of
# internals; German like the rest of the stored job messages.
ERROR_MESSAGES = {
    "timeout": (
        "Die KI hat nicht rechtzeitig geantwortet. Bitte versuchen Sie es erneut; "
        "besteht das Problem weiter, wenden Sie sich an die Administration."
    ),
    "truncated": (
        "Die Antwort der KI war unvollständig oder nicht verwertbar. Bitte "
        "versuchen Sie es erneut; besteht das Problem weiter, wenden Sie sich an "
        "die Administration."
    ),
    "unavailable": (
        "Der KI-Dienst ist derzeit nicht erreichbar. Bitte versuchen Sie es "
        "später erneut."
    ),
    "other": "Die Fragen konnten nicht erzeugt werden. Bitte versuchen Sie es erneut.",
}
PARTIAL_FAILURE_NOTICE = "Für einen Teil des Dokuments konnten keine Fragen erzeugt werden."

_TRUNCATED_HINTS = ("expecting", "unterminated", "extra data", "invalid control", "empty response")
_UNAVAILABLE_HINTS = ("http error", "urlopen error", "connection", "not configured")


def classify_error(exc):
    """Map a failed AI call to a category of ERROR_MESSAGES. ``chat_json``
    wraps everything in ``AIError("AI request failed: …")`` (raised ``from``
    the original), so inspect the cause first and fall back to the message."""
    for err in (exc.__cause__, exc):
        if err is None:
            continue
        if isinstance(err, TimeoutError):
            return "timeout"
        if isinstance(err, urlerror.HTTPError):
            return "unavailable"
        if isinstance(err, urlerror.URLError):
            return "timeout" if isinstance(err.reason, TimeoutError) else "unavailable"
        if isinstance(err, ConnectionError):
            return "unavailable"
        if isinstance(err, json.JSONDecodeError):
            return "truncated"
    message = str(exc).lower()
    if "timed out" in message or "timeout" in message:
        return "timeout"
    if any(hint in message for hint in _TRUNCATED_HINTS):
        return "truncated"
    if any(hint in message for hint in _UNAVAILABLE_HINTS):
        return "unavailable"
    if isinstance(exc, (ValueError, KeyError, TypeError)) and not isinstance(exc, ai.AIError):
        return "truncated"  # the reply parsed but had an unusable shape
    return "other"


def _is_cancelled(job_id):
    status = (
        GenerationJob.objects.filter(pk=job_id).values_list("status", flat=True).first()
    )
    return status == GenerationJob.Status.CANCELLED


def _pack_words(text, size):
    """Greedy word packing into pieces of at most ``size`` characters (a
    single longer word stays whole)."""
    chunks, current, length = [], [], 0
    for word in text.split():
        if current and length + 1 + len(word) > size:
            chunks.append(" ".join(current))
            current, length = [], 0
        current.append(word)
        length += (1 if length else 0) + len(word)
    if current:
        chunks.append(" ".join(current))
    return chunks


def _chunk_size(total, chunk_chars, max_chunks):
    size = 2 * chunk_chars
    if max_chunks:
        size = min(2 * chunk_chars, max(chunk_chars, math.ceil(total / max_chunks)))
    return size


def chunk_text(text, *, chunk_chars, max_chunks):
    """Split text at whitespace, growing the chunk size (up to 2*chunk_chars)
    so a document up to roughly 2*chunk_chars*max_chunks is covered in one pass.
    Returns (chunks, truncated); truncated is True when the (greedy) packing
    still needs more than max_chunks chunks, in which case the tail is dropped
    and the caller surfaces a notice — nothing is ever dropped silently."""
    words = text.split()
    total = sum(len(w) for w in words) + max(0, len(words) - 1)
    chunks = _pack_words(text, _chunk_size(total, chunk_chars, max_chunks))
    truncated = len(chunks) > max_chunks
    return chunks[:max_chunks], truncated


# A page/slide with less text than this (title slide, "Fragen?", an image
# with a caption) gets no share of the questions (#304).
MIN_CONTENT_CHARS = 80
# Extra calls after all chunks when the run is still short of its target.
TOPUP_CALLS = 2


@dataclass
class Chunk:
    """A piece of the material for one or more AI calls. ``pages`` lists
    the (page number, content weight) of the pages it covers — 1.0 for a
    whole content page, a fraction for part of a split page, 0 for a
    near-empty page; empty for unstructured (pasted) text. ``weight`` is the
    chunk's share in the question target."""

    text: str
    label: str = ""
    pages: list = field(default_factory=list)
    weight: float = 0.0


def split_pages(text):
    """(label, [(number, body), …]) from the extraction's page markers
    (common.documents), or ("", []) for text without markers."""
    text = text or ""
    matches = list(PAGE_MARKER_RE.finditer(text))
    if not matches:
        return "", []
    pages = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        if i == 0 and text[:match.start()].strip():
            body = (text[:match.start()].strip() + "\n" + body).strip()
        pages.append((int(match.group(2)), body))
    return matches[0].group(1), pages


def build_chunks(text, *, chunk_chars, max_chunks):
    """Chunks for the worker: whole pages packed together, cutting only at
    page markers — a page larger than a chunk is split by words, each part
    keeping its marker line (#304). Text without markers (pasted text, older
    jobs) is chunked by size as before, weighted by its length. Returns
    (chunks, truncated) like ``chunk_text``."""
    label, pages = split_pages(text)
    if not pages:
        chunks, truncated = chunk_text(text, chunk_chars=chunk_chars, max_chunks=max_chunks)
        return [Chunk(text=c, weight=float(len(c))) for c in chunks], truncated
    size = _chunk_size(len(text), chunk_chars, max_chunks)
    content = {n for n, body in pages if len(body) >= MIN_CONTENT_CHARS}
    if not content:  # all pages short: treat every non-empty page as content
        content = {n for n, body in pages if body}
    pieces = []  # (number, text, weight)
    for number, body in pages:
        marker = page_marker(label, number)
        weight = 1.0 if number in content else 0.0
        if len(marker) + 1 + len(body) <= size:
            pieces.append((number, f"{marker}\n{body}", weight))
            continue
        parts = _pack_words(body, max(1, size - len(marker) - 1))
        part_total = sum(len(part) for part in parts) or 1
        for part in parts:
            pieces.append((number, f"{marker}\n{part}", weight * len(part) / part_total))
    chunks, current = [], None
    for number, piece, weight in pieces:
        if current is not None and len(current.text) + 2 + len(piece) > size:
            chunks.append(current)
            current = None
        if current is None:
            current = Chunk(text=piece, label=label, pages=[(number, weight)])
        else:
            current.text += "\n\n" + piece
            current.pages.append((number, weight))
    if current is not None:
        chunks.append(current)
    for chunk in chunks:
        chunk.weight = sum(weight for _, weight in chunk.pages)
    truncated = bool(max_chunks) and len(chunks) > max_chunks
    return (chunks[:max_chunks] if max_chunks else chunks), truncated


def largest_remainder(total, weights):
    """Split the integer ``total`` proportionally to ``weights`` so that the
    parts sum to exactly ``total`` (Hamilton / largest remainder; ties go to
    the earlier item). All-zero weights split evenly."""
    if not weights:
        return []
    if sum(weights) <= 0:
        weights = [1] * len(weights)
    weight_sum = sum(weights)
    raw = [total * w / weight_sum for w in weights]
    parts = [math.floor(r) for r in raw]
    order = sorted(range(len(raw)), key=lambda i: (-(raw[i] - parts[i]), i))
    for i in order[: total - sum(parts)]:
        parts[i] += 1
    return parts


def spread(total, weights):
    """Like ``largest_remainder`` but spreads a small total evenly across
    the items (cumulative rounding): 4 questions over 9 equal slides land on
    every second slide instead of on the first four."""
    weight_sum = sum(weights)
    if weight_sum <= 0:
        return [0] * len(weights)
    parts, cumulative, previous = [], 0.0, 0
    for w in weights:
        cumulative += w
        boundary = math.floor(total * cumulative / weight_sum + 0.5)
        parts.append(boundary - previous)
        previous = boundary
    return parts


def page_quotas(chunk, quota):
    """{page number: questions} for a chunk's content pages, in page order;
    empty for unstructured text."""
    weights = {}
    for number, weight in chunk.pages:
        weights[number] = weights.get(number, 0.0) + weight
    numbers = [n for n, w in weights.items() if w > 0]
    return dict(zip(numbers, spread(quota, [weights[n] for n in numbers])))


def call_plan(quotas, existing, count):
    """The per-page split for the next call of a chunk: the page quotas minus
    the chunk's drafts so far (by their ``source_page``; drafts without a
    usable one are counted against the earliest open pages), then the first
    ``count`` open questions in page order. [(page, n), …]"""
    remaining = dict(quotas)
    unassigned = 0
    for draft in existing:
        page = draft.get("source_page")
        if remaining.get(page, 0) > 0:
            remaining[page] -= 1
        else:
            unassigned += 1
    for page, open_count in remaining.items():
        take = min(open_count, unassigned)
        remaining[page] -= take
        unassigned -= take
    plan, left = [], count
    for page, open_count in remaining.items():
        if left <= 0:
            break
        if open_count > 0:
            plan.append((page, min(open_count, left)))
            left -= plan[-1][1]
    return plan


_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)


def norm_question(text):
    return " ".join(_PUNCT.sub("", (text or "")).casefold().split())


def merge_drafts(existing, new):
    seen = {norm_question(d.get("text", "")) for d in existing}
    out = list(existing)
    for draft in new:
        key = norm_question(draft.get("text", ""))
        if key and key not in seen:
            seen.add(key)
            out.append(draft)
    return out


def fail_orphaned_jobs():
    """Mark every RUNNING job FAILED — their worker threads died with the
    previous process (crash/redeploy/reload). Returns the number swept."""
    return GenerationJob.objects.filter(status=GenerationJob.Status.RUNNING).update(
        status=GenerationJob.Status.FAILED, error="Unterbrochen (Server-Neustart)."
    )


def sweep_orphaned_jobs():
    """Run the orphan sweep off the ASGI event loop. ``AppConfig.ready`` runs
    inside uvicorn's event loop, where a synchronous ORM call raises
    ``SynchronousOnlyOperation``; calling this from a plain thread gives it a
    sync context (and its own pooled connection, released afterwards)."""
    connections.close_all()
    try:
        fail_orphaned_jobs()
    finally:
        for conn in connections.all():
            if not conn.in_atomic_block:
                conn.close()


def start_job(job):
    _executor.submit(run_generation_job, job.id)


def run_generation_job(job_id):
    connections.close_all()  # fresh DB connection for this worker thread
    try:
        job = GenerationJob.objects.filter(pk=job_id).first()
        if job is None or job.status == GenerationJob.Status.CANCELLED:
            return
        try:
            chunks, truncated = build_chunks(
                job.source_text,
                chunk_chars=settings.AI_CHUNK_CHARS,
                max_chunks=settings.AI_GEN_MAX_CHUNKS,
            )
            notice = ""
            if truncated:
                notice = (
                    f"Das Dokument ({job.source_chars or len(job.source_text)} Zeichen) "
                    "überschreitet die Verarbeitungsgrenze — es wurde nur der "
                    "vordere Teil ausgewertet."
                )
            # Move to RUNNING, but never resurrect a job the request thread has
            # already CANCELLED (a full-row save would otherwise clobber it).
            started = (
                GenerationJob.objects.filter(pk=job_id)
                .exclude(status=GenerationJob.Status.CANCELLED)
                .update(
                    status=GenerationJob.Status.RUNNING,
                    total_chunks=len(chunks),
                    truncated=truncated,
                    notice=notice,
                )
            )
            if not started:
                return  # cancelled before we could start
            failed_chunks = 0
            errors = []  # categories of failed calls (classify_error)
            done = 0
            drafts = list(job.drafts)
            reason = ""
            target = job.target_count or settings.AI_GEN_MAX_QUESTIONS
            # Each chunk's share of the target follows its content pages (or,
            # for pasted text, its length); the parts sum to the target (#304).
            quotas = largest_remainder(target, [c.weight for c in chunks])
            plans = [page_quotas(c, q) for c, q in zip(chunks, quotas)]
            chunk_drafts = [[] for _ in chunks]
            chunk_errored = [False] * len(chunks)
            chunk_declined = [False] * len(chunks)
            per_call = max(1, settings.AI_GEN_PER_CALL)
            system = ai_generate.generate_system()

            def generate(index, count):
                """One AI call for a chunk; returns the number of new drafts.
                Raises on a failed call (handled by the caller)."""
                nonlocal drafts, reason
                chunk = chunks[index]
                data = ai.chat_json(
                    system,
                    ai_generate.build_generate_prompt(
                        chunk.text, count, job.kinds, job.level, job.guidance,
                        focus_kinds=job.focus_kinds,
                        avoid=[d.get("text", "") for d in drafts],
                        page_plan=call_plan(plans[index], chunk_drafts[index], count),
                        page_label=chunk.label,
                    ),
                    max_tokens=call_max_tokens(count),
                )
                new = ai_generate.build_drafts(
                    data, job.kinds, count, pages={n for n, _ in chunk.pages}
                )
                declined = ai_generate.unsuitable_reason(data)
                if declined:
                    reason = reason or declined
                    chunk_declined[index] = True
                before = len(drafts)
                drafts = merge_drafts(drafts, new)[:target]
                chunk_drafts[index].extend(drafts[before:])
                # Progress write: never touches status, so a concurrent
                # CANCELLED persists instead of being clobbered.
                GenerationJob.objects.filter(pk=job_id).update(drafts=drafts)
                return len(drafts) - before

            def log_failure(index, exc):
                logger.warning(
                    "Question generation job %s, part %s/%s: AI call failed: %s",
                    job_id, index + 1, len(chunks), exc,
                )

            for index in range(len(chunks)):
                # A chunk's quota is generated in calls of at most per_call
                # questions (#309): one call asked for all of them outgrew
                # AI_TIMEOUT / AI_MAX_TOKENS from ~10 questions on. Follow-up
                # calls list the existing questions so the model adds new ones.
                quota = min(quotas[index], target - len(drafts))
                produced = 0
                for _ in range(math.ceil(max(quota, 0) / per_call) + 1):
                    count = min(quota - produced, target - len(drafts), per_call)
                    if count <= 0:
                        break
                    if _is_cancelled(job_id):
                        return
                    try:
                        added = generate(index, count)
                    except (ai.AIError, ValueError, KeyError, TypeError) as exc:
                        log_failure(index, exc)
                        errors.append(classify_error(exc))
                        chunk_errored[index] = True
                        break
                    produced += added
                    if added == 0:
                        break  # nothing new from this part of the material
                if chunk_errored[index] and produced == 0:
                    failed_chunks += 1
                done += 1
                GenerationJob.objects.filter(pk=job_id).update(
                    drafts=drafts, done_chunks=done
                )
            # Top-up (#304): still short of the target (the model returned
            # fewer, or drafts were dropped as invalid/duplicates) — a few more
            # calls for the parts with the largest shortfall. Not for parts
            # that failed or that the model declined as unsuitable.
            for _ in range(TOPUP_CALLS):
                if not drafts or len(drafts) >= target:
                    break
                shortfalls = [
                    (quotas[i] - len(chunk_drafts[i]), -i)
                    for i in range(len(chunks))
                    if not chunk_errored[i] and not chunk_declined[i]
                ]
                shortfall, neg_index = max(shortfalls, default=(0, 0))
                if shortfall <= 0:
                    break
                index = -neg_index
                if _is_cancelled(job_id):
                    return
                try:
                    added = generate(
                        index, min(per_call, target - len(drafts), shortfall)
                    )
                except (ai.AIError, ValueError, KeyError, TypeError) as exc:
                    log_failure(index, exc)
                    break
                if added == 0:
                    break
            if not drafts and errors:
                # Nothing came out and calls failed: a real failure with a
                # reason the teacher can act on, not "0 questions generated" (#302).
                category = Counter(errors).most_common(1)[0][0]
                GenerationJob.objects.filter(pk=job_id).exclude(
                    status=GenerationJob.Status.CANCELLED
                ).update(
                    status=GenerationJob.Status.FAILED,
                    drafts=[],
                    done_chunks=done,
                    error=ERROR_MESSAGES[category],
                )
                return
            if failed_chunks:
                notice = (notice + " " + PARTIAL_FAILURE_NOTICE).strip()
            if not drafts and not notice:
                notice = "Aus dem Material ließen sich keine sinnvollen Fragen bilden."
            # Finish, unless the job was cancelled meanwhile — conditional so a
            # CANCELLED status is never overwritten with DONE.
            GenerationJob.objects.filter(pk=job_id).exclude(
                status=GenerationJob.Status.CANCELLED
            ).update(
                status=GenerationJob.Status.DONE,
                drafts=drafts,
                done_chunks=done,
                notice=notice,
                unsuitable_reason="" if drafts else reason,
            )
        except Exception:  # never leave a job stuck in running
            logger.exception("Question generation job %s failed", job_id)
            GenerationJob.objects.filter(pk=job_id).exclude(
                status=GenerationJob.Status.CANCELLED
            ).update(status=GenerationJob.Status.FAILED, error=ERROR_MESSAGES["other"])
    finally:
        # Return the worker's pooled connection (skip a mid-transaction one, as
        # TestCase wraps each test in an atomic block).
        for conn in connections.all():
            if not conn.in_atomic_block:
                conn.close()
