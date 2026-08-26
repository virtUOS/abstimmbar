# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from unittest.mock import patch

from django.test import SimpleTestCase

from live.ai_evaluation import classify


class ClassifyModelSolutionTest(SimpleTestCase):
    @patch("live.ai_evaluation.ai.chat_json", return_value={"verdict": "korrekt", "note": "ok"})
    def test_model_solution_is_in_prompt(self, chat):
        verdict, note = classify(
            "Q",
            "hint",
            "answer",
            ["korrekt", "falsch"],
            model_solution="Paris ist die Hauptstadt",
        )
        user_prompt = chat.call_args.args[1]
        self.assertIn("Musterlösung: Paris ist die Hauptstadt", user_prompt)
        self.assertEqual(verdict, "korrekt")
