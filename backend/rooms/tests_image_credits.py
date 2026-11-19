from django.contrib.auth import get_user_model
from django.test import TestCase

from rooms import image_credits as ic
from rooms.models import AnswerOption, Question, QuestionSet, Room, UploadedImage


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
        self.assertEqual(ic.license_url("", ""), "")

    def test_license_label(self):
        self.assertEqual(ic.license_label("cc-by-nd", "4.0"), "CC BY-ND 4.0")
        self.assertEqual(ic.license_label("cc-by", ""), "CC BY")
        self.assertEqual(ic.license_label("cc0", "3.0"), "CC0 1.0")
        self.assertEqual(ic.license_label("pd", ""), "")
        self.assertEqual(ic.license_label("other", ""), "")
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
