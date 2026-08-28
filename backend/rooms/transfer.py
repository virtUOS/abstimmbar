# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Question-set duplication and JSON file export/import (roadmap M3).

The export format is deliberately small and versioned. Results (runs/votes)
are never part of a transfer. Image references inside question HTML are
instance-local media URLs — they survive duplication within one instance,
but not a move to a different instance (known v1 limitation, roadmap).
Imported HTML is untrusted and goes through the nh3 allowlist.

Format v2 (#33 MR2 Task 6): every translatable field (QuestionSet
title/description, Section.title, Question.text, AnswerOption.text) is a
{"de": ..., "en": ...} map, like the authoring API's TranslatedMapMixin
(common/i18n_fields.py). v1 files — a plain string per translatable field —
are still accepted on import, written to the canonical language only (the
same "legacy plain string" convention TranslatedMapMixin uses).

CRITICAL: never read/write a translatable field through the bare accessor
here. The active language during a request is the author's UI language
(mozilla-django-oidc/i18next), which may differ from the content-canonical
language (settings.MODELTRANSLATION_DEFAULT_LANGUAGE) — always go through
the explicit ``<field>_de``/``<field>_en`` columns instead.
"""
from django.conf import settings
from rest_framework import serializers

from common.i18n_fields import LANGS, translated_map

from .models import AnswerOption, Question, QuestionSet, Section
from .naming import unique_title
from .sanitize import clean_html, clean_media_url

EXPORT_FORMAT = "abstimmbar-set-v2"
LEGACY_FORMAT = "abstimmbar-set-v1"
VALID_KINDS = {k.value for k in Question.Kind}
CONTENT_DEFAULT_LANGUAGE = settings.MODELTRANSLATION_DEFAULT_LANGUAGE


def _import_categories(value):
    """2–5 trimmed, unique category labels from a foreign file, else default."""
    from .models import default_verdicts

    cleaned, seen = [], set()
    for raw in value or []:
        label = str(raw).strip()[:40]
        key = label.casefold()
        if label and key not in seen:
            seen.add(key)
            cleaned.append(label)
    return cleaned if 2 <= len(cleaned) <= 5 else default_verdicts()


def _unique_in_room(room, base):
    # Dedupe on the canonical-language column — consistent with the
    # serializers' own uniqueness check (Task 2, keyed on title_<default>),
    # not the bare (active-language) accessor.
    canonical_key = f"title_{CONTENT_DEFAULT_LANGUAGE}"
    return unique_title(
        base,
        lambda t: room.question_sets.filter(**{f"{canonical_key}__iexact": t}).exists(),
    )


def _lang_columns(obj, base):
    """{"<base>_<lang>": value, ...} — an object's own per-language columns
    for a translatable field, read directly (never the bare accessor)."""
    return {f"{base}_{lang}": getattr(obj, f"{base}_{lang}") for lang in LANGS}


def _lang_map(value):
    """A v2 {lang: text} map, or a v1 plain string (-> canonical language
    only, e.g. every other legacy-string entry point in this MR)."""
    if isinstance(value, dict):
        return {lang: str(value.get(lang) or "").strip() for lang in LANGS}
    m = {lang: "" for lang in LANGS}
    m[CONTENT_DEFAULT_LANGUAGE] = str(value or "").strip()
    return m


# Non-translatable Question fields copied verbatim by duplicate_question and
# by the after-question sync (#54). `kind` and the `text_<lang>` columns are
# handled separately; `position`, `section`, `before_question` and results are
# deliberately excluded.
QUESTION_CONTENT_FIELDS = (
    "shuffle_options",
    "binary_choice",
    "time_limit",
    "allow_multiple",
    "wordcloud_live",
    "wordcloud_ai_enabled",
    "wordcloud_grouping",
    "wordcloud_max_answers",
    "reveal_answers",
    "ai_evaluate",
    "evaluation_hint",
    "evaluation_categories",
    "evaluation_chart",
)


def _copy_options(source, target):
    """Deep-copy ``source``'s answer options onto ``target`` (bulk create).

    Reads the options with a fresh query rather than ``source.options.all()``:
    the source may carry a stale prefetch cache (e.g. right after the
    before-question's options were rewritten in the same request, #54).
    """
    AnswerOption.objects.bulk_create(
        AnswerOption(
            question=target,
            **_lang_columns(option, "text"),
            image=option.image,
            is_correct=option.is_correct,
            is_abstention=option.is_abstention,
            position=option.position,
        )
        for option in AnswerOption.objects.filter(question=source)
    )


def duplicate_question(question, *, question_set, section, position):
    """Deep-copy a single question (content + options, no results) into a set.

    Reused by ``duplicate_set`` (whole-set copy) and by the "add after-question"
    action (#54). Language columns are copied verbatim; ``position``/``section``
    are set by the caller. The ``before_question`` link is the caller's job.
    """
    clone = Question.objects.create(
        question_set=question_set,
        kind=question.kind,
        **_lang_columns(question, "text"),
        **{field: getattr(question, field) for field in QUESTION_CONTENT_FIELDS},
        position=position,
        section=section,
    )
    _copy_options(question, clone)
    return clone


def sync_after_question(before):
    """Mirror ``before``'s content onto its linked after-question, if any (#54).

    Copies text + all content fields and replaces the after-question's options;
    keeps the after-question's own id/position/section/link and its results.
    No-op when the question has no after-question.
    """
    after = Question.objects.filter(before_question=before).first()
    if after is None:
        return
    after.kind = before.kind
    for lang in LANGS:
        setattr(after, f"text_{lang}", getattr(before, f"text_{lang}"))
    for field in QUESTION_CONTENT_FIELDS:
        setattr(after, field, getattr(before, field))
    after.save()
    after.options.all().delete()
    _copy_options(before, after)


def duplicate_set(question_set, target_room, title=None):
    """Deep-copy a set (questions + options, no results) into a room.

    Every translatable field's language columns are copied verbatim from the
    source. ``title``, if given, overrides the canonical language only (the
    caller — the ``duplicate`` API action — builds it as a single string,
    e.g. "<title> (Kopie)"); the copied non-canonical title is left as-is.
    """
    canonical_key = f"title_{CONTENT_DEFAULT_LANGUAGE}"
    title_cols = _lang_columns(question_set, "title")
    canonical_title = title if title is not None else title_cols[canonical_key]
    title_cols[canonical_key] = _unique_in_room(target_room, canonical_title or "")
    clone = QuestionSet.objects.create(
        room=target_room,
        # Copies never collide: a taken title gets a numbered suffix.
        **title_cols,
        **_lang_columns(question_set, "description"),
        type=question_set.type,
        reveal_answers=question_set.reveal_answers,
        open_on_show=question_set.open_on_show,
        show_results_to_participants=question_set.show_results_to_participants,
        # The license statement travels with the copy; the share link does not.
        license=question_set.license,
        license_holder=question_set.license_holder,
    )
    # Copy sections first so questions can point at the new ones (v2).
    section_map = {
        section.pk: Section.objects.create(
            question_set=clone,
            position=section.position,
            **_lang_columns(section, "title"),
        )
        for section in question_set.sections.all()
    }
    for question in question_set.questions.prefetch_related("options"):
        duplicate_question(
            question,
            question_set=clone,
            section=section_map.get(question.section_id),
            position=question.position,
        )
    return clone


def export_set(question_set):
    # Sections are referenced from questions by their index in this list.
    sections = list(question_set.sections.all())
    section_index = {section.pk: i for i, section in enumerate(sections)}
    return {
        "format": EXPORT_FORMAT,
        "title": translated_map(question_set, "title"),
        "description": translated_map(question_set, "description"),
        "type": question_set.type,
        "reveal_answers": question_set.reveal_answers,
        "open_on_show": question_set.open_on_show,
        "show_results_to_participants": question_set.show_results_to_participants,
        "license": question_set.license,
        "license_holder": question_set.license_holder,
        "sections": [
            {"title": translated_map(section, "title")} for section in sections
        ],
        "questions": [
            {
                "kind": question.kind,
                "text": translated_map(question, "text"),
                "shuffle_options": question.shuffle_options,
                "binary_choice": question.binary_choice,
                "time_limit": question.time_limit,
                "allow_multiple": question.allow_multiple,
                "wordcloud_live": question.wordcloud_live,
                "wordcloud_ai_enabled": question.wordcloud_ai_enabled,
                "wordcloud_grouping": question.wordcloud_grouping,
                "wordcloud_max_answers": question.wordcloud_max_answers,
                "reveal_answers": question.reveal_answers,
                "ai_evaluate": question.ai_evaluate,
                "evaluation_hint": question.evaluation_hint,
                "evaluation_categories": question.evaluation_categories,
                "evaluation_chart": question.evaluation_chart,
                "section": section_index.get(question.section_id),
                "options": [
                    {
                        "text": translated_map(option, "text"),
                        "image": option.image,
                        "is_correct": option.is_correct,
                        "is_abstention": option.is_abstention,
                    }
                    for option in question.options.all()
                ],
            }
            for question in question_set.questions.prefetch_related("options")
        ],
    }


def import_set(room, data):
    """Create a set in ``room`` from an export file's parsed JSON.

    Accepts both v2 files (translatable fields as {de,en} maps) and legacy
    v1 files (translatable fields as plain strings — written to the
    canonical language only). Detected per field by value type, so a v1
    file's plain strings and a v2 file's maps are both handled by the same
    code path; only the overall ``format`` marker is validated strictly.
    """
    if not isinstance(data, dict) or data.get("format") not in {
        EXPORT_FORMAT, LEGACY_FORMAT,
    }:
        raise serializers.ValidationError(
            {"format": f"Expected an {EXPORT_FORMAT} export file."}
        )
    title_map = {lang: v[:200] for lang, v in _lang_map(data.get("title")).items()}
    if not title_map[CONTENT_DEFAULT_LANGUAGE]:
        raise serializers.ValidationError({"title": "Missing title."})
    reveal = data.get("reveal_answers", QuestionSet.RevealAnswers.AFTER_CLOSE)
    if reveal not in {r.value for r in QuestionSet.RevealAnswers}:
        raise serializers.ValidationError({"reveal_answers": "Invalid value."})
    set_type = data.get("type", QuestionSet.SetType.LIVE_POLL)
    if set_type not in QuestionSet.SetType.values:
        set_type = QuestionSet.SetType.LIVE_POLL

    questions = data.get("questions") or []
    if not isinstance(questions, list):
        raise serializers.ValidationError({"questions": "Must be a list."})
    for item in questions:
        if not isinstance(item, dict) or item.get("kind") not in VALID_KINDS:
            raise serializers.ValidationError({"questions": "Invalid question."})

    # Foreign file: sanitize like any client input — per language (#49).
    description_map = {
        lang: clean_html(v) for lang, v in _lang_map(data.get("description")).items()
    }
    title_map[CONTENT_DEFAULT_LANGUAGE] = _unique_in_room(
        room, title_map[CONTENT_DEFAULT_LANGUAGE]
    )
    question_set = QuestionSet.objects.create(
        room=room,
        **{f"title_{lang}": (v or None) for lang, v in title_map.items()},
        **{f"description_{lang}": (v or None) for lang, v in description_map.items()},
        type=set_type,
        reveal_answers=reveal,
        open_on_show=bool(data.get("open_on_show")),
        show_results_to_participants=bool(data.get("show_results_to_participants")),
        license=(
            data.get("license")
            if data.get("license") in {c.value for c in QuestionSet.License}
            else ""
        ),
        license_holder=str(data.get("license_holder") or "")[:200],
    )
    # Sections first, so questions can reference them by index.
    imported_sections = []
    raw_sections = data.get("sections") or []
    if isinstance(raw_sections, list):
        for position, raw in enumerate(raw_sections):
            raw_title = raw.get("title") if isinstance(raw, dict) else None
            section_title = {
                lang: v[:200] for lang, v in _lang_map(raw_title).items()
            }
            if not section_title[CONTENT_DEFAULT_LANGUAGE]:
                section_title[CONTENT_DEFAULT_LANGUAGE] = f"Abschnitt {position + 1}"
            imported_sections.append(
                Section.objects.create(
                    question_set=question_set,
                    position=position,
                    **{f"title_{lang}": (v or None) for lang, v in section_title.items()},
                )
            )
    for position, item in enumerate(questions):
        raw_limit = item.get("time_limit")
        time_limit = (
            int(raw_limit)
            if isinstance(raw_limit, int) and 0 < raw_limit <= 3600
            else None
        )
        raw_max = item.get("wordcloud_max_answers")
        wc_max = int(raw_max) if isinstance(raw_max, int) and raw_max > 0 else 0
        raw_section = item.get("section")
        section = (
            imported_sections[raw_section]
            if isinstance(raw_section, int) and 0 <= raw_section < len(imported_sections)
            else None
        )
        # Foreign file: sanitize like any client input — per language.
        text_map = {
            lang: clean_html(v) for lang, v in _lang_map(item.get("text")).items()
        }
        question = Question.objects.create(
            question_set=question_set,
            kind=item["kind"],
            **{f"text_{lang}": (v or None) for lang, v in text_map.items()},
            shuffle_options=bool(item.get("shuffle_options")),
            binary_choice=bool(item.get("binary_choice")),
            time_limit=time_limit,
            allow_multiple=bool(item.get("allow_multiple")),
            wordcloud_live=bool(item.get("wordcloud_live", True)),
            wordcloud_ai_enabled=bool(item.get("wordcloud_ai_enabled")),
            wordcloud_grouping=str(item.get("wordcloud_grouping") or "")[:2000],
            wordcloud_max_answers=wc_max,
            ai_evaluate=bool(item.get("ai_evaluate")),
            evaluation_hint=str(item.get("evaluation_hint") or "")[:2000],
            evaluation_categories=_import_categories(item.get("evaluation_categories")),
            evaluation_chart=bool(item.get("evaluation_chart")),
            reveal_answers=(
                item.get("reveal_answers")
                if item.get("reveal_answers") in Question.RevealAnswers.values
                else Question.RevealAnswers.INHERIT
            ),
            position=position,
            section=section,
        )
        if item["kind"] in Question.TEXT_KINDS:
            continue
        options = item.get("options") or []
        AnswerOption.objects.bulk_create(
            AnswerOption(
                question=question,
                **{
                    f"text_{lang}": (v[:500] or None)
                    for lang, v in _lang_map(option.get("text")).items()
                },
                # Foreign file: same media-only rule as client input.
                image=clean_media_url(str(option.get("image") or "")),
                is_correct=bool(option.get("is_correct")),
                is_abstention=bool(option.get("is_abstention")),
                position=position_option,
            )
            for position_option, option in enumerate(options)
            if isinstance(option, dict)
        )
    return question_set
