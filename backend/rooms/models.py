# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Authoring side (ADR-0002): Room, QuestionSet, Question, AnswerOption.

``Section`` (optional named groups inside a set) is a v2 feature; questions
carry a flat ``position`` so sections can be added later without remodeling.
"""
import secrets
from typing import ClassVar

from django.conf import settings
from django.db import IntegrityError, models

from common.models import TimeStampedModel

from .wordlist import WORDS

# Room codes are three ASCII words joined by hyphens (ADR-0006), e.g.
# "tiger-komet-radio" — memorable and easy to say/type/QR. ~500 words give
# >10^8 combinations (more than the old 8 digits); collisions are retried.
# Existing numeric codes stay valid; the column is wide enough for both.
ROOM_CODE_WORDS = 3
ROOM_CODE_LENGTH = 60


def generate_room_code():
    return "-".join(secrets.choice(WORDS) for _ in range(ROOM_CODE_WORDS))


def default_verdicts():
    """Default AI free-text scale: the correctness verdicts (unchanged
    behaviour for existing questions). A JSONField default must be callable."""
    return ["korrekt", "unklar", "falsch"]


class Room(TimeStampedModel):
    """The stable container participants enter (concept §3.1).

    The code survives across runs and semesters so students can bookmark it;
    rooms are reusable for different groups (review decision, July 2026).
    """

    code = models.CharField(max_length=ROOM_CODE_LENGTH, unique=True, editable=False)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    owners = models.ManyToManyField(settings.AUTH_USER_MODEL, related_name="rooms")
    # The "Besitzer": the one owner who may delete the room or hand it over
    # (#25/#26). Distinct from created_by (audit): ownership is transferable,
    # authorship is not. Always one of ``owners``; SET_NULL only guards
    # account deletion (a fresh owner is picked by the app in that case).
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="owned_rooms",
    )
    # Provenance (v2 review feedback): who created the room and who last
    # edited it. SET_NULL so removing an account keeps the room intact.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="created_rooms",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="+",
    )
    # Show the institution logo (SiteConfig) on the beamer during a run.
    show_logo_in_presentation = models.BooleanField(default=True)
    # Keep the join QR code / room code permanently on the beamer so latecomers
    # can still join mid-run (#6). Which corner they sit in is configurable.
    show_qr_in_presentation = models.BooleanField(default=False)
    show_code_in_presentation = models.BooleanField(default=False)
    # Markdown shown to participants once the vote is finished, below any
    # system-wide closing info (#24); may include links and images.
    closing_info = models.TextField(blank=True, default="")

    class PresentationCorner(models.TextChoices):
        TOP_LEFT = "top-left", "oben links"
        TOP_RIGHT = "top-right", "oben rechts"
        BOTTOM_LEFT = "bottom-left", "unten links"
        BOTTOM_RIGHT = "bottom-right", "unten rechts"

    presentation_corner = models.CharField(
        max_length=12,
        choices=PresentationCorner.choices,
        default=PresentationCorner.BOTTOM_RIGHT,
    )
    # Per-user favourites (heart). A room can be favourited by several of its
    # owners independently.
    favorited_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="favorite_rooms", blank=True
    )
    # Per-user archive (analogous to favourites): hides the room from the
    # owner's overview into a separate archive page, reversible (#16).
    archived_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name="archived_rooms", blank=True
    )

    class Meta:
        ordering: ClassVar = ["-updated_at"]

    def save(self, *args, **kwargs):
        if self.code:
            return super().save(*args, **kwargs)
        # Retry on the (astronomically rare) code collision.
        for _ in range(20):
            self.code = generate_room_code()
            try:
                return super().save(*args, **kwargs)
            except IntegrityError:
                continue
        raise IntegrityError("Could not allocate a unique room code.")

    def __str__(self):
        return f"{self.title} ({self.code})"


class QuestionSet(TimeStampedModel):
    """An ordered series of questions inside a room (concept §3.1)."""

    class RevealAnswers(models.TextChoices):
        # When correct answers are highlighted (review decision: configurable).
        IMMEDIATELY = "immediately", "Immediately with the results"
        AFTER_CLOSE = "after_close", "After closing, on key press"
        NEVER = "never", "Never"

    class License(models.TextChoices):
        # Optional license shown to colleagues who copy a shared set (v2,
        # "Teilen & Zusammenarbeit"). Empty = no statement.
        CC0 = "cc0", "CC0 (public domain)"
        CC_BY = "cc-by", "CC BY 4.0"
        CC_BY_SA = "cc-by-sa", "CC BY-SA 4.0"
        CC_BY_NC = "cc-by-nc", "CC BY-NC 4.0"
        CC_BY_NC_SA = "cc-by-nc-sa", "CC BY-NC-SA 4.0"
        COPYRIGHT = "copyright", "© All rights reserved"

    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="question_sets")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    reveal_answers = models.CharField(
        max_length=20, choices=RevealAnswers.choices, default=RevealAnswers.AFTER_CLOSE
    )
    # Presenter flow option: calling up a question immediately opens it for
    # answering (skips the separate preview → S step).
    open_on_show = models.BooleanField(default=False)
    # v2: participants see the results of a closed question on their own
    # device (correct answers only once revealed, per reveal_answers).
    show_results_to_participants = models.BooleanField(default=False)
    # v2 "Teilen & Zusammenarbeit": a non-guessable token makes the set
    # copyable by any logged-in colleague who has the link; null = not
    # shared. The optional license travels with copies and exports.
    share_token = models.CharField(
        max_length=32, unique=True, null=True, blank=True, editable=False
    )
    license = models.CharField(
        max_length=20, choices=License.choices, blank=True, default=""
    )
    # Rights holder shown with the license (esp. © Copyright and CC BY
    # attribution); prefilled with the author's name in the UI. Travels
    # with copies/exports like the license itself.
    license_holder = models.CharField(max_length=200, blank=True, default="")

    class Meta:
        ordering: ClassVar = ["-updated_at"]

    def enable_sharing(self):
        if not self.share_token:
            self.share_token = secrets.token_urlsafe(16)[:32]
            self.save(update_fields=["share_token", "updated_at"])

    def disable_sharing(self):
        if self.share_token:
            self.share_token = None
            self.save(update_fields=["share_token", "updated_at"])

    def __str__(self):
        return self.title


class Section(TimeStampedModel):
    """A named, ordered group of questions inside a set (concept §3.1, v2).

    Flat, no nesting; questions may stay unsectioned. Sections are an
    overlay on the question list — the presentation shows an interstitial
    slide ("Zwischenfolie") when entering a new section.
    """

    question_set = models.ForeignKey(
        QuestionSet, on_delete=models.CASCADE, related_name="sections"
    )
    title = models.CharField(max_length=200)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering: ClassVar = ["position", "id"]

    def __str__(self):
        return self.title


class Question(TimeStampedModel):
    """A single item with an answer format (concept §4)."""

    class Kind(models.TextChoices):
        SINGLE_CHOICE = "single_choice", "Single choice"
        MULTIPLE_CHOICE = "multiple_choice", "Multiple choice"
        WORD_CLOUD = "word_cloud", "Word cloud"
        # v2 formats (concept §4): Likert behaves like single choice with an
        # ordered scale; open text collects free-form answers.
        LIKERT = "likert", "Likert scale"
        OPEN_TEXT = "open_text", "Open text"
        PRIORITIES = "priorities", "Priorities"
        ORDERING = "ordering", "Ordering"

    # Kinds whose answers are AnswerOption rows (vs. free text).
    CHOICE_KINDS = ("single_choice", "multiple_choice", "likert")
    TEXT_KINDS = ("word_cloud", "open_text")

    question_set = models.ForeignKey(
        QuestionSet, on_delete=models.CASCADE, related_name="questions"
    )
    # Optional grouping (v2). SET_NULL: deleting a section keeps its
    # questions, just unsectioned. The section always belongs to the same
    # set as the question (enforced in the API).
    section = models.ForeignKey(
        Section, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="questions",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    # Sanitized HTML from the WYSIWYG editor (ADR-0007); the API layer is the
    # only writer and always passes it through the nh3 allowlist.
    text = models.TextField(blank=True)
    # Show answer options in random order during presentation (choice kinds).
    shuffle_options = models.BooleanField(default=False)
    # v2: optional answering time in seconds (countdown; server-enforced).
    time_limit = models.PositiveIntegerField(null=True, blank=True)
    position = models.PositiveIntegerField(default=0)
    # v2 KI: for open_text, classify each answer live during the run. The
    # optional hint gives the model grading guidance beyond the question text
    # (e.g. the expected answer or a criterion).
    ai_evaluate = models.BooleanField(default=False)
    evaluation_hint = models.TextField(blank=True)
    # The scale the model sorts answers into: an ordered list of 2–5 category
    # labels. Default is the correctness scale (unchanged behaviour); presets
    # like „positiv/neutral/negativ" or free categories are possible. The model
    # picks exactly one per answer; unsure → the middle category.
    evaluation_categories = models.JSONField(default=default_verdicts)
    # Optionally show the category distribution as a bar chart on the beamer /
    # results page (in addition to the grouped answer lists).
    evaluation_chart = models.BooleanField(default=False)
    # v2 (#14): word clouds may let each participant submit several terms
    # (+ „Fertig"). Only meaningful for WORD_CLOUD; ignored otherwise.
    allow_multiple = models.BooleanField(default=False)
    # v2 (#30): show the growing word cloud on the beamer already while the
    # vote is open. Off keeps the screen clear until the vote closes (avoids
    # anchoring the audience). Only meaningful for WORD_CLOUD; default on to
    # keep the previous behaviour.
    wordcloud_live = models.BooleanField(default=True)
    # v2 KI (Live-Wortwolke): opt-in per Frage. Schaltet die KI-Sichten im
    # Präsentationsmodus frei (Aufräumen = Synonyme/ähnliche Begriffe/Tippfehler
    # zusammenfassen, zusätzlich zur eingebauten Groß-/Kleinschreibungs-Korrektur;
    # plus Gruppieren). Nur WORD_CLOUD, nur wirksam wenn KI systemweit aktiv ist.
    wordcloud_ai_enabled = models.BooleanField(default=False)
    # Optionale Gruppierungs-Kriterien für die KI-Sicht „Gruppiert". Leer → das
    # LLM bildet automatische thematische Cluster; ausgefüllt → es gruppiert nach
    # dieser Vorgabe. Nur wirksam bei aktivem wordcloud_ai_enabled.
    wordcloud_grouping = models.TextField(blank=True)
    # v2 (#76): cap how many terms one participant may contribute to a word
    # cloud. 0 = unlimited. Only meaningful for WORD_CLOUD + allow_multiple
    # (without allow_multiple each participant contributes exactly one term).
    wordcloud_max_answers = models.PositiveSmallIntegerField(default=0)

    class RevealAnswers(models.TextChoices):
        # Per-question override of when correct answers are highlighted (#28).
        # INHERIT keeps the set-wide default; only meaningful for kinds with
        # correct answers (single/multiple choice).
        INHERIT = "inherit", "Wie im Set"
        IMMEDIATELY = "immediately", "Immediately with the results"
        AFTER_CLOSE = "after_close", "After closing, on reveal"
        NEVER = "never", "Never"

    reveal_answers = models.CharField(
        max_length=20,
        choices=RevealAnswers.choices,
        default=RevealAnswers.INHERIT,
    )

    # Vorher-Nachher-Paar (#54): eine Nachher-Frage verweist auf ihre
    # Vorher-Frage. OneToOne erzwingt höchstens eine Nachher-Frage je
    # Vorher-Frage; CASCADE bedeutet: Löschen der Vorher-Frage löscht die
    # Nachher-Frage mit (die Nachher-Frage allein zu löschen entkoppelt nur).
    # Der Inhalt der Nachher-Frage wird beim Speichern der Vorher-Frage
    # gespiegelt (serializers.sync_after_question); die Ergebnisse bleiben
    # getrennt (eigene Frage → eigene Votes).
    before_question = models.OneToOneField(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="after_question",
    )

    class Meta:
        ordering: ClassVar = ["position", "id"]

    def __str__(self):
        return f"{self.get_kind_display()} #{self.pk}"

    @property
    def effective_reveal(self):
        """Resolve the reveal mode against the set default (#28)."""
        if self.reveal_answers == self.RevealAnswers.INHERIT:
            return self.question_set.reveal_answers
        return self.reveal_answers


class AnswerOption(TimeStampedModel):
    """One selectable answer of a choice question."""

    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name="options")
    text = models.CharField(max_length=500, blank=True)
    # v2: optional image (relative /media/ URL from the upload endpoint,
    # like images embedded in question HTML — same instance-local caveat).
    image = models.CharField(max_length=300, blank=True, default="")
    is_correct = models.BooleanField(default=False)
    # Likert only: an optional "Enthaltung" — flagged so ordinal analyses
    # can exclude it from the scale (v2 review feedback).
    is_abstention = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering: ClassVar = ["position", "id"]

    def __str__(self):
        return self.text[:50]


class UploadedImage(TimeStampedModel):
    """An image referenced from question HTML (uploaded via /api/images/).

    Tracked in the DB (rather than dumped anonymously into media/) so orphaned
    files can be garbage-collected later.
    """

    uploader = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="uploaded_images"
    )
    file = models.ImageField(upload_to="question-images/%Y/%m/")

    def __str__(self):
        return self.file.name
