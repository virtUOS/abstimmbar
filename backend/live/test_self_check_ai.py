# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from unittest.mock import patch

from django.test import TestCase

from accounts.models import User
from common.models import SiteConfig
from live import self_check_ai
from rooms.models import Question, QuestionSet, Room


class SelfCheckAiTests(TestCase):
    def setUp(self):
        self_check_ai._reset_for_tests()
        self.user = User.objects.create_user(username="o", password="p")
        self.room = Room.objects.create(title="R")
        self.room.owners.add(self.user)
        self.qs = QuestionSet.objects.create(
            room=self.room, title="S", type=QuestionSet.SetType.SELF_CHECK
        )
        self.q = Question.objects.create(
            question_set=self.qs, kind=Question.Kind.OPEN_TEXT,
            text_de="Frage", text_en="Q",
            ai_evaluate=True, model_solution="Paris",
            evaluation_categories=["korrekt", "unklar", "falsch"],
        )

    @patch("live.self_check_ai.classify", return_value=("korrekt", "gut"))
    def test_grade_calls_classify_and_caches(self, mock_classify):
        v1 = self_check_ai.grade(self.q, "Antwort")
        v2 = self_check_ai.grade(self.q, "  antwort ")  # same after strip+casefold
        self.assertEqual(v1, ("korrekt", "gut"))
        self.assertEqual(v2, ("korrekt", "gut"))
        self.assertEqual(mock_classify.call_count, 1)  # second hit served from cache

    @patch("live.self_check_ai.classify", return_value=("korrekt", ""))
    def test_grade_passes_model_solution_and_categories(self, mock_classify):
        self_check_ai.grade(self.q, "x")
        args, kwargs = mock_classify.call_args
        # classify(question_text, hint, answer, categories, model_solution=...)
        self.assertEqual(args[2], "x")
        self.assertEqual(args[3], ["korrekt", "unklar", "falsch"])
        self.assertEqual(kwargs["model_solution"], "Paris")

    @patch("live.self_check_ai.classify", return_value=("korrekt", ""))
    def test_grade_language_in_cache_key_and_prompt(self, mock_classify):
        # #300: same answer, different participant language -> graded anew,
        # with the language handed to the classifier.
        self_check_ai.grade(self.q, "x", language="en")
        self_check_ai.grade(self.q, "x", language="en")
        self_check_ai.grade(self.q, "x", language="de")
        self.assertEqual(mock_classify.call_count, 2)
        self.assertEqual(
            [c.kwargs["note_language"] for c in mock_classify.call_args_list], ["en", "de"]
        )

    def test_grade_defaults_to_active_language(self):
        from django.utils import translation
        with patch("live.self_check_ai.classify", return_value=("korrekt", "")) as mock_classify, \
                translation.override("en"):
            self_check_ai.grade(self.q, "y")
        self.assertEqual(mock_classify.call_args.kwargs["note_language"], "en")

    def test_classify_appends_note_language(self):
        from live.ai_evaluation import classify
        with patch(
            "basicbar_integrations.ai.chat_json", return_value={"verdict": "korrekt"}
        ) as chat:
            classify("Q", "", "a", ["korrekt", "falsch"], note_language="en")
            self.assertIn("auf Englisch", chat.call_args.args[0])
            classify("Q", "", "a", ["korrekt", "falsch"])
            self.assertNotIn("Schreibe die Begründung", chat.call_args.args[0])

    def test_allow_unlimited_when_zero(self):
        SiteConfig.objects.update_or_create(pk=1, defaults={"self_check_ai_per_minute": 0})
        for _ in range(100):
            self.assertTrue(self_check_ai.allow(self.qs.pk))

    def test_allow_enforces_positive_limit(self):
        SiteConfig.objects.update_or_create(pk=1, defaults={"self_check_ai_per_minute": 3})
        self.assertTrue(self_check_ai.allow(self.qs.pk))
        self.assertTrue(self_check_ai.allow(self.qs.pk))
        self.assertTrue(self_check_ai.allow(self.qs.pk))
        self.assertFalse(self_check_ai.allow(self.qs.pk))  # 4th within the minute

    def test_allow_is_per_set(self):
        SiteConfig.objects.update_or_create(pk=1, defaults={"self_check_ai_per_minute": 1})
        self.assertTrue(self_check_ai.allow(1))
        self.assertFalse(self_check_ai.allow(1))
        self.assertTrue(self_check_ai.allow(2))  # different set has its own window
