# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)
"""Confirmation of motion-text translations (spec § 7.6).

Members see the text in the canonical language only, until the chair has
confirmed the other language. A confirmation is bound to a digest of the
current wording (text and options, both languages): any change — an edit
before the start or a new version after it — makes the stored digest stale,
so the translation is withheld again until it is confirmed anew. Nothing
here touches ``MotionVersion`` (seals hash its fields)."""
import hashlib
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from rooms.models import Question

from . import versions
from .models import Ballot, TranslationApproval

LANGUAGES = ("de", "en")
CHOICE_KINDS = (
    Question.Kind.SINGLE_CHOICE, Question.Kind.MULTIPLE_CHOICE, Question.Kind.ELECTION,
)


def canonical_language() -> str:
    return settings.MODELTRANSLATION_DEFAULT_LANGUAGE


def other_language() -> str:
    canonical = canonical_language()
    return next(lang for lang in LANGUAGES if lang != canonical)


def maps_of_version(question: Question, version) -> dict:
    """Wording maps of a frozen version (options only for choice kinds)."""
    options = []
    if question.kind in CHOICE_KINDS:
        options = [
            {"id": o["id"], "text": {"de": o["text_de"], "en": o["text_en"]}}
            for o in version.options
        ]
    return {
        "text": {"de": version.text_de, "en": version.text_en},
        "options": options,
        "version": version.number,
    }


def wording_maps(question: Question) -> dict:
    version = versions.current(question)
    if version is not None:
        return maps_of_version(question, version)
    options = []
    if question.kind in CHOICE_KINDS:
        options = [
            {"id": o.pk, "text": {"de": o.text_de or "", "en": o.text_en or ""}}
            for o in question.options.order_by("position", "id")
        ]
    return {
        "text": {"de": question.text_de or "", "en": question.text_en or ""},
        "options": options,
        "version": None,
    }


def digest(maps: dict) -> str:
    body = json.dumps(
        {"text": maps["text"], "options": maps["options"]},
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(body.encode()).hexdigest()


def is_confirmed(maps: dict, approval: TranslationApproval | None) -> bool:
    """Confirmed: the other-language text exists and the approval is for
    exactly this wording."""
    return (
        approval is not None
        and bool((maps["text"][other_language()] or "").strip())
        and approval.digest == digest(maps)
    )


def approvals(question_ids) -> dict[int, TranslationApproval]:
    return {
        a.question_id: a
        for a in TranslationApproval.objects.filter(question_id__in=list(question_ids))
    }


def status_of(maps: dict, approval: TranslationApproval | None) -> str:
    if not (maps["text"][other_language()] or "").strip():
        return "none"
    return "confirmed" if is_confirmed(maps, approval) else "pending"


def status(question: Question) -> str:
    approval = TranslationApproval.objects.filter(question=question).first()
    return status_of(wording_maps(question), approval)


def text_i18n(value: dict, confirmed: bool) -> dict:
    """``{other: text}`` for a confirmed translation, else empty."""
    other = other_language()
    return {other: value[other]} if confirmed and (value[other] or "").strip() else {}


def review(question: Question) -> dict:
    maps = wording_maps(question)
    approval = TranslationApproval.objects.filter(question=question).first()
    return {
        "canonical": canonical_language(),
        "other": other_language(),
        "status": status_of(maps, approval),
        "digest": digest(maps),
        **maps,
    }


def confirm(question: Question, expected_digest: str) -> None:
    """Confirm the translation as shown (``expected_digest``)."""
    from .ballots import ballots_for  # ballots imports versions

    maps = wording_maps(question)
    if not (maps["text"][other_language()] or "").strip():
        raise ValidationError("There is no translation to confirm.", code="empty")
    if ballots_for(question).filter(status=Ballot.Status.OPEN).exists():
        raise ValidationError("A vote on this item is open.", code="vote_open")
    if expected_digest != digest(maps):
        raise ValidationError(
            "The wording has changed. Please review it again.", code="stale",
        )
    TranslationApproval.objects.update_or_create(
        question=question,
        defaults={"digest": digest(maps), "confirmed_at": timezone.now()},
    )
