# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Server-side Markdown rendering for the framework-free participant page.

The participant page is a plain Django template, so Markdown content (e.g. the
run's closing info, #24) is rendered to HTML on the server and passed through
the shared rich-HTML allowlist (``basicbar_integrations.html_sanitize.clean_html``) — the same
boundary the WYSIWYG editor uses. Tables/H1/blockquote from Markdown are not in
that subset and get unwrapped; links keep rel="noopener", images stay /media/.

Kept as a migration/back-compat tool while stored content is still Markdown;
MR-B migrates those fields to stored HTML.
"""
import markdown as _markdown
from basicbar_integrations.html_sanitize import clean_html


def render_markdown(text):
    """Render Markdown to HTML, then clamp to the shared rich-HTML allowlist."""
    if not text:
        return ""
    html = _markdown.markdown(
        text, extensions=["extra", "sane_lists", "nl2br"], output_format="html"
    )
    return clean_html(html)
