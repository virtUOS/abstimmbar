# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Chunking, dedup and the background worker for async question generation."""
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor

from basicbar_integrations import ai
from django.conf import settings
from django.db import connections

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


def _is_cancelled(job_id):
    status = (
        GenerationJob.objects.filter(pk=job_id).values_list("status", flat=True).first()
    )
    return status == GenerationJob.Status.CANCELLED


def chunk_text(text, *, chunk_chars, max_chunks):
    """Split text at whitespace, growing the chunk size (up to 2*chunk_chars)
    so a document up to roughly 2*chunk_chars*max_chunks is covered in one pass.
    Returns (chunks, truncated); truncated is True when the (greedy) packing
    still needs more than max_chunks chunks, in which case the tail is dropped
    and the caller surfaces a notice — nothing is ever dropped silently."""
    words = text.split()
    total = sum(len(w) for w in words) + max(0, len(words) - 1)
    size = 2 * chunk_chars
    if max_chunks:
        size = min(2 * chunk_chars, max(chunk_chars, math.ceil(total / max_chunks)))
    chunks, current, length = [], [], 0
    for word in words:
        if current and length + 1 + len(word) > size:
            chunks.append(" ".join(current))
            current, length = [], 0
        current.append(word)
        length += (1 if length else 0) + len(word)
    if current:
        chunks.append(" ".join(current))
    truncated = len(chunks) > max_chunks
    return chunks[:max_chunks], truncated


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
            chunks, truncated = chunk_text(
                job.source_text,
                chunk_chars=settings.AI_CHUNK_CHARS,
                max_chunks=settings.AI_GEN_MAX_CHUNKS,
            )
            notice = ""
            if truncated:
                notice = (
                    f"Das Dokument ({job.source_chars or len(job.source_text)} Zeichen) "
                    f"überschreitet die Verarbeitungsgrenze — es wurden die ersten "
                    f"{len(chunks)} Abschnitte ausgewertet."
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
            done = 0
            drafts = list(job.drafts)
            reason = ""
            target = job.target_count or settings.AI_GEN_MAX_QUESTIONS
            num = max(1, len(chunks))
            per = max(1, round(target / num))
            per_call = max(1, settings.AI_GEN_PER_CALL)
            system = ai_generate.generate_system()
            for index, chunk in enumerate(chunks):
                # A chunk's quota is generated in calls of at most per_call
                # questions (#309): one call asked for all of them outgrew
                # AI_TIMEOUT / AI_MAX_TOKENS from ~10 questions on. Follow-up
                # calls list the existing questions so the model adds new ones.
                quota = min(per, target - len(drafts))
                if quota <= 0:
                    break
                produced = 0
                chunk_failed = False
                for _ in range(math.ceil(quota / per_call) + 1):
                    count = min(quota - produced, target - len(drafts), per_call)
                    if count <= 0:
                        break
                    if _is_cancelled(job_id):
                        return
                    try:
                        data = ai.chat_json(
                            system,
                            ai_generate.build_generate_prompt(
                                chunk, count, job.kinds, job.level, job.guidance,
                                focus_kinds=job.focus_kinds,
                                avoid=[d.get("text", "") for d in drafts],
                            ),
                            max_tokens=call_max_tokens(count),
                        )
                        new = ai_generate.build_drafts(data, job.kinds, count)
                        reason = reason or ai_generate.unsuitable_reason(data)
                    except (ai.AIError, ValueError, KeyError, TypeError) as exc:
                        logger.warning(
                            "Question generation job %s, part %s/%s: AI call failed: %s",
                            job_id, index + 1, len(chunks), exc,
                        )
                        chunk_failed = True
                        break
                    before = len(drafts)
                    drafts = merge_drafts(drafts, new)[:target]
                    added = len(drafts) - before
                    produced += added
                    # Progress write: never touches status, so a concurrent
                    # CANCELLED persists instead of being clobbered.
                    GenerationJob.objects.filter(pk=job_id).update(drafts=drafts)
                    if added == 0:
                        break  # nothing new from this part of the material
                if chunk_failed and produced == 0:
                    failed_chunks += 1
                done += 1
                GenerationJob.objects.filter(pk=job_id).update(
                    drafts=drafts, done_chunks=done
                )
                if len(drafts) >= target:
                    break
            if failed_chunks:
                extra = f" {failed_chunks} Abschnitt(e) konnten nicht ausgewertet werden."
                notice = (notice + extra).strip()
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
        except Exception as exc:  # noqa: BLE001 -- never leave a job stuck in running
            GenerationJob.objects.filter(pk=job_id).exclude(
                status=GenerationJob.Status.CANCELLED
            ).update(status=GenerationJob.Status.FAILED, error=str(exc)[:2000])
    finally:
        # Return the worker's pooled connection (skip a mid-transaction one, as
        # TestCase wraps each test in an atomic block).
        for conn in connections.all():
            if not conn.in_atomic_block:
                conn.close()
