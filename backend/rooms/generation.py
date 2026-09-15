# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Chunking, dedup and the background worker for async question generation."""
import re

from basicbar_integrations import ai
from django.conf import settings
from django.db import connections

from . import ai_generate
from .models import GenerationJob


def chunk_text(text, *, chunk_chars, max_chunks):
    """Split text into ~chunk_chars pieces at whitespace boundaries. Returns
    (chunks, truncated); truncated is True when more than max_chunks pieces
    would result (only the first max_chunks are returned)."""
    words = text.split()
    chunks, current, length = [], [], 0
    for word in words:
        if current and length + 1 + len(word) > chunk_chars:
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
    GenerationJob.objects.filter(status=GenerationJob.Status.RUNNING).update(
        status=GenerationJob.Status.FAILED, error="Unterbrochen (Server-Neustart)."
    )


def run_generation_job(job_id):
    connections.close_all()  # fresh DB connection for this worker thread
    job = GenerationJob.objects.filter(pk=job_id).first()
    if job is None or job.status == GenerationJob.Status.CANCELLED:
        return
    try:
        chunks, truncated = chunk_text(
            job.source_text,
            chunk_chars=settings.AI_CHUNK_CHARS,
            max_chunks=settings.AI_GEN_MAX_CHUNKS,
        )
        job.total_chunks = len(chunks)
        job.truncated = truncated
        job.status = GenerationJob.Status.RUNNING
        if truncated:
            job.notice = (
                f"Das Dokument ({job.source_chars or len(job.source_text)} Zeichen) "
                f"überschreitet die Verarbeitungsgrenze — es wurden die ersten "
                f"{len(chunks)} Abschnitte ausgewertet."
            )
        job.save()
        failed_chunks = 0
        for chunk in chunks:
            fresh = GenerationJob.objects.filter(pk=job_id).values_list("status", flat=True).first()
            if fresh == GenerationJob.Status.CANCELLED:
                return
            per = settings.AI_GEN_PER_CHUNK
            try:
                data = ai.chat_json(
                    ai_generate.generate_system(),
                    ai_generate.build_generate_prompt(chunk, per, job.kinds, job.level, job.guidance),
                )
                new = ai_generate.build_drafts(data, job.kinds, per)
                job.drafts = merge_drafts(job.drafts, new)[: settings.AI_GEN_POOL_MAX]
            except (ai.AIError, ValueError, KeyError, TypeError):
                failed_chunks += 1
            job.done_chunks += 1
            job.save()
            if len(job.drafts) >= settings.AI_GEN_POOL_MAX:
                break
        if failed_chunks:
            extra = f" {failed_chunks} Abschnitt(e) konnten nicht ausgewertet werden."
            job.notice = (job.notice + extra).strip()
        if not job.drafts and not job.notice:
            job.notice = "Aus dem Material ließen sich keine sinnvollen Fragen bilden."
        job.status = GenerationJob.Status.DONE
        job.save()
    except Exception as exc:  # noqa: BLE001 -- never leave a job stuck in running
        GenerationJob.objects.filter(pk=job_id).update(
            status=GenerationJob.Status.FAILED, error=str(exc)[:2000]
        )
