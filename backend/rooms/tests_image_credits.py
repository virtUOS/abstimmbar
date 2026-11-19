import io

from django.contrib.auth import get_user_model
from django.test import TestCase
from PIL import Image

from rooms import image_credits as ic
from rooms.models import AnswerOption, Question, QuestionSet, Room, UploadedImage
from rooms.tests import ApiTestCase


class ImageCreditsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="u")
        self.room = Room.objects.create(title="R")
        self.qset = QuestionSet.objects.create(room=self.room, title="S")

    def _img(self, name, **credit):
        return UploadedImage.objects.create(uploader=self.user, file=name, **credit)

    @staticmethod
    def _src(name):
        return f"/media/{name}"

    def _question(self, text_de="", text_en="", option_images=()):
        q = Question.objects.create(
            question_set=self.qset, kind="single_choice", text_de=text_de, text_en=text_en
        )
        for i, src in enumerate(option_images):
            AnswerOption.objects.create(question=q, text=f"o{i}", image=src, position=i)
        return q

    def test_license_url_cc_with_and_without_version(self):
        self.assertEqual(
            ic.license_url("cc-by-nd", "4.0"),
            "https://creativecommons.org/licenses/by-nd/4.0/",
        )
        self.assertEqual(
            ic.license_url("cc-by", ""), "https://creativecommons.org/licenses/by/"
        )

    def test_license_url_cc0_pd_other(self):
        self.assertEqual(
            ic.license_url("cc0", ""), "https://creativecommons.org/publicdomain/zero/1.0/"
        )
        self.assertEqual(
            ic.license_url("pd", ""), "https://creativecommons.org/publicdomain/mark/1.0/"
        )
        self.assertEqual(ic.license_url("other", ""), "")
        self.assertEqual(ic.license_url("arr", ""), "")
        self.assertEqual(ic.license_url("", ""), "")

    def test_license_label(self):
        self.assertEqual(ic.license_label("cc-by-nd", "4.0"), "CC BY-ND 4.0")
        self.assertEqual(ic.license_label("cc-by", ""), "CC BY")
        self.assertEqual(ic.license_label("cc0", "3.0"), "CC0 1.0")
        self.assertEqual(ic.license_label("pd", ""), "")
        self.assertEqual(ic.license_label("other", ""), "")
        self.assertEqual(ic.license_label("arr", ""), "")
        self.assertEqual(ic.license_label("", ""), "")

    def test_has_credit_author_or_license_only(self):
        self.assertFalse(ic.has_credit(self._img("a.png")))
        self.assertFalse(ic.has_credit(self._img("a2.png", credit_title="T")))
        self.assertTrue(ic.has_credit(self._img("b.png", credit_author="X")))
        self.assertTrue(ic.has_credit(self._img("c.png", credit_license="cc0")))

    def test_credits_dedupe_text_and_option(self):
        self._img("a.png", credit_author="X")
        src = self._src("a.png")
        q = self._question(text_de=f'<p><img src="{src}" alt=""></p>', option_images=[src])
        images = ic.images_by_src(ic.question_image_srcs(q))
        out = ic.credits_for_question(q, images)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["src"], src)
        self.assertEqual(out[0]["author"], "X")
        self.assertTrue(out[0]["has_credit"])
        self.assertEqual(
            set(out[0]),
            {"id", "src", "author", "title", "source", "license", "license_label",
             "license_url", "version", "text", "has_credit"},
        )

    def test_credits_skip_images_without_credit(self):
        self._img("a.png")
        src = self._src("a.png")
        q = self._question(text_en=f'<img src="{src}">')
        images = ic.images_by_src(ic.question_image_srcs(q))
        self.assertEqual(ic.credits_for_question(q, images), [])
        out = ic.credits_for_question(q, images, include_empty=True)
        self.assertEqual(len(out), 1)
        self.assertFalse(out[0]["has_credit"])

    def test_credits_for_questions_single_query(self):
        self._img("a.png", credit_author="A")
        self._img("b.png", credit_author="B")
        self._img("c.png")
        qs = [
            self._question(text_de=f'<img src="{self._src("a.png")}">'),
            self._question(option_images=[self._src("b.png")]),
            self._question(text_de=f'<img src="{self._src("c.png")}">'),
        ]
        qs = list(Question.objects.filter(id__in=[q.id for q in qs]).prefetch_related("options"))
        with self.assertNumQueries(1):
            result = ic.credits_for_questions(qs)
        self.assertEqual(sorted(len(v) for v in result.values()), [1, 1])
        self.assertNotIn(qs[2].id, result)

    def test_foreign_src_ignored(self):
        self._img("y.png", credit_author="A")
        q = self._question(
            text_de='<img src="https://x/y.png"><img src="/media/other/../x">'
        )
        images = ic.images_by_src(ic.question_image_srcs(q))
        self.assertEqual(images, {})
        self.assertEqual(ic.credits_for_question(q, images, include_empty=True), [])

    def test_clean_validates_version_and_source(self):
        from django.core.exceptions import ValidationError

        img = self._img("v.png", credit_license_version="4.0", credit_source="https://a.b/c")
        img.clean()
        img.credit_license_version = "x"
        with self.assertRaises(ValidationError):
            img.clean()
        img.credit_license_version = ""
        img.credit_source = "javascript:alert(1)"
        with self.assertRaises(ValidationError):
            img.clean()


