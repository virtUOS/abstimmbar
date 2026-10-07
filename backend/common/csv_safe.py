# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""CSV formula-injection guard for exports of participant-authored text."""

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value):
    """Prefix a text cell that a spreadsheet would read as a formula
    (= + - @ tab CR) with an apostrophe. Non-strings pass unchanged."""
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value
