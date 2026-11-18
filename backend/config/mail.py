# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""E-mail settings derived from the environment: the feature flag and the
Django 6.1 ``MAILERS`` setting.

Pure functions so settings.py can use them without importing any app.
"""

from collections.abc import Mapping


def mail_enabled(env: Mapping[str, str]) -> bool:
    """Explicit ``MAIL_ENABLED`` ("1"/"0") wins; empty or unset means on
    exactly when an SMTP host and a sender address are configured."""
    explicit = env.get("MAIL_ENABLED", "")
    if explicit != "":
        return explicit == "1"
    return bool(env.get("EMAIL_HOST", "") and env.get("DEFAULT_FROM_EMAIL", ""))


SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    try:
        return int(env.get(name, ""))
    except (TypeError, ValueError):
        return default


def mailers_from_env(env: Mapping[str, str]) -> dict:
    """``MAILERS`` from the (unchanged) ``EMAIL_*`` variables.

    Django 6.1 validates OPTIONS against the chosen backend and rejects
    unknown ones, so the SMTP options go only to the SMTP backend — the
    console/locmem/file backends (dev, tests) get none."""
    backend = env.get("EMAIL_BACKEND", "") or SMTP_BACKEND
    if backend != SMTP_BACKEND:
        return {"default": {"BACKEND": backend}}
    use_ssl = env.get("EMAIL_USE_SSL", "0") == "1"
    return {
        "default": {
            "BACKEND": backend,
            "OPTIONS": {
                "host": env.get("EMAIL_HOST", ""),
                "port": _int(env, "EMAIL_PORT", 587),
                "username": env.get("EMAIL_HOST_USER", ""),
                "password": env.get("EMAIL_HOST_PASSWORD", ""),
                "use_ssl": use_ssl,
                # Django forbids both at once; implicit TLS (SSL) wins.
                "use_tls": env.get("EMAIL_USE_TLS", "1") == "1" and not use_ssl,
                "timeout": _int(env, "EMAIL_TIMEOUT", 10),
            },
        },
    }