class _CreditApiBase(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.qset = QuestionSet.objects.create(room=self.room, title="S")

    @staticmethod
    def _png():
        buffer = io.BytesIO()
        Image.new("RGB", (4, 4), "green").save(buffer, format="PNG")
        buffer.seek(0)
        buffer.name = "test.png"
        return buffer

    def _upload(self, user=None):
        """Upload via the API as ``user``; returns (UploadedImage, src)."""
        if user is not None:
            self.client.force_login(user)
        response = self.client.post("/api/images/", {"file": self._png()})
        self.assertEqual(response.status_code, 201)
        self.client.force_login(self.owner)
        src = response.json()["url"]
        return UploadedImage.objects.get(pk=response.json()["id"]), src

    def _question(self, src):
        return Question.objects.create(
            question_set=self.qset,
            kind="single_choice",
            text_de=f'<p><img src="{src}" alt=""></p>',
        )


class ImageCreditApiTests(_CreditApiBase):
    def test_question_payload_lists_images_with_editable(self):
        img, src = self._upload()
        q = self._question(src)
        payload = self.client.get(f"/api/questions/{q.id}/").json()
        self.assertEqual(len(payload["image_credits"]), 1)
        entry = payload["image_credits"][0]
        self.assertEqual(entry["id"], img.id)
        self.assertEqual(entry["src"], src)
        self.assertFalse(entry["has_credit"])
        self.assertTrue(entry["editable"])

    def test_patch_credit_by_uploader(self):
        img, src = self._upload()
        response = self.client.patch(
            f"/api/images/{img.id}/credit/",
            {"author": "Ada", "license": "cc-by", "version": "4.0",
             "title": "Pic", "source": "https://example.org/x", "text": ""},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["author"], "Ada")
        self.assertEqual(body["license_label"], "CC BY 4.0")
        self.assertEqual(body["src"], src)
        self.assertTrue(body["has_credit"])
        self.assertTrue(body["editable"])
        img.refresh_from_db()
        self.assertEqual(img.credit_author, "Ada")
        self.assertEqual(img.credit_license_version, "4.0")

    def test_patch_credit_by_room_owner_not_uploader(self):
        img, src = self._upload(user=self.other)
        self._question(src)
        response = self.client.patch(
            f"/api/images/{img.id}/credit/", {"author": "Bob"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        img.refresh_from_db()
        self.assertEqual(img.credit_author, "Bob")

    def test_patch_credit_forbidden_for_stranger(self):
        img, src = self._upload()
        self._question(src)
        self.client.force_login(self.other)
        response = self.client.patch(
            f"/api/images/{img.id}/credit/", {"author": "Eve"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 404)
        img.refresh_from_db()
        self.assertEqual(img.credit_author, "")

    def test_patch_unknown_image_is_404(self):
        response = self.client.patch(
            "/api/images/999999/credit/", {"author": "x"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 404)

    def _bad(self, body):
        img, _ = self._upload()
        response = self.client.patch(
            f"/api/images/{img.id}/credit/", body, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        img.refresh_from_db()
        self.assertEqual(img.credit_author, "")

    def test_patch_rejects_javascript_source(self):
        self._bad({"author": "x", "source": "javascript:alert(1)"})

    def test_patch_rejects_bad_version(self):
        self._bad({"author": "x", "version": "v4"})

    def test_patch_trims_version_whitespace(self):
        # DRF trims; the stored value never carries a trailing newline.
        img, _ = self._upload()
        response = self.client.patch(
            f"/api/images/{img.id}/credit/", {"version": "4.0\n"}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 200)
        img.refresh_from_db()
        self.assertEqual(img.credit_license_version, "4.0")

    def test_patch_accepts_all_rights_reserved(self):
        img, _ = self._upload()
        response = self.client.patch(
            f"/api/images/{img.id}/credit/", {"license": "arr", "text": "Nur Lehre"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual((body["license_label"], body["license_url"]), ("", ""))
        self.assertTrue(body["has_credit"])

    def test_patch_rejects_unknown_license(self):
        self._bad({"author": "x", "license": "gpl"})

    def test_credit_change_visible_in_duplicated_set(self):
        img, src = self._upload()
        q1 = self._question(src)
        response = self.client.post(f"/api/question-sets/{self.qset.id}/duplicate/", {})
        self.assertEqual(response.status_code, 201)
        q2 = Question.objects.get(question_set_id=response.json()["id"])
        self.client.patch(
            f"/api/images/{img.id}/credit/", {"author": "Zed"}, content_type="application/json"
        )
        for q in (q1, q2):
            entries = self.client.get(f"/api/questions/{q.id}/").json()["image_credits"]
            self.assertEqual([e["author"] for e in entries], ["Zed"])


class ImageCreditEditRightTests(_CreditApiBase):
    """I1: uploader, staff, or owner of EVERY room referencing the image."""

    def _foreign_room(self, owner):
        room = Room.objects.create(title_de="Fremd")
        room.owners.add(owner)
        return QuestionSet.objects.create(room=room, title="F")

    def _embed(self, qset, src, field="text_de"):
        return Question.objects.create(
            question_set=qset, kind="single_choice", **{field: f'<p><img src="{src}" alt=""></p>'}
        )

    def _patch(self, img, user, author="X"):
        self.client.force_login(user)
        return self.client.patch(
            f"/api/images/{img.id}/credit/", {"author": author}, content_type="application/json"
        )

    def _editable(self, q, user):
        self.client.force_login(user)
        return self.client.get(f"/api/questions/{q.id}/").json()["image_credits"][0]["editable"]

    def test_stranger_embedding_foreign_src_is_read_only(self):
        img, src = self._upload()  # uploaded by owner, used in owner's room
        self._question(src)
        stranger_q = self._embed(self._foreign_room(self.other), src)
        self.assertFalse(self._editable(stranger_q, self.other))
        self.assertEqual(self._patch(img, self.other, "Eve").status_code, 404)
        img.refresh_from_db()
        self.assertEqual(img.credit_author, "")

    def test_co_owner_of_only_room_may_edit(self):
        img, src = self._upload(user=self.other)
        q = self._question(src)
        self.assertTrue(self._editable(q, self.owner))
        self.assertEqual(self._patch(img, self.owner).status_code, 200)

    def test_duplicated_into_second_own_room_still_editable(self):
        img, src = self._upload(user=self.other)
        q = self._question(src)
        self._embed(self._foreign_room(self.owner), src)
        self.assertTrue(self._editable(q, self.owner))
        self.assertEqual(self._patch(img, self.owner).status_code, 200)

    def test_also_used_in_foreign_room_only_uploader_may_edit(self):
        third = get_user_model().objects.create_user(username="third")
        img, src = self._upload(user=self.other)  # uploader: other
        q = self._question(src)  # owner's room
        self._embed(self._foreign_room(third), src)  # e.g. shared-set copy
        self.assertFalse(self._editable(q, self.owner))
        self.assertEqual(self._patch(img, self.owner).status_code, 404)
        self.assertEqual(self._patch(img, self.other, "Up").status_code, 200)
        img.refresh_from_db()
        self.assertEqual(img.credit_author, "Up")

    def test_staff_may_edit(self):
        staff = get_user_model().objects.create_user(username="staff", is_staff=True)
        img, src = self._upload()
        self._question(src)
        self._embed(self._foreign_room(self.other), src)
        self.assertEqual(self._patch(img, staff).status_code, 200)

    def test_text_en_only_reference(self):
        img, src = self._upload(user=self.other)
        self._embed(self.qset, src, field="text_en")
        self.assertEqual(self._patch(img, self.owner).status_code, 200)

    def test_option_image_reference(self):
        img, src = self._upload(user=self.other)
        q = Question.objects.create(question_set=self.qset, kind="single_choice", text_de="Q")
        AnswerOption.objects.create(question=q, text="a", image=src, position=0)
        self.assertEqual(self._patch(img, self.owner).status_code, 200)

    def test_unreferenced_foreign_image_not_editable(self):
        img, _ = self._upload(user=self.other)
        self.assertEqual(self._patch(img, self.owner).status_code, 404)

    def test_unauthenticated_patch_rejected(self):
        img, _ = self._upload()
        self.client.logout()
        response = self.client.patch(
            f"/api/images/{img.id}/credit/", {"author": "X"}, content_type="application/json"
        )
        self.assertIn(response.status_code, (401, 403))
        img.refresh_from_db()
        self.assertEqual(img.credit_author, "")

    def test_umlaut_filename_co_owner(self):
        img = UploadedImage.objects.create(uploader=self.other, file="question-images/Bär Öl.png")
        src = img.file.url
        self.assertNotIn("ä", src)  # percent-encoded, as stored in question HTML
        q = self._question(src)
        self.assertTrue(self._editable(q, self.owner))
        self.assertEqual(self._patch(img, self.owner).status_code, 200)
