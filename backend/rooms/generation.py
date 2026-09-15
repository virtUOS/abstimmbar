# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Chunking, dedup and the background worker for async question generation."""
import re


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
    return _PUNCT.sub("", (text or "")).casefold().split().__str__()


def merge_drafts(existing, new):
    seen = {norm_question(d.get("text", "")) for d in existing}
    out = list(existing)
    for draft in new:
        key = norm_question(draft.get("text", ""))
        if key and key not in seen:
            seen.add(key)
            out.append(draft)
    return out
