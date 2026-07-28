# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Shared Markdown→HTML conversion for the one-off editor-unify migrations
(rooms 0026, common 0006). Renders Markdown to HTML and clamps to the shared
rich-HTML allowlist — identical to common.markdown.render_markdown, imported
lazily so migrations don't hard-depend on app import order."""


def md_to_html(text):
    if not text:
        return ""
    from common.markdown import render_markdown

    return render_markdown(text)


def convert_fields(apps, app_label, model_name, base_fields, langs=("de", "en")):
    """For every row of ``app_label.model_name``, convert each
    ``{base}_{lang}`` column from Markdown to sanitized HTML in place."""
    Model = apps.get_model(app_label, model_name)
    for obj in Model.objects.all().iterator():
        changed_cols = []
        for base in base_fields:
            for lang in langs:
                col = f"{base}_{lang}"
                old = getattr(obj, col, None)
                if old:
                    new = md_to_html(old)
                    if new != old:
                        setattr(obj, col, new)
                        changed_cols.append(col)
        if changed_cols:
            obj.save(update_fields=changed_cols)
