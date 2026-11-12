# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""E-mail feature flag, derived from the environment.

Pure function so settings.py can use it without importing any app.
"""

from collections.abc import Mapping


def mail_enabled(env: Mapping[str, str]) -> bool:
    """Explicit ``MAIL_ENABLED`` ("1"/"0") wins; empty or unset means on
    exactly when an SMTP host and a sender address are configured."""
    explicit = env.get("MAIL_ENABLED", "")
    if explicit != "":
        return explicit == "1"
    return bool(env.get("EMAIL_HOST", "") and env.get("DEFAULT_FROM_EMAIL", ""))
