# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Per-user AI rate limits (#343)."""
from unittest import mock

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import override_settings

from rooms.models import QuestionSet, UploadedImage
from rooms.tests import AI_ON, ApiTestCase
from rooms.tests_image_alt import CHAT, VISION_ON, _png

DISTRACTORS = "basicbar_integrations.ai.chat_json"


def _rates(**rates):
    return override_settings(
        REST_FRAMEWORK={
            "DEFAULT_AUTHENTICATION_CLASSES": [
                "rest_framework.authentication.SessionAuthentication"
            ],
            "DEFAULT_THROTTLE_RATES": rates,
        }
    )


class AIThrottleTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.qs = QuestionSet.objects.create(room=self.room, title="T")
        self.url = f"/api/question-sets/{self.qs.pk}/ai-rephrase/"
        self.img = UploadedImage(uploader=self.owner)
        self.img.file.save("a.png", ContentFile(_png()), save=True)
        self.alt_url = f"/api/images/{self.img.pk}/alt-suggestion/"

    def _rephrase(self, **extra):
        return self.client.post(
            self.url, {"text": "Frage?"}, content_type="application/json", **extra
        )

    def _alt(self):
        return self.client.post(self.alt_url, {"lang": "en"}, content_type="application/json")

    @override_settings(**AI_ON)
    def test_ai_scope_limits_after_n(self):
        with _rates(ai="2/hour", ai_vision="2/hour"), mock.patch(
            DISTRACTORS, return_value={"suggestions": ["Eine Frage?"]}
        ) as m:
            self.assertEqual(self._rephrase().status_code, 200)
            self.assertEqual(self._rephrase().status_code, 200)
            r = self._rephrase(HTTP_ACCEPT_LANGUAGE="de")
        self.assertEqual(r.status_code, 429)
        self.assertEqual(m.call_count, 2)
        self.assertIn("Sie haben die KI gerade sehr oft genutzt", r.json()["detail"])
        self.assertIn("Minuten erneut", r.json()["detail"])
        self.assertIn("Retry-After", r)

    @override_settings(**VISION_ON)
    def test_vision_scope_separate(self):
        with _rates(ai="1/hour", ai_vision="1/hour"), mock.patch(
            CHAT, return_value={"alt": "x", "suggestions": ["Q?"]}
        ):
            self.assertEqual(self._rephrase().status_code, 200)
            self.assertEqual(self._rephrase().status_code, 429)
            # the text scope being exhausted does not affect the vision scope
            self.assertEqual(self._alt().status_code, 200)
            self.assertEqual(self._alt().status_code, 429)

    @override_settings(**AI_ON)
    def test_staff_exempt(self):
        self.owner.is_staff = True
        self.owner.save()
        with _rates(ai="1/hour"), mock.patch(DISTRACTORS, return_value={"suggestions": ["Q?"]}) as m:
            for _ in range(3):
                self.assertEqual(self._rephrase().status_code, 200)
        self.assertEqual(m.call_count, 3)

    @override_settings(**VISION_ON)
    def test_rate_off_disables(self):
        with _rates(ai="off", ai_vision="OFF"), mock.patch(
            CHAT, return_value={"alt": "x", "suggestions": ["Q?"]}
        ):
            for _ in range(3):
                self.assertEqual(self._rephrase().status_code, 200)
                self.assertEqual(self._alt().status_code, 200)

    @override_settings(**AI_ON)
    def test_generation_status_not_throttled(self):
        with _rates(ai="1/hour"), mock.patch("rooms.views.generation.start_job"):
            r = self.client.post(
                f"/api/question-sets/{self.qs.pk}/ai-generate/", {"text": "Material text."}
            )
            self.assertEqual(r.status_code, 201)
            job_id = r.json()["job_id"]
            self.assertEqual(
                self.client.post(
                    f"/api/question-sets/{self.qs.pk}/ai-generate/", {"text": "Mehr."}
                ).status_code,
                429,
            )
            for _ in range(3):
                self.assertEqual(
                    self.client.get(
                        f"/api/question-sets/{self.qs.pk}/ai-generate/active/"
                    ).status_code,
                    200,
                )
                self.assertEqual(
                    self.client.get(
                        f"/api/question-sets/{self.qs.pk}/ai-generate/jobs/{job_id}/"
                    ).status_code,
                    200,
                )

    @override_settings(**AI_ON)
    def test_singular_minute_message(self):
        with _rates(ai="1/minute"), mock.patch(DISTRACTORS, return_value={"suggestions": ["Q?"]}):
            self._rephrase()
            de = self._rephrase(HTTP_ACCEPT_LANGUAGE="de")
            en = self._rephrase(HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(de.status_code, 429)
        self.assertTrue(de.json()["detail"].endswith("in 1 Minute erneut."), de.json())
        self.assertTrue(en.json()["detail"].endswith("in 1 minute."), en.json())

    @override_settings(**AI_ON)
    def test_rejection_is_logged(self):
        with _rates(ai="1/hour"), mock.patch(DISTRACTORS, return_value={"suggestions": ["Q?"]}):
            self._rephrase()
            with self.assertLogs("abstimmbar.ai", "INFO") as logs:
                self._rephrase()
        self.assertIn(f"AI throttled scope=ai user={self.owner.pk}", logs.output[0])

    @override_settings(**VISION_ON)
    def test_every_ai_endpoint_is_throttled_before_the_model(self):
        qs, q = self.qs.pk, 1
        text_endpoints = [
            f"/api/question-sets/{qs}/ai-generate/",
            f"/api/question-sets/{qs}/ai-generate/jobs/{q}/retry/",
            f"/api/question-sets/{qs}/ai-distractors/",
            f"/api/question-sets/{qs}/ai-rephrase/",
            f"/api/question-sets/{qs}/ai-proofread/",
            f"/api/questions/{q}/ai-distractors/",
            f"/api/questions/{q}/ai-rephrase/",
            f"/api/runs/{q}/matrix/{q}/ai-propose",
            f"/api/runs/{q}/mindmap/{q}/ai-optimize",
            f"/api/runs/{q}/questions/{q}/ai-wordcloud/",
            f"/api/runs/{q}/questions/{q}/ai-freetext/",
            f"/api/runs/{q}/questions/{q}/ai-summary/",
            f"/api/runs/{q}/ai-summary/",
            f"/api/runs/{q}/wordcloud-ai/",
        ]
        with _rates(ai="0/hour", ai_vision="0/hour"), mock.patch(DISTRACTORS) as m:
            for url in text_endpoints:
                r = self.client.post(url, {}, content_type="application/json")
                self.assertEqual(r.status_code, 429, url)
            r = self._alt()
            self.assertEqual(r.status_code, 429)
        m.assert_not_called()
