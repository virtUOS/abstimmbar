# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Authoring rules of the mindmap question kind (stage 1).

A mindmap question carries optional *predefined branches* (``mindmap_seed``):
a nested list ``[{"text", "description", "children": [...]}]`` of plain
canonical-language terms below the root. Levels count from the root's
children (level 1) down to ``mindmap_depth`` — the same rule the live side
applies to participant contributions. Sibling terms are deduplicated the way
participants' terms merge (``text_key``), so materialising the seed per run
never collides with the live uniqueness constraint.
"""

import unicodedata

MINDMAP_MIN_DEPTH = 1
MINDMAP_MAX_DEPTH = 8
MINDMAP_DEFAULT_DEPTH = 5
MINDMAP_DEFAULT_MAX_PER_PERSON = 10
MINDMAP_MAX_PER_PERSON_LIMIT = 300
MINDMAP_TEXT_MAX = 60
MINDMAP_DESCRIPTION_MAX = 200
MINDMAP_SEED_MAX_NODES = 100


class SeedError(ValueError):
    """An invalid predefined-branches structure (strict mode)."""


def normalize_text(value):
    """How terms and descriptions are stored: Unicode NFKC (so composed and
    decomposed "Café" are the same string), every whitespace character a
    plain space, other control/format characters (Cc/Cf: NUL, zero-width
    space/joiner, BOM, bidi marks …) dropped, whitespace collapsed and
    stripped. NUL must never reach Postgres."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    cleaned = []
    for char in text:
        if char.isspace():
            cleaned.append(" ")
        elif unicodedata.category(char) not in ("Cc", "Cf"):
            cleaned.append(char)
    return " ".join("".join(cleaned).split())


def text_key(value):
    """Merge key for terms under one parent: normalised, case-insensitive.
    Shared with the live side (identical terms = one node). Casefolding can
    lengthen a term ("ß" → "ss"), so the key is cut to the column length
    (MINDMAP_TEXT_MAX): two terms differing only beyond that point merge."""
    return normalize_text(value).casefold()[:MINDMAP_TEXT_MAX]


def clean_seed(value, max_level, *, strict=True):
    """Return the normalised seed tree.

    ``strict`` (editor API) raises SeedError on the first problem; lenient
    mode (imports of foreign files) drops/truncates instead: invalid nodes and
    duplicate siblings are skipped, over-long text is cut, levels beyond
    ``max_level`` and nodes beyond the overall cap are dropped.
    """
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        if strict:
            raise SeedError("Predefined branches must be a list.")
        return []
    count = 0

    def walk(nodes, level):
        nonlocal count
        result, seen = [], set()
        for raw in nodes:
            if not isinstance(raw, dict):
                if strict:
                    raise SeedError("Invalid branch.")
                continue
            text = normalize_text(raw.get("text"))
            description = normalize_text(raw.get("description"))
            children = raw.get("children") or []
            if not text:
                if strict:
                    raise SeedError("Every branch needs a term.")
                continue
            if len(text) > MINDMAP_TEXT_MAX:
                if strict:
                    raise SeedError(
                        f"A term may have at most {MINDMAP_TEXT_MAX} characters."
                    )
                text = text[:MINDMAP_TEXT_MAX].strip()
            if len(description) > MINDMAP_DESCRIPTION_MAX:
                if strict:
                    raise SeedError(
                        "A description may have at most "
                        f"{MINDMAP_DESCRIPTION_MAX} characters."
                    )
                description = description[:MINDMAP_DESCRIPTION_MAX].strip()
            if not isinstance(children, list):
                if strict:
                    raise SeedError("Invalid branch.")
                children = []
            key = text_key(text)
            if key in seen:
                if strict:
                    raise SeedError(f"“{text}” appears twice at the same place.")
                continue
            if level > max_level:
                if strict:
                    raise SeedError(
                        "The predefined branches are deeper than the allowed depth."
                    )
                continue
            if count >= MINDMAP_SEED_MAX_NODES:
                if strict:
                    raise SeedError(
                        f"At most {MINDMAP_SEED_MAX_NODES} predefined terms."
                    )
                continue
            seen.add(key)
            count += 1
            result.append(
                {
                    "text": text,
                    "description": description,
                    "children": walk(children, level + 1),
                }
            )
        return result

    return walk(value, 1)


def clamp_depth(value):
    """Depth from foreign input: an int in 1–8, else the default."""
    if isinstance(value, int) and not isinstance(value, bool) and (
        MINDMAP_MIN_DEPTH <= value <= MINDMAP_MAX_DEPTH
    ):
        return value
    return MINDMAP_DEFAULT_DEPTH


def clamp_max_per_person(value):
    """Terms per person from foreign input: 0 (unlimited) … limit, else default."""
    if isinstance(value, int) and not isinstance(value, bool) and (
        0 <= value <= MINDMAP_MAX_PER_PERSON_LIMIT
    ):
        return value
    return MINDMAP_DEFAULT_MAX_PER_PERSON
