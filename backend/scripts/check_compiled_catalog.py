# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""CI check: the committed gettext catalog (.mo) matches its source (.po).

Pure Python (Babel), so CI needs no system gettext from the Ubuntu mirrors.
It compares the translations msgfmt / `compilemessages` would compile — the
.po's non-fuzzy, translated, non-obsolete entries — with the entries in the
committed .mo, ignoring the header. Any added, missing or changed
translation fails.

    pip install babel
    python scripts/check_compiled_catalog.py [locale/de/LC_MESSAGES/django]
"""

import sys
from pathlib import Path

from babel.messages.mofile import read_mo
from babel.messages.pofile import read_po


def _plain(value):
    """Plural ids/strings come as tuples from the .po and as lists from the
    .mo; make both hashable and comparable."""
    return tuple(value) if isinstance(value, (list, tuple)) else value


def _translated(catalog, *, skip_fuzzy):
    entries = {}
    for message in catalog:
        if not message.id:  # header
            continue
        if skip_fuzzy and message.fuzzy:
            continue
        string = _plain(message.string)
        strings = string if isinstance(string, tuple) else (string,)
        if not any(strings):  # untranslated: msgfmt leaves it out
            continue
        entries[(message.context, _plain(message.id))] = string
    return entries


def main(base: str = "locale/de/LC_MESSAGES/django") -> int:
    po_path, mo_path = Path(f"{base}.po"), Path(f"{base}.mo")
    with po_path.open("rb") as f:
        expected = _translated(read_po(f), skip_fuzzy=True)
    with mo_path.open("rb") as f:
        committed = _translated(read_mo(f), skip_fuzzy=False)

    problems = []
    for key in sorted(expected.keys() - committed.keys(), key=repr):
        problems.append(f"missing in .mo: {key[1]!r}")
    for key in sorted(committed.keys() - expected.keys(), key=repr):
        problems.append(f"only in .mo:    {key[1]!r}")
    for key in sorted(expected.keys() & committed.keys(), key=repr):
        if expected[key] != committed[key]:
            problems.append(f"changed:        {key[1]!r}: .mo {committed[key]!r} != .po {expected[key]!r}")

    if problems:
        print("\n".join(problems))
        print(f"{mo_path} is out of date: run compilemessages -l de and commit it.")
        return 1
    print(f"{mo_path} matches {po_path} ({len(expected)} translations).")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
