# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Title helpers: readable defaults and uniqueness (v2 review feedback).

Room titles are unique per user, set titles per room — enforced at the
API layer (existing duplicates are deliberately left alone). Copies and
imports get a numbered suffix instead of an error.
"""
from django.utils import timezone

MONTHS = {
    "de": [
        "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember",
    ],
    "en": [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ],
}

MAX_TITLE_LENGTH = 200


def _format_default(prefix, lang, now):
    month = MONTHS[lang][now.month - 1]
    if lang == "de":
        # "Unbenannter Raum vom 7. Juli 2026, 12:30"
        return f"{prefix} vom {now.day}. {month} {now.year}, {now:%H:%M}"
    # "Unnamed room from July 7, 2026, 12:30 PM"
    hour12 = now.hour % 12 or 12
    ampm = "AM" if now.hour < 12 else "PM"
    return f"{prefix} from {month} {now.day}, {now.year}, {hour12}:{now.minute:02d} {ampm}"


def default_titles(prefixes):
    """Localized default titles for content that was saved without a title.

    `prefixes` maps a language code to its prefix, e.g.
    ``{"de": "Unbenannter Raum", "en": "Unnamed room"}``. Returns a
    ``{lang: title}`` dict; all languages share one timestamp so the
    variants stay in lockstep (#19)."""
    now = timezone.localtime()
    return {lang: _format_default(prefix, lang, now) for lang, prefix in prefixes.items()}


def generate_default_titles(prefixes, canonical_lang, exists):
    """Localized default titles with the canonical one made unique (#19).

    Uniqueness is enforced only on the canonical language (the column the
    API checks); the same numeric suffix is mirrored onto the other
    languages so a room shows as "… (2)" consistently in every language."""
    titles = default_titles(prefixes)
    base = titles[canonical_lang]
    unique = unique_title(base, exists)
    titles[canonical_lang] = unique
    suffix = unique[len(base):] if unique.startswith(base) else ""
    if suffix:
        for lang in titles:
            if lang != canonical_lang:
                titles[lang] = (titles[lang] + suffix)[:MAX_TITLE_LENGTH]
    return titles


def unique_title(base, exists):
    """Return ``base`` or ``base (2)``, ``base (3)``, … until ``exists``
    (a callable taking a candidate title) no longer matches."""
    title = base[:MAX_TITLE_LENGTH]
    counter = 2
    while exists(title):
        suffix = f" ({counter})"
        title = base[: MAX_TITLE_LENGTH - len(suffix)] + suffix
        counter += 1
    return title
