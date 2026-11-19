"""Bilingual alt text for option images (#342): API, duplicate, transfer."""
import copy

from rooms.models import AnswerOption, Question, QuestionSet, Room
from rooms.tests import ApiTestCase

IMG = "/media/question-images/2026/11/a.png"


class OptionImageAltTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.qset = QuestionSet.objects.create(
            room=self.room, title_de="Termin", title_en="Session"
        )

    def _post_question(self, options):
        return self.client.post(
            "/api/questions/",
            {
                "question_set": self.qset.pk,
                "kind": "single_choice",
                "text": "<p>Q</p>",
                "options": options,
            },
            content_type="application/json",
        )

    def _make_question(self):
        question = Question.objects.create(
            question_set=self.qset, kind="single_choice", text_de="<p>Q</p>"
        )
        AnswerOption.objects.create(
            question=question, image=IMG, is_correct=True,
            image_alt_de="Ein Hund", image_alt_en="A dog",
        )
        AnswerOption.objects.create(question=question, text_de="Katze", position=1)
        return question

    def test_option_image_alt_roundtrip_rest(self):
        created = self._post_question([
            {"text": "", "image": IMG, "image_alt": {"de": "Ein Hund", "en": "A dog"}},
            {"text": "B"},
        ])
        self.assertEqual(created.status_code, 201, created.content)
        question_id = created.json()["id"]
        got = self.client.get(f"/api/questions/{question_id}/").json()
        self.assertEqual(got["options"][0]["image_alt"], {"de": "Ein Hund", "en": "A dog"})
        self.assertEqual(got["options"][1]["image_alt"], {"de": "", "en": ""})

        options = got["options"]
        options[0]["image_alt"] = {"de": "Ein Pudel", "en": "A poodle"}
        patched = self.client.patch(
            f"/api/questions/{question_id}/", {"options": options},
            content_type="application/json",
        )
        self.assertEqual(patched.status_code, 200, patched.content)
        again = self.client.get(f"/api/questions/{question_id}/").json()
        self.assertEqual(again["options"][0]["image_alt"], {"de": "Ein Pudel", "en": "A poodle"})
        option = AnswerOption.objects.get(pk=options[0]["id"])
        self.assertEqual(option.image_alt_de, "Ein Pudel")
        self.assertEqual(option.image_alt_en, "A poodle")

    def test_image_alt_max_length_300(self):
        ok = self._post_question([
            {"text": "A", "image_alt": {"de": "x" * 300, "en": ""}}, {"text": "B"},
        ])
        self.assertEqual(ok.status_code, 201, ok.content)
        too_long = self._post_question([
            {"text": "A", "image_alt": {"de": "x" * 301, "en": ""}}, {"text": "B"},
        ])
        self.assertEqual(too_long.status_code, 400)

    def test_image_alt_is_stripped(self):
        created = self._post_question([
            {"text": "A", "image_alt": {"de": "  Hund  ", "en": ""}}, {"text": "B"},
        ])
        self.assertEqual(created.status_code, 201, created.content)
        option = AnswerOption.objects.get(question_id=created.json()["id"], position=0)
        self.assertEqual(option.image_alt_de, "Hund")

    def test_duplicate_set_keeps_image_alt(self):
        self._make_question()
        response = self.client.post(f"/api/question-sets/{self.qset.pk}/duplicate/", {})
        self.assertEqual(response.status_code, 201, response.content)
        copy_option = AnswerOption.objects.get(
            question__question_set_id=response.json()["id"], image=IMG
        )
        self.assertEqual(copy_option.image_alt_de, "Ein Hund")
        self.assertEqual(copy_option.image_alt_en, "A dog")

    def _export(self):
        response = self.client.get(f"/api/question-sets/{self.qset.pk}/export/")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def _import(self, data):
        target = Room.objects.create(title="Ziel")
        target.owners.add(self.owner)
        response = self.client.post(
            f"/api/rooms/{target.pk}/import-set/", data, content_type="application/json"
        )
        self.assertEqual(response.status_code, 201, response.content)
        return QuestionSet.objects.get(pk=response.json()["id"])

    def test_json_export_import_keeps_image_alt(self):
        self._make_question()
        data = self._export()
        exported = data["questions"][0]["options"][0]
        self.assertEqual(exported["image_alt"], {"de": "Ein Hund", "en": "A dog"})
        imported = self._import(data)
        option = AnswerOption.objects.get(question__question_set=imported, image=IMG)
        self.assertEqual(option.image_alt_de, "Ein Hund")
        self.assertEqual(option.image_alt_en, "A dog")

    def test_import_old_file_without_image_alt_ok(self):
        self._make_question()
        data = copy.deepcopy(self._export())
        for question in data["questions"]:
            for option in question["options"]:
                option.pop("image_alt", None)
        imported = self._import(data)
        option = AnswerOption.objects.get(question__question_set=imported, image=IMG)
        self.assertEqual(option.image_alt_de or "", "")
        self.assertEqual(option.image_alt_en or "", "")
