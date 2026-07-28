# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""HTML sanitizing for authored rich content (ADR-0007, #49).

The one allowlist now lives in ``basicbar_integrations.html_sanitize`` (shared by rooms +
common). This module re-exports it so existing rooms imports keep working.
"""
from basicbar_integrations.html_sanitize import clean_html, clean_media_url

__all__ = ["clean_html", "clean_media_url"]
