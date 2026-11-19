import io
from unittest import mock

from basicbar_integrations.ai import AIError
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from PIL import Image

from rooms import image_alt
from rooms.models import UploadedImage
from rooms.tests import AI_ON, ApiTestCase

VISION_ON = {**AI_ON, "AI_VISION": True, "AI_VISION_MODEL": "vm"}
CHAT = "basicbar_integrations.ai.chat_json"


def _png(size=(40, 30), mode="RGB"):
    buf = io.BytesIO()
    Image.new(mode, size, "red").save(buf, "PNG")
    return buf.getvalue()


class SuggestAltTests(ApiTestCase):
    def _img(self, data=None):
        img = UploadedImage(uploader=self.owner)
        img.file.save("a.png", ContentFile(data or _png()), save=True)
        return img

    @override_settings(**VISION_ON)
    def test_suggest_alt_strips_prefix_and_caps_length(self):
        img = self._img()
        with mock.patch(CHAT, return_value={"alt": "  Bild von " + "wort " * 60}) as m:
            alt = image_alt.suggest_alt(img, "de")
        self.assertFalse(alt.lower().startswith("bild"))
        self.assertLessEqual(len(alt), 150)
        self.assertTrue(alt.endswith("wort"))
        self.assertEqual(m.call_args.kwargs["model"], "vm")
        self.assertEqual(m.call_args.kwargs["images"][0][1], "image/jpeg")
        with mock.patch(CHAT, return_value={"alt": "An image of a cat"}):
            self.assertEqual(image_alt.suggest_alt(img, "en"), "A cat")

    @override_settings(**VISION_ON)
    def test_suggest_alt_empty_raises(self):
        with mock.patch(CHAT, return_value={"alt": "  "}), self.assertRaises(AIError):
            image_alt.suggest_alt(self._img(), "en")

    @override_settings(**VISION_ON)
    def test_image_downscaled_before_send(self):
        img = self._img(_png((3000, 1500)))
        with mock.patch(CHAT, return_value={"alt": "x"}) as m:
            image_alt.suggest_alt(img, "en")
        data, mime = m.call_args.kwargs["images"][0]
        sent = Image.open(io.BytesIO(data))
        self.assertLessEqual(max(sent.size), 1024)
        self.assertEqual(mime, "image/jpeg")

    @override_settings(**VISION_ON)
    def test_alpha_image_sent_as_png(self):
        img = self._img(_png((20, 20), "RGBA"))
        with mock.patch(CHAT, return_value={"alt": "x"}) as m:
            image_alt.suggest_alt(img, "en")
        self.assertEqual(m.call_args.kwargs["images"][0][1], "image/png")


class AltEndpointTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.img = UploadedImage(uploader=self.owner)
        self.img.file.save("a.png", ContentFile(_png()), save=True)
        self.url = f"/api/images/{self.img.pk}/alt-suggestion/"

    @override_settings(**VISION_ON)
    def test_endpoint_returns_alt(self):
        with mock.patch(CHAT, return_value={"alt": "Eine rote Fläche"}):
            r = self.client.post(self.url, {"lang": "de"}, content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"alt": "Eine rote Fläche"})

    @override_settings(**AI_ON, AI_VISION=False)
    def test_endpoint_disabled_503(self):
        r = self.client.post(self.url, {"lang": "de"}, content_type="application/json")
        self.assertEqual(r.status_code, 503)
        self.assertIn("detail", r.json())

    @override_settings(**VISION_ON)
    def test_endpoint_ai_error_502(self):
        with mock.patch(CHAT, side_effect=AIError("boom")):
            r = self.client.post(self.url, {"lang": "en"}, content_type="application/json")
        self.assertEqual(r.status_code, 502)
        self.assertIn("detail", r.json())

    @override_settings(**VISION_ON)
    def test_endpoint_forbidden_for_stranger_404(self):
        self.client.force_login(self.other)
        with mock.patch(CHAT, return_value={"alt": "x"}) as m:
            r = self.client.post(self.url, {"lang": "en"}, content_type="application/json")
        self.assertEqual(r.status_code, 404)
        m.assert_not_called()

    @override_settings(**VISION_ON)
    def test_endpoint_missing_image_404(self):
        r = self.client.post(
            "/api/images/99999/alt-suggestion/", {"lang": "en"}, content_type="application/json"
        )
        self.assertEqual(r.status_code, 404)

    @override_settings(**VISION_ON)
    def test_endpoint_bad_lang_400(self):
        with mock.patch(CHAT, return_value={"alt": "x"}) as m:
            r = self.client.post(self.url, {"lang": "fr"}, content_type="application/json")
        self.assertEqual(r.status_code, 400)
        m.assert_not_called()

    def test_endpoint_requires_login(self):
        self.client.logout()
        r = self.client.post(self.url, {"lang": "de"}, content_type="application/json")
        self.assertIn(r.status_code, (401, 403))


class WhoamiVisionTests(TestCase):
    def test_whoami_ai_vision_flag(self):
        with override_settings(**VISION_ON):
            self.assertTrue(self.client.get("/api/whoami/").json()["ai_vision_enabled"])
        with override_settings(**AI_ON, AI_VISION=False):
            self.assertFalse(self.client.get("/api/whoami/").json()["ai_vision_enabled"])
        with override_settings(AI_PROVIDER="none", AI_VISION=True):
            self.assertFalse(self.client.get("/api/whoami/").json()["ai_vision_enabled"])
