# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone, translation

from common.i18n_fields import resolve_translated_text
from rooms.models import AnswerOption, Question, QuestionSet, Room

from . import ai_evaluation, ai_wordcloud, ai_wordcloud_live
from .models import ParticipantToken, Run, Vote
from .results import freetext_evaluation
from .state import active_run, build_payloads

User = get_user_model()

# The dev container may carry a real .env; force AI on/off explicitly.
AI_ON = {
    "AI_PROVIDER": "litellm",
    "AI_BASE_URL": "https://llm.test/v1",
    "AI_API_KEY": "secret",
    "AI_MODEL": "test-model",
}
AI_OFF = {"AI_PROVIDER": "none", "AI_BASE_URL": "", "AI_API_KEY": "", "AI_MODEL": ""}


class LiveTestCase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="frank")
        self.room = Room.objects.create(title="Bio 101")
        self.room.owners.add(self.owner)
        self.question_set = QuestionSet.objects.create(room=self.room, title="Termin 1")
        self.question = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.SINGLE_CHOICE,
            text="<p>2+2?</p>",
        )
        self.correct = AnswerOption.objects.create(
            question=self.question, text="4", is_correct=True, position=0
        )
        self.wrong = AnswerOption.objects.create(
            question=self.question, text="5", position=1
        )

    def join(self):
        response = self.client.post(
            f"/api/live/rooms/{self.room.code}/join/", {}, content_type="application/json"
        )
        return response.json()["token"]

    def open_question(self, question=None):
        run = Run.objects.create(
            question_set=self.question_set,
            phase=Run.Phase.OPEN,
            active_question=question or self.question,
        )
        return run

    def vote(self, token, **payload):
        return self.client.post(
            f"/api/live/rooms/{self.room.code}/vote/",
            {"token": token, **payload},
            content_type="application/json",
        )


class JoinTests(LiveTestCase):
    def test_join_issues_and_reuses_token(self):
        token = self.join()
        self.assertEqual(ParticipantToken.objects.count(), 1)
        response = self.client.post(
            f"/api/live/rooms/{self.room.code}/join/",
            {"token": token},
            content_type="application/json",
        )
        self.assertEqual(response.json()["token"], token)
        self.assertEqual(ParticipantToken.objects.count(), 1)

    def test_unknown_room_404(self):
        response = self.client.post(
            "/api/live/rooms/00000000/join/", {}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 404)

    def test_word_code_join_is_case_insensitive(self):
        # Word codes are stored lowercase; a participant may type any case.
        response = self.client.post(
            f"/api/live/rooms/{self.room.code.upper()}/join/",
            {}, content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ParticipantToken.objects.get().room, self.room)


class VoteTests(LiveTestCase):
    def test_vote_happy_path(self):
        token = self.join()
        self.open_question()
        response = self.vote(token, options=[self.correct.pk])
        self.assertEqual(response.status_code, 201)
        vote = Vote.objects.get()
        self.assertEqual(list(vote.options.all()), [self.correct])

    def test_double_vote_conflicts(self):
        token = self.join()
        self.open_question()
        self.vote(token, options=[self.correct.pk])
        response = self.vote(token, options=[self.wrong.pk])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(Vote.objects.count(), 1)

    def test_vote_requires_open_phase(self):
        token = self.join()
        run = self.open_question()
        run.phase = Run.Phase.CLOSED
        run.save()
        self.assertEqual(self.vote(token, options=[self.correct.pk]).status_code, 409)

    def test_single_choice_rejects_multiple_options(self):
        token = self.join()
        self.open_question()
        response = self.vote(token, options=[self.correct.pk, self.wrong.pk])
        self.assertEqual(response.status_code, 400)

    def test_rejects_option_of_other_question(self):
        other_question = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.SINGLE_CHOICE
        )
        foreign = AnswerOption.objects.create(question=other_question, text="x")
        token = self.join()
        self.open_question()
        self.assertEqual(self.vote(token, options=[foreign.pk]).status_code, 400)

    def test_word_cloud_multiple_answers(self):
        # allow_multiple word clouds accept several terms from one token (#14);
        # a plain word cloud still rejects the second submission.
        cloud = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.WORD_CLOUD,
            allow_multiple=True,
        )
        self.open_question(cloud)
        token = self.join()
        self.assertEqual(self.vote(token, text="Klima").status_code, 201)
        self.assertEqual(self.vote(token, text="Wasser").status_code, 201)
        # One term per person: the same word again (any case) is rejected.
        self.assertEqual(self.vote(token, text="  klima ").status_code, 409)
        self.assertEqual(Vote.objects.filter(token__key=token).count(), 2)

        plain = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.WORD_CLOUD,
        )
        Run.objects.update(phase=Run.Phase.FINISHED)
        self.open_question(plain)
        token2 = self.join()
        self.assertEqual(self.vote(token2, text="A").status_code, 201)
        self.assertEqual(self.vote(token2, text="B").status_code, 409)

    def test_wordcloud_max_answers_enforced(self):
        # Per-participant cap (#76): the cap-th term is accepted, one more is
        # rejected (409); enforced server-side regardless of the client.
        cloud = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.WORD_CLOUD,
            allow_multiple=True, wordcloud_max_answers=2,
        )
        self.open_question(cloud)
        token = self.join()
        self.assertEqual(self.vote(token, text="Klima").status_code, 201)
        self.assertEqual(self.vote(token, text="Wasser").status_code, 201)
        self.assertEqual(self.vote(token, text="Wald").status_code, 409)
        self.assertEqual(Vote.objects.filter(token__key=token).count(), 2)

    def test_wordcloud_max_answers_zero_is_unlimited(self):
        cloud = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.WORD_CLOUD,
            allow_multiple=True, wordcloud_max_answers=0,
        )
        self.open_question(cloud)
        token = self.join()
        for term in ("A", "B", "C", "D"):
            self.assertEqual(self.vote(token, text=term).status_code, 201)
        self.assertEqual(Vote.objects.filter(token__key=token).count(), 4)

    def test_word_cloud_retract(self):
        # A participant can withdraw their own term while the question is
        # open; afterwards the same term can be submitted again (#14).
        cloud = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.WORD_CLOUD,
            allow_multiple=True,
        )
        self.open_question(cloud)
        token = self.join()
        self.vote(token, text="Klima")
        self.assertEqual(Vote.objects.filter(token__key=token).count(), 1)
        r = self.client.post(
            f"/api/live/rooms/{self.room.code}/retract/",
            {"token": token, "text": "klima"},  # case-insensitive match
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Vote.objects.filter(token__key=token).count(), 0)
        # Retracted → can be entered again.
        self.assertEqual(self.vote(token, text="Klima").status_code, 201)

    def test_word_cloud_vote_and_normalization(self):
        cloud = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.WORD_CLOUD
        )
        self.open_question(cloud)
        for raw in ["Klima", "klima", "  KLIMA ", "Wasser"]:
            token = self.join()
            self.assertEqual(self.vote(token, text=raw).status_code, 201)
        payloads = build_payloads(self.room)
        words = {w["text"]: w["count"] for w in payloads["presenter"]["words"]}
        # Case variants merge; the most frequent spelling wins the display.
        self.assertEqual(sum(words.values()), 4)
        self.assertEqual(len(words), 2)
        self.assertIn(words.get("Klima", words.get("klima", words.get("KLIMA"))), [3])
        self.assertEqual(words["Wasser"], 1)


class ControlTests(LiveTestCase):
    def login(self):
        self.client.force_login(self.owner)

    def test_start_run_creates_and_reuses(self):
        self.login()
        response = self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        run_id = response.json()["run"]
        again = self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {},
            content_type="application/json",
        ).json()
        self.assertEqual(again["run"], run_id)

    def test_start_run_reset_deletes_votes(self):
        token = self.join()
        self.open_question()
        self.vote(token, options=[self.correct.pk])
        self.login()
        self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {"reset": True},
            content_type="application/json",
        )
        self.assertEqual(Vote.objects.count(), 0)
        self.assertEqual(Run.objects.count(), 1)

    def test_continue_keeps_votes(self):
        token = self.join()
        self.open_question()
        self.vote(token, options=[self.correct.pk])
        self.login()
        self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {},
            content_type="application/json",
        )
        self.assertEqual(Vote.objects.count(), 1)

    def _finished_run_with_vote(self):
        run = self.open_question()
        token = self.join()
        self.vote(token, options=[self.correct.pk])
        run.phase = Run.Phase.FINISHED
        run.save(update_fields=["phase"])
        return run

    def test_archive_starts_new_run_keeping_old(self):
        # "Archivieren": the old Durchführung stays as an archive, a fresh
        # empty run begins alongside it (#17).
        self.login()
        run_a = self._finished_run_with_vote()
        resp = self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {"existing": "archive"},
            content_type="application/json",
        ).json()
        self.assertNotEqual(resp["run"], run_a.pk)
        self.assertEqual(Run.objects.count(), 2)
        self.assertEqual(run_a.votes.count(), 1)

    def test_archive_finishes_unfinished_run_with_votes(self):
        # Archiving must work even when the previous run was left UNFINISHED
        # (presenter closed the tab without ending it) — the common case (#70).
        # The run is finished (kept as an archive) and a fresh empty run begins.
        self.login()
        run_a = self.open_question()
        token = self.join()
        self.vote(token, options=[self.correct.pk])
        run_a.refresh_from_db()
        self.assertNotEqual(run_a.phase, Run.Phase.FINISHED)  # still open
        resp = self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {"existing": "archive"},
            content_type="application/json",
        ).json()
        run_a.refresh_from_db()
        self.assertEqual(run_a.phase, Run.Phase.FINISHED)  # archived, not reused
        self.assertNotEqual(resp["run"], run_a.pk)  # a brand-new run
        self.assertEqual(Run.objects.count(), 2)
        self.assertEqual(run_a.votes.count(), 1)  # old answers preserved
        self.assertEqual(Run.objects.get(pk=resp["run"]).votes.count(), 0)

    def test_live_status_reports_active_run_has_votes(self):
        # The start dialog needs to know whether the run it would resume already
        # carries answers, so archiving can be offered (#70).
        self.login()
        self.open_question()
        token = self.join()
        self.vote(token, options=[self.correct.pk])
        resp = self.client.get(
            f"/api/question-sets/{self.question_set.pk}/live-status/"
        ).json()
        self.assertTrue(resp["active_run"])
        self.assertTrue(resp["has_votes"])
        self.assertTrue(resp["active_run_has_votes"])

    def test_live_status_recently_started_true_for_open_run(self):
        self.login()
        run = self.open_question()
        Run.objects.filter(pk=run.pk).update(opened_at=timezone.now())
        resp = self.client.get(
            f"/api/question-sets/{self.question_set.pk}/live-status/"
        ).json()
        self.assertTrue(resp["recently_started"])

    def test_live_status_recently_started_false_when_only_finished(self):
        self.login()
        run = self._finished_run_with_vote()
        Run.objects.filter(pk=run.pk).update(opened_at=timezone.now())  # recent but finished
        resp = self.client.get(
            f"/api/question-sets/{self.question_set.pk}/live-status/"
        ).json()
        self.assertFalse(resp["recently_started"])

    def test_live_status_recently_started_false_when_stale(self):
        self.login()
        run = self.open_question()
        Run.objects.filter(pk=run.pk).update(
            opened_at=timezone.now() - timezone.timedelta(minutes=121)
        )
        resp = self.client.get(
            f"/api/question-sets/{self.question_set.pk}/live-status/"
        ).json()
        self.assertFalse(resp["recently_started"])

    def test_live_status_recently_started_false_when_never_opened(self):
        self.login()
        self.open_question()  # phase OPEN but opened_at stays null
        resp = self.client.get(
            f"/api/question-sets/{self.question_set.pk}/live-status/"
        ).json()
        self.assertFalse(resp["recently_started"])

    def test_easy_mode_continues_recent_session_across_day(self):
        # An ongoing session (non-finished run opened within the window) continues
        # even when it was created on a previous calendar day — no archive.
        self.owner.easy_mode = True
        self.owner.is_staff = False
        self.owner.save(update_fields=["easy_mode", "is_staff"])
        self.login()
        run = self.open_question()
        token = self.join()
        self.vote(token, options=[self.correct.pk])
        Run.objects.filter(pk=run.pk).update(
            opened_at=timezone.now(),
            created_at=timezone.now() - timezone.timedelta(days=1),
        )
        resp = self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {"mode": "live"},
            content_type="application/json",
        ).json()
        self.assertEqual(resp["run"], run.pk)      # continued, not archived
        self.assertEqual(Run.objects.count(), 1)

    def test_continue_reactivates_latest_run(self):
        # "Weiterzählen": the most recent Durchführung is reactivated and its
        # votes are kept — no second run (#17).
        self.login()
        run_a = self._finished_run_with_vote()
        resp = self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {"existing": "continue"},
            content_type="application/json",
        ).json()
        self.assertEqual(resp["run"], run_a.pk)
        self.assertEqual(Run.objects.count(), 1)
        run_a.refresh_from_db()
        self.assertNotEqual(run_a.phase, Run.Phase.FINISHED)
        self.assertEqual(run_a.votes.count(), 1)

    def test_continue_recent_session_resumes_in_place(self):
        self.login()
        run = self.open_question()
        Run.objects.filter(pk=run.pk).update(opened_at=timezone.now())
        resp = self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {"existing": "continue"},
            content_type="application/json",
        ).json()
        run.refresh_from_db()
        self.assertEqual(resp["run"], run.pk)
        self.assertEqual(run.phase, Run.Phase.OPEN)                 # not reset to lobby
        self.assertEqual(run.active_question_id, self.question.pk)  # preserved

    def test_continue_stale_unfinished_run_resets_to_lobby(self):
        self.login()
        run = self.open_question()
        Run.objects.filter(pk=run.pk).update(
            opened_at=timezone.now() - timezone.timedelta(minutes=121)
        )
        resp = self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {"existing": "continue"},
            content_type="application/json",
        ).json()
        run.refresh_from_db()
        self.assertEqual(resp["run"], run.pk)
        self.assertEqual(run.phase, Run.Phase.LOBBY)   # reset (not recent)
        self.assertIsNone(run.active_question_id)      # reset

    def test_easy_mode_archives_when_last_run_another_day(self):
        # Effective easy mode + no explicit ``existing``: a finished run from
        # a previous calendar day is kept as an archive, a fresh run starts.
        self.owner.easy_mode = True
        self.owner.is_staff = False
        self.owner.save(update_fields=["easy_mode", "is_staff"])
        self.login()
        run_a = self._finished_run_with_vote()
        Run.objects.filter(pk=run_a.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=1)
        )
        resp = self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {"mode": "live"},
            content_type="application/json",
        ).json()
        self.assertNotEqual(resp["run"], run_a.pk)
        self.assertEqual(Run.objects.count(), 2)
        run_a.refresh_from_db()
        self.assertEqual(run_a.phase, Run.Phase.FINISHED)
        self.assertEqual(run_a.votes.count(), 1)

    def test_easy_mode_continues_when_last_run_today(self):
        # Same easy-mode owner, but the latest non-empty run is from today:
        # auto-decision must be "continue", not "archive".
        self.owner.easy_mode = True
        self.owner.is_staff = False
        self.owner.save(update_fields=["easy_mode", "is_staff"])
        self.login()
        run_a = self._finished_run_with_vote()
        resp = self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {"mode": "live"},
            content_type="application/json",
        ).json()
        self.assertEqual(resp["run"], run_a.pk)
        self.assertEqual(Run.objects.count(), 1)
        run_a.refresh_from_db()
        self.assertNotEqual(run_a.phase, Run.Phase.FINISHED)
        self.assertEqual(run_a.votes.count(), 1)

    def test_easy_mode_explicit_existing_wins(self):
        # An explicit ``existing`` always overrides the easy-mode automatic,
        # even when the auto-decision would have been "archive".
        self.owner.easy_mode = True
        self.owner.is_staff = False
        self.owner.save(update_fields=["easy_mode", "is_staff"])
        self.login()
        run_a = self._finished_run_with_vote()
        Run.objects.filter(pk=run_a.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=1)
        )
        resp = self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {"mode": "live", "existing": "continue"},
            content_type="application/json",
        ).json()
        self.assertEqual(resp["run"], run_a.pk)
        self.assertEqual(Run.objects.count(), 1)

    def test_admin_at_pro_default_no_auto_archive(self):
        # Admins default to Pro (``easy_mode`` is None -> effective_easy_mode
        # is False for staff): no easy-mode automatic, so the default (no
        # ``existing``) behaves as the plain "continue" fallback, not
        # auto-archive.
        self.owner.easy_mode = None
        self.owner.is_staff = True
        self.owner.save(update_fields=["easy_mode", "is_staff"])
        self.login()
        run_a = self._finished_run_with_vote()
        Run.objects.filter(pk=run_a.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=1)
        )
        resp = self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {"mode": "live"},
            content_type="application/json",
        ).json()
        self.assertEqual(resp["run"], run_a.pk)
        self.assertEqual(Run.objects.count(), 1)

    def test_admin_in_simple_mode_auto_archives(self):
        # An admin who explicitly chose Simple (``easy_mode=True``) still
        # gets the easy-mode automatic, even though they are staff.
        self.owner.is_staff = True
        self.owner.easy_mode = True  # admin explicitly chose simple
        self.owner.save(update_fields=["is_staff", "easy_mode"])
        self.login()
        run_a = self._finished_run_with_vote()
        Run.objects.filter(pk=run_a.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=1)
        )
        resp = self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {"mode": "live"},
            content_type="application/json",
        ).json()
        self.assertNotEqual(resp["run"], run_a.pk)
        self.assertEqual(Run.objects.count(), 2)
        run_a.refresh_from_db()
        self.assertEqual(run_a.phase, Run.Phase.FINISHED)
        self.assertEqual(run_a.votes.count(), 1)

    def test_archive_results_finishes_and_prepares_fresh(self):
        # #27 shortcut: the running Durchführung is finished (kept as archive)
        # and an empty run is prepared so the next presentation starts clean.
        self.login()
        run_a = self.open_question()
        token = self.join()
        self.vote(token, options=[self.correct.pk])
        resp = self.client.post(
            f"/api/question-sets/{self.question_set.pk}/archive-results/",
            {},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        run_a.refresh_from_db()
        self.assertEqual(run_a.phase, Run.Phase.FINISHED)
        self.assertIsNotNone(run_a.ended_at)
        self.assertEqual(run_a.votes.count(), 1)  # data kept
        fresh = Run.objects.exclude(pk=run_a.pk).get()
        self.assertEqual(fresh.phase, Run.Phase.LOBBY)
        self.assertEqual(resp.json()["run"], fresh.pk)

    def test_archive_results_idempotent(self):
        # A second click reuses the already-prepared empty run.
        self.login()
        self.open_question()
        token = self.join()
        self.vote(token, options=[self.correct.pk])
        url = f"/api/question-sets/{self.question_set.pk}/archive-results/"
        r1 = self.client.post(url, {}, content_type="application/json").json()
        r2 = self.client.post(url, {}, content_type="application/json").json()
        self.assertEqual(r1["run"], r2["run"])
        self.assertEqual(Run.objects.count(), 2)

    def test_results_omit_empty_prepared_run(self):
        # The prepared empty run must not show up as a Durchführung (#27).
        self.login()
        self.open_question()
        token = self.join()
        self.vote(token, options=[self.correct.pk])
        self.client.post(
            f"/api/question-sets/{self.question_set.pk}/archive-results/",
            {},
            content_type="application/json",
        )
        data = self.client.get(
            f"/api/question-sets/{self.question_set.pk}/results/"
        ).json()
        self.assertEqual(len(data["results"]), 1)

    def test_first_opened_at_set_once(self):
        self.login()
        run = Run.objects.create(question_set=self.question_set)
        url = f"/api/runs/{run.pk}/control/"
        self.client.post(
            url, {"phase": "open", "question": self.question.pk},
            content_type="application/json",
        )
        run.refresh_from_db()
        first = run.first_opened_at
        self.assertIsNotNone(first)
        # Re-opening (another question) must not overwrite the archive name.
        self.client.post(
            url, {"phase": "open", "question": self.question.pk},
            content_type="application/json",
        )
        run.refresh_from_db()
        self.assertEqual(run.first_opened_at, first)

    def test_control_phase_machine(self):
        self.login()
        run = Run.objects.create(question_set=self.question_set)
        url = f"/api/runs/{run.pk}/control/"
        response = self.client.post(
            url,
            {"phase": "open", "question": self.question.pk},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        run.refresh_from_db()
        self.assertEqual(run.phase, "open")
        self.assertEqual(run.active_question, self.question)
        # Open without a question is invalid.
        response = self.client.post(
            url, {"phase": "open", "question": None}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        # Finishing stamps ended_at.
        self.client.post(url, {"phase": "finished"}, content_type="application/json")
        run.refresh_from_db()
        self.assertIsNotNone(run.ended_at)

    def test_close_triggers_eager_ai_wordcloud(self):
        # #75: closing the vote kicks off the AI word-cloud computation so the
        # presenter can switch to the AI views instantly.
        from unittest.mock import patch
        self.login()
        wc = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.WORD_CLOUD,
            wordcloud_ai_enabled=True, position=5,
        )
        run = Run.objects.create(question_set=self.question_set)
        url = f"/api/runs/{run.pk}/control/"
        self.client.post(
            url, {"phase": "open", "question": wc.pk}, content_type="application/json"
        )
        with patch("live.views.ai_wordcloud_live.ensure_result") as ensure:
            self.client.post(url, {"phase": "closed"}, content_type="application/json")
        ensure.assert_called_once_with(run.pk, wc.pk, self.room.pk)

    def test_close_no_eager_ai_for_plain_wordcloud(self):
        from unittest.mock import patch
        self.login()
        wc = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.WORD_CLOUD,
            wordcloud_ai_enabled=False, position=6,
        )
        run = Run.objects.create(question_set=self.question_set)
        url = f"/api/runs/{run.pk}/control/"
        self.client.post(
            url, {"phase": "open", "question": wc.pk}, content_type="application/json"
        )
        with patch("live.views.ai_wordcloud_live.ensure_result") as ensure:
            self.client.post(url, {"phase": "closed"}, content_type="application/json")
        ensure.assert_not_called()

    def test_ai_wordcloud_result_kept_warm_on_deactivate(self):
        # #75: deactivating a view must NOT drop the cached AI result.
        from live import ai_wordcloud_live as m
        key = (912345, 998877)
        with m._lock:
            m._results[key] = {"merged": [{"text": "x", "count": 1}],
                               "clusters": [], "pending": False}
        try:
            m.set_active(key[0], key[1], self.room.pk, False)
            self.assertIsNotNone(m.get_result(key[0], key[1]))
        finally:
            with m._lock:
                m._results.pop(key, None)
                m._active.discard(key)

    def test_control_requires_owner(self):
        run = Run.objects.create(question_set=self.question_set)
        eve = User.objects.create_user(username="eve")
        self.client.force_login(eve)
        response = self.client.post(
            f"/api/runs/{run.pk}/control/",
            {"phase": "lobby"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)

    def test_live_status_reports_votes(self):
        token = self.join()
        self.open_question()
        self.vote(token, options=[self.correct.pk])
        self.login()
        payload = self.client.get(
            f"/api/question-sets/{self.question_set.pk}/live-status/"
        ).json()
        self.assertTrue(payload["has_votes"])
        self.assertIsNotNone(payload["active_run"])

    def test_control_reveal_can_be_toggled_off(self):
        self.login()
        run = self.open_question()
        self.client.post(
            f"/api/runs/{run.pk}/control/",
            {"reveal": True},
            content_type="application/json",
        )
        run.refresh_from_db()
        self.assertTrue(run.answers_revealed)
        resp = self.client.post(
            f"/api/runs/{run.pk}/control/",
            {"reveal": False},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        run.refresh_from_db()
        self.assertFalse(run.answers_revealed)


class StatePayloadTests(LiveTestCase):
    def test_participant_sees_question_only_when_open(self):
        run = self.open_question()
        run.phase = Run.Phase.PREVIEW
        run.save()
        payloads = build_payloads(self.room)
        self.assertNotIn("question", payloads["participant"])
        self.assertIn("question", payloads["presenter"])
        run.phase = Run.Phase.OPEN
        run.save()
        payloads = build_payloads(self.room)
        self.assertIn("question", payloads["participant"])
        # Participants never receive correctness flags.
        option = payloads["participant"]["question"]["options"][0]
        self.assertNotIn("is_correct", option)

    def test_participant_payload_carries_run_id(self):
        # Devices scope their "already voted" marker to the run so a re-run
        # lets them vote again (client-side; the run id makes it possible).
        run = self.open_question()
        payloads = build_payloads(self.room)
        self.assertEqual(payloads["participant"]["run_id"], run.pk)

    def test_presenter_gets_results(self):
        token = self.join()
        self.open_question()
        self.vote(token, options=[self.correct.pk])
        payloads = build_payloads(self.room)
        results = {
            resolve_translated_text(r["text"]): r["count"]
            for r in payloads["presenter"]["results"]
        }
        self.assertEqual(results, {"4": 1, "5": 0})
        self.assertEqual(payloads["presenter"]["votes"], 1)

    def test_presenter_before_after_comparison(self):
        # #54: when the active question is an after-question, the presenter
        # payload carries the before-question's aggregates from the same run.
        after = Question.objects.create(
            question_set=self.question_set,
            kind=Question.Kind.SINGLE_CHOICE,
            text="<p>2+2?</p>",
            before_question=self.question,
            position=5,
        )
        AnswerOption.objects.create(question=after, text="4", is_correct=True, position=0)
        AnswerOption.objects.create(question=after, text="5", position=1)
        token = self.join()
        run = self.open_question()  # before-question active, collect a vote
        self.vote(token, options=[self.correct.pk])
        run.active_question = after
        run.phase = Run.Phase.RESULTS
        run.save()
        before = build_payloads(self.room)["presenter"]["before"]
        self.assertEqual(before["votes"], 1)
        counts = {
            resolve_translated_text(r["text"]): r["count"] for r in before["results"]
        }
        self.assertEqual(counts, {"4": 1, "5": 0})

    def test_question_and_option_text_are_language_maps(self):
        # #33 MR2: the SSE hub broadcasts one payload to every participant,
        # so authored text is a {de, en} map, resolved client-side.
        self.question.text_de = "<p>Wie viel?</p>"
        self.question.text_en = "<p>How much?</p>"
        self.question.save(update_fields=["text_de", "text_en"])
        self.correct.text_de = "vier"
        self.correct.text_en = "four"
        self.correct.save(update_fields=["text_de", "text_en"])
        self.open_question()
        payloads = build_payloads(self.room)
        question = payloads["presenter"]["question"]
        self.assertEqual(
            question["text"], {"de": "<p>Wie viel?</p>", "en": "<p>How much?</p>"}
        )
        option = question["options"][0]
        self.assertEqual(option["text"], {"de": "vier", "en": "four"})

    def test_room_title_and_set_title_are_language_maps(self):
        self.room.title_de = "Biologie"
        self.room.title_en = "Biology"
        self.room.save(update_fields=["title_de", "title_en"])
        self.question_set.title_de = "Termin Eins"
        self.question_set.title_en = "Session One"
        self.question_set.save(update_fields=["title_de", "title_en"])
        self.open_question()
        payloads = build_payloads(self.room)
        self.assertEqual(
            payloads["presenter"]["room"]["title"],
            {"de": "Biologie", "en": "Biology"},
        )
        self.assertEqual(
            payloads["presenter"]["set_title"],
            {"de": "Termin Eins", "en": "Session One"},
        )

    def test_shuffle_is_stable_per_run(self):
        self.question.shuffle_options = True
        self.question.save()
        self.open_question()
        first = build_payloads(self.room)["participant"]["question"]["options"]
        second = build_payloads(self.room)["participant"]["question"]["options"]
        self.assertEqual(first, second)

    def test_idle_room(self):
        payloads = build_payloads(self.room)
        self.assertEqual(payloads["participant"]["phase"], "idle")

    def test_per_question_reveal_overrides_set(self):
        # #28: a question may override the set-wide reveal mode.
        self.question_set.reveal_answers = "never"
        self.question_set.save(update_fields=["reveal_answers"])
        self.question.reveal_answers = "immediately"
        self.question.save(update_fields=["reveal_answers"])
        self.open_question()
        payloads = build_payloads(self.room)
        self.assertEqual(payloads["presenter"]["reveal_answers"], "immediately")

    def test_inherit_uses_set_reveal(self):
        self.question_set.reveal_answers = "immediately"
        self.question_set.save(update_fields=["reveal_answers"])
        # self.question keeps the default "inherit".
        self.open_question()
        payloads = build_payloads(self.room)
        self.assertEqual(payloads["presenter"]["reveal_answers"], "immediately")

    def test_question_payload_carries_wordcloud_live(self):
        # #30: the presenter uses this flag to hide the cloud while open.
        wc = Question.objects.create(
            question_set=self.question_set,
            kind=Question.Kind.WORD_CLOUD,
            text="<p>Stichwort?</p>",
            wordcloud_live=False,
        )
        self.open_question(question=wc)
        payloads = build_payloads(self.room)
        self.assertFalse(payloads["presenter"]["question"]["wordcloud_live"])

    def test_question_payload_carries_wordcloud_max_answers(self):
        # #76: the participant page needs the per-person cap to stop input.
        wc = Question.objects.create(
            question_set=self.question_set,
            kind=Question.Kind.WORD_CLOUD,
            text="<p>Stichwort?</p>",
            allow_multiple=True,
            wordcloud_max_answers=3,
        )
        self.open_question(question=wc)
        payloads = build_payloads(self.room)
        self.assertEqual(payloads["presenter"]["question"]["wordcloud_max_answers"], 3)
        self.assertEqual(payloads["participant"]["question"]["wordcloud_max_answers"], 3)


class ParticipantPageTests(LiveTestCase):
    def test_pages_render(self):
        self.assertEqual(self.client.get("/p/").status_code, 200)
        self.assertContains(self.client.get(f"/p/{self.room.code}/"), self.room.title)
        self.assertEqual(self.client.get("/p/00000000/").status_code, 404)

    def test_qr_png(self):
        response = self.client.get(f"/p/{self.room.code}/qr.png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")

    def test_closing_info_rendered_system_then_room(self):
        # #24: the finished screen carries system-wide + room stored HTML.
        # editor-unify #49: both fields now hold sanitized HTML (not
        # Markdown) — set them as such.
        from common.models import SiteConfig

        site = SiteConfig.load()
        site.closing_info = "System-Hinweis"
        site.save()
        self.room.closing_info = '<p><a href="https://e.com">Raum-Link</a></p>'
        self.room.save(update_fields=["closing_info"])
        html = self.client.get(f"/p/{self.room.code}/").content.decode()
        self.assertIn("System-Hinweis", html)
        self.assertIn('href="https://e.com"', html)

    def test_closing_info_renders_stored_html_directly(self):
        # editor-unify #49: closing_info now stores sanitized HTML (not
        # Markdown) — the page must show it as-is, not re-run it through the
        # Markdown parser (which would escape/mangle the already-HTML tags).
        self.room.closing_info_de = "<p>Danke <strong>alle</strong></p>"
        self.room.save(update_fields=["closing_info_de"])
        html = self.client.get(f"/p/{self.room.code}/").content.decode()
        self.assertIn("<strong>alle</strong>", html)


class ParticipantI18nTests(LiveTestCase):
    def test_participant_page_renders_english(self):
        # LocaleMiddleware + {% trans %} switch the framework-free
        # participant template to English via Accept-Language.
        resp = self.client.get(f"/p/{self.room.code}/", HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('<html lang="en">', html)
        self.assertIn("My answers", html)
        self.assertNotIn("Meine Antworten", html)

    def test_no_template_syntax_leaks_into_page(self):
        # Regression: a multi-line {# #} note rendered as visible text because
        # Django's {# #} comment is single-line only (must be {% comment %}).
        # Leaked template syntax ({# / {% / {{) in the output is the signature.
        resp = self.client.get(f"/p/{self.room.code}/")
        html = resp.content.decode()
        self.assertNotIn("{#", html)
        self.assertNotIn("{%", html)
        self.assertNotIn("{{", html)
        self.assertIn('id="menu-wrap"', html)  # the menu still renders

    def test_participant_page_renders_german_via_accept_language(self):
        resp = self.client.get(f"/p/{self.room.code}/", HTTP_ACCEPT_LANGUAGE="de")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('<html lang="de">', html)
        self.assertIn("Meine Antworten", html)

    def test_participant_page_defaults_to_english(self):
        # No Accept-Language header at all — the true default (English).
        resp = self.client.get(f"/p/{self.room.code}/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn('<html lang="en">', resp.content.decode())

    def test_language_cookie_switches_page(self):
        self.client.cookies["django_language"] = "en"
        resp = self.client.get(f"/p/{self.room.code}/")
        self.assertIn('<html lang="en">', resp.content.decode())

    def test_participant_home_lang_query_switches_to_english(self):
        # ?lang= is the QR/short-link entry point (spec): it must win over
        # Accept-Language and persist via the language cookie.
        resp = self.client.get("/p/?lang=en", HTTP_ACCEPT_LANGUAGE="de")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('<html lang="en">', html)
        self.assertIn("Join a poll", html)
        self.assertEqual(resp.cookies[settings.LANGUAGE_COOKIE_NAME].value, "en")

    def test_participant_home_ignores_unsupported_lang(self):
        resp = self.client.get("/p/?lang=fr", HTTP_ACCEPT_LANGUAGE="de")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('<html lang="de">', html)
        self.assertNotIn(settings.LANGUAGE_COOKIE_NAME, resp.cookies)


class HasResultsTests(LiveTestCase):
    def test_set_listing_reports_results(self):
        self.client.force_login(self.owner)
        listing = self.client.get(
            f"/api/question-sets/?room={self.room.pk}"
        ).json()["results"]
        self.assertFalse(listing[0]["has_results"])
        token = self.join()
        self.open_question()
        self.vote(token, options=[self.correct.pk])
        listing = self.client.get(
            f"/api/question-sets/?room={self.room.pk}"
        ).json()["results"]
        self.assertTrue(listing[0]["has_results"])


class ResultsApiTests(LiveTestCase):
    def _run_with_votes(self):
        run = self.open_question()
        for option in (self.correct, self.correct, self.wrong):
            token = self.join()
            self.vote(token, options=[option.pk])
        run.phase = Run.Phase.FINISHED
        run.save()
        return run

    def test_results_aggregation(self):
        self._run_with_votes()
        self.client.force_login(self.owner)
        payload = self.client.get(
            f"/api/question-sets/{self.question_set.pk}/results/"
        ).json()["results"]
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["votes_total"], 3)
        counts = {
            resolve_translated_text(o["text"]): o["count"]
            for o in payload[0]["questions"][0]["options"]
        }
        self.assertEqual(counts, {"4": 2, "5": 1})

    def test_results_expose_before_question_link(self):
        # #54: each result item carries its before-question id (null when
        # standalone) so the results view can pair before/after.
        self._run_with_votes()
        self.client.force_login(self.owner)
        payload = self.client.get(
            f"/api/question-sets/{self.question_set.pk}/results/"
        ).json()["results"]
        self.assertIn("before_question", payload[0]["questions"][0])
        self.assertIsNone(payload[0]["questions"][0]["before_question"])

    def test_results_require_owner(self):
        self._run_with_votes()
        eve = User.objects.create_user(username="eve")
        self.client.force_login(eve)
        response = self.client.get(
            f"/api/question-sets/{self.question_set.pk}/results/"
        )
        self.assertEqual(response.status_code, 404)

    def test_delete_single_run(self):
        run = self._run_with_votes()
        self.client.force_login(self.owner)
        response = self.client.delete(f"/api/runs/{run.pk}/")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(Run.objects.count(), 0)
        self.assertEqual(Vote.objects.count(), 0)

    def test_delete_all_results(self):
        self._run_with_votes()
        self._run_with_votes()
        self.client.force_login(self.owner)
        response = self.client.post(
            f"/api/question-sets/{self.question_set.pk}/delete-results/"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Run.objects.count(), 0)

    def test_csv_export(self):
        self._run_with_votes()
        self.client.force_login(self.owner)
        response = self.client.get(
            f"/api/question-sets/{self.question_set.pk}/results.csv"
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8-sig")
        self.assertIn("durchfuehrung;gestartet;frage_nr;frage;antwort;richtig;stimmen", body)
        self.assertIn(";1;2+2?;4;x;2", body)
        self.assertIn(";1;2+2?;5;;1", body)
        # #33 MR2: question/option text is a {de, en} map internally — the
        # CSV must resolve it to a canonical string, never leak the dict.
        self.assertNotIn("{", body)
        self.assertNotIn("'de'", body)

    def test_csv_requires_owner(self):
        self._run_with_votes()
        eve = User.objects.create_user(username="eve")
        self.client.force_login(eve)
        response = self.client.get(
            f"/api/question-sets/{self.question_set.pk}/results.csv"
        )
        self.assertEqual(response.status_code, 404)


class FinishedPhaseTests(LiveTestCase):
    def test_finished_room_reports_finished_not_idle(self):
        run = self.open_question()
        run.phase = Run.Phase.FINISHED
        run.save()
        payloads = build_payloads(self.room)
        self.assertEqual(payloads["participant"]["phase"], "finished")

    def test_room_without_runs_stays_idle(self):
        self.assertEqual(build_payloads(self.room)["participant"]["phase"], "idle")

    def test_new_run_wins_over_old_finished_one(self):
        old = self.open_question()
        old.phase = Run.Phase.FINISHED
        old.save()
        Run.objects.create(question_set=self.question_set, phase=Run.Phase.LOBBY)
        self.assertEqual(build_payloads(self.room)["participant"]["phase"], "lobby")


class V21FormatTests(LiveTestCase):
    def _question(self, kind, **kwargs):
        return Question.objects.create(
            question_set=self.question_set, kind=kind, position=99, **kwargs
        )

    def test_open_text_vote_stores_raw_text(self):
        question = self._question(Question.Kind.OPEN_TEXT)
        self.open_question(question)
        token = self.join()
        long_text = "Meinung:  " + "x" * 600
        response = self.vote(token, text=long_text)
        self.assertEqual(response.status_code, 201)
        vote = Vote.objects.get()
        # Clamped to 500, inner whitespace preserved (unlike word clouds).
        self.assertEqual(len(vote.text), 500)
        self.assertTrue(vote.text.startswith("Meinung:  x"))

    def test_open_text_appears_as_words_for_presenter(self):
        question = self._question(Question.Kind.OPEN_TEXT)
        self.open_question(question)
        self.vote(self.join(), text="Sehr gut")
        payloads = build_payloads(self.room)
        self.assertEqual(payloads["presenter"]["words"][0]["text"], "Sehr gut")

    def test_likert_allows_exactly_one_option(self):
        question = self._question(Question.Kind.LIKERT)
        scale = [
            AnswerOption.objects.create(question=question, text=t, position=i)
            for i, t in enumerate(["++", "+", "0", "-", "--"])
        ]
        self.open_question(question)
        token = self.join()
        response = self.vote(token, options=[scale[0].pk, scale[1].pk])
        self.assertEqual(response.status_code, 400)
        response = self.vote(token, options=[scale[1].pk])
        self.assertEqual(response.status_code, 201)


class TimerTests(LiveTestCase):
    def test_expired_timer_rejects_votes(self):
        from django.utils import timezone

        self.question.time_limit = 30
        self.question.save()
        run = self.open_question()
        run.opened_at = timezone.now() - timezone.timedelta(seconds=60)
        run.save()
        response = self.vote(self.join(), options=[self.correct.pk])
        self.assertEqual(response.status_code, 409)

    def test_running_timer_accepts_votes_and_reports_deadline(self):
        from django.utils import timezone

        self.question.time_limit = 300
        self.question.save()
        run = self.open_question()
        run.opened_at = timezone.now()
        run.save()
        self.assertEqual(
            self.vote(self.join(), options=[self.correct.pk]).status_code, 201
        )
        payloads = build_payloads(self.room)
        self.assertIn("ends_at", payloads["participant"])

    def test_control_open_stamps_opened_at(self):
        self.client.force_login(self.owner)
        run = Run.objects.create(question_set=self.question_set)
        self.client.post(
            f"/api/runs/{run.pk}/control/",
            {"phase": "open", "question": self.question.pk},
            content_type="application/json",
        )
        run.refresh_from_db()
        self.assertIsNotNone(run.opened_at)


class RevealTests(LiveTestCase):
    def test_reveal_flag_via_control(self):
        self.client.force_login(self.owner)
        run = self.open_question()
        run.phase = Run.Phase.RESULTS
        run.save()
        self.client.post(
            f"/api/runs/{run.pk}/control/", {"reveal": True},
            content_type="application/json",
        )
        run.refresh_from_db()
        self.assertTrue(run.answers_revealed)
        # Navigating to the next question resets the reveal.
        self.client.post(
            f"/api/runs/{run.pk}/control/",
            {"phase": "preview", "question": self.question.pk},
            content_type="application/json",
        )
        run.refresh_from_db()
        self.assertFalse(run.answers_revealed)


class ParticipantResultsTests(LiveTestCase):
    def _run_in_results(self):
        run = self.open_question()
        self.vote(self.join(), options=[self.correct.pk])
        run.phase = Run.Phase.RESULTS
        run.save()
        return run

    def test_disabled_by_default(self):
        self._run_in_results()
        payloads = build_payloads(self.room)
        self.assertNotIn("results", payloads["participant"])

    def test_enabled_shows_counts_without_correct_until_revealed(self):
        self.question_set.show_results_to_participants = True
        self.question_set.save()
        run = self._run_in_results()
        payloads = build_payloads(self.room)
        results = payloads["participant"]["results"]
        self.assertEqual(
            {resolve_translated_text(r["text"]): r["count"] for r in results},
            {"4": 1, "5": 0},
        )
        self.assertNotIn("is_correct", results[0])
        run.answers_revealed = True
        run.save()
        results = build_payloads(self.room)["participant"]["results"]
        self.assertTrue(any(r.get("is_correct") for r in results))


class SelfPacedTests(LiveTestCase):
    """Self-paced quiz (concept §6.3): all questions open, instant feedback."""

    def setUp(self):
        super().setUp()
        self.cloud = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.WORD_CLOUD, position=1
        )

    def start(self, **body):
        self.client.force_login(self.owner)
        response = self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {"mode": "self_paced", **body},
            content_type="application/json",
        )
        self.client.logout()
        return response

    def quiz(self, token=""):
        return self.client.get(
            f"/api/live/rooms/{self.room.code}/quiz/", {"token": token}
        )

    def test_start_opens_immediately(self):
        self.start()
        run = Run.objects.get()
        self.assertEqual(run.mode, Run.Mode.SELF_PACED)
        self.assertEqual(run.phase, Run.Phase.OPEN)
        self.assertIsNone(run.active_question)

    def test_mode_switch_repurposes_run(self):
        self.start()
        run = Run.objects.get()
        self.client.force_login(self.owner)
        self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {},
            content_type="application/json",
        )
        run.refresh_from_db()
        self.assertEqual(run.mode, Run.Mode.LIVE)
        self.assertEqual(run.phase, Run.Phase.LOBBY)
        self.assertEqual(Run.objects.count(), 1)

    def test_invalid_mode_rejected(self):
        response = self.start(mode="warp")
        self.assertEqual(response.status_code, 400)

    def test_vote_any_question_with_feedback(self):
        self.start()
        token = self.join()
        response = self.vote(
            token, question=self.question.pk, options=[self.wrong.pk]
        )
        self.assertEqual(response.status_code, 201)
        payload = response.json()
        self.assertFalse(payload["is_correct"])
        self.assertEqual(payload["correct"], [self.correct.pk])
        # Second question (text kind): accepted, no correctness feedback.
        response = self.vote(token, question=self.cloud.pk, text="Osmose")
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("correct", response.json())

    def test_vote_requires_known_question(self):
        self.start()
        token = self.join()
        self.assertEqual(self.vote(token, options=[self.correct.pk]).status_code, 400)
        self.assertEqual(
            self.vote(token, question=99999, options=[self.correct.pk]).status_code,
            400,
        )

    def test_double_vote_conflicts(self):
        self.start()
        token = self.join()
        self.vote(token, question=self.question.pk, options=[self.correct.pk])
        response = self.vote(token, question=self.question.pk, options=[self.wrong.pk])
        self.assertEqual(response.status_code, 409)

    def test_no_feedback_when_reveal_never(self):
        self.question_set.reveal_answers = "never"
        self.question_set.save()
        self.start()
        token = self.join()
        response = self.vote(
            token, question=self.question.pk, options=[self.correct.pk]
        )
        self.assertEqual(response.status_code, 201)
        self.assertNotIn("correct", response.json())

    def test_quiz_endpoint_returns_questions_and_answered(self):
        self.start()
        token = self.join()
        self.vote(token, question=self.question.pk, options=[self.correct.pk])
        payload = self.quiz(token).json()
        self.assertEqual(resolve_translated_text(payload["set_title"]), "Termin 1")
        self.assertTrue(payload["feedback"])
        self.assertEqual([q["id"] for q in payload["questions"]],
                         [self.question.pk, self.cloud.pk])
        # Options never leak is_correct.
        self.assertNotIn("is_correct", payload["questions"][0]["options"][0])
        self.assertEqual(
            payload["answered"], {str(self.question.pk): {"is_correct": True}}
        )

    def test_quiz_conflict_without_open_quiz(self):
        self.assertEqual(self.quiz().status_code, 409)
        self.open_question()  # live run, not self-paced
        self.assertEqual(self.quiz().status_code, 409)

    def test_payloads_signal_mode_and_progress(self):
        self.start()
        token = self.join()
        self.vote(token, question=self.question.pk, options=[self.correct.pk])
        payloads = build_payloads(self.room)
        participant = payloads["participant"]
        self.assertEqual(participant["mode"], "self_paced")
        self.assertEqual(participant["phase"], "open")
        self.assertNotIn("question", participant)
        presenter = payloads["presenter"]
        progress = {
            resolve_translated_text(row["text"]): row["votes"]
            for row in presenter["progress"]
        }
        self.assertEqual(progress["2+2?"], 1)
        self.assertEqual(presenter["votes_total"], 1)


class LikertSummaryTests(TestCase):
    """Diverging Likert aggregation (results.likert_summary)."""

    def _opts(self, *specs):
        """specs: (text, count, is_abstention) → options_with_counts shape."""
        return [
            {"id": i, "text": t, "is_correct": False, "is_abstention": a, "count": c}
            for i, (t, c, a) in enumerate(specs)
        ]

    def test_odd_scale_has_neutral_and_centre_line(self):
        from .results import likert_summary

        summary = likert_summary(
            self._opts(
                ("gar nicht", 2, False),
                ("eher nicht", 5, False),
                ("neutral", 8, False),
                ("eher", 20, False),
                ("voll", 15, False),
                ("Enthaltung", 3, True),
            )
        )
        self.assertEqual(summary["scale_total"], 50)
        self.assertEqual(summary["abstentions"], 3)
        self.assertEqual(summary["disagree"], 7)
        self.assertEqual(summary["neutral"], 8)
        self.assertEqual(summary["agree"], 35)
        self.assertEqual(summary["agree_pct"], 70.0)
        polarities = [s["polarity"] for s in summary["steps"]]
        self.assertEqual(
            polarities, ["disagree", "disagree", "neutral", "agree", "agree"]
        )
        # centre line = 14 % (disagree) + half of 16 % (neutral) = 22 %
        self.assertEqual(summary["divider"], 22.0)

    def test_even_scale_splits_between_middle_steps(self):
        from .results import likert_summary

        summary = likert_summary(
            self._opts(
                ("gar nicht", 3, False),
                ("eher nicht", 3, False),
                ("eher", 2, False),
                ("voll", 2, False),
            )
        )
        self.assertEqual(summary["neutral"], 0)
        self.assertEqual(summary["disagree"], 6)
        self.assertEqual(summary["agree"], 4)
        self.assertNotIn("neutral", [s["polarity"] for s in summary["steps"]])
        # divider between the two halves = lower-half share = 60 %
        self.assertEqual(summary["divider"], 60.0)

    def test_too_few_steps_returns_none(self):
        from .results import likert_summary

        self.assertIsNone(likert_summary(self._opts(("nur eine", 5, False))))
        self.assertIsNone(
            likert_summary(
                self._opts(("skala", 5, False), ("Enthaltung", 1, True))
            )
        )


class LikertResultsIntegrationTests(LiveTestCase):
    """Likert summary flows into the results API and CSV export."""

    def setUp(self):
        super().setUp()
        self.likert = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.LIKERT,
            text="<p>Gut strukturiert?</p>", position=5,
        )
        self.steps = [
            AnswerOption.objects.create(question=self.likert, text=t, position=i)
            for i, t in enumerate(["gar nicht", "eher nicht", "neutral", "eher", "voll"])
        ]
        self.abstain = AnswerOption.objects.create(
            question=self.likert, text="Enthaltung", position=5, is_abstention=True
        )

    def _cast(self, run, option, n):
        for _ in range(n):
            token = ParticipantToken.objects.create(room=self.room)
            vote = Vote.objects.create(run=run, question=self.likert, token=token)
            vote.options.add(option)

    def test_results_api_includes_likert_summary(self):
        from .results import run_results

        run = Run.objects.create(
            question_set=self.question_set, phase=Run.Phase.FINISHED
        )
        self._cast(run, self.steps[3], 3)  # eher
        self._cast(run, self.steps[4], 1)  # voll
        self._cast(run, self.abstain, 2)
        item = next(
            q for q in run_results(run)["questions"] if q["id"] == self.likert.pk
        )
        self.assertEqual(item["likert"]["agree"], 4)
        self.assertEqual(item["likert"]["abstentions"], 2)
        self.assertEqual(item["likert"]["agree_pct"], 100.0)

    def test_csv_has_percent_column_and_summary_rows(self):
        run = Run.objects.create(
            question_set=self.question_set, phase=Run.Phase.FINISHED
        )
        self._cast(run, self.steps[3], 3)
        self._cast(run, self.abstain, 1)
        self.client.force_login(self.owner)
        body = self.client.get(
            f"/api/question-sets/{self.question_set.pk}/results.csv"
        ).content.decode("utf-8-sig")
        # Recording mode (#53) added on-site/recording columns before prozent.
        self.assertIn("stimmen;vor_ort;aufzeichnung;prozent", body)
        self.assertIn("Zusammenfassung: Zustimmung;;3;;;100.0", body)
        self.assertIn("Zusammenfassung: Enthaltung;;1;", body)


class AiWordCloudTests(LiveTestCase):
    """Optional AI cleanup of a word-cloud result (Paket 2)."""

    def setUp(self):
        super().setUp()
        self.cloud = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.WORD_CLOUD, position=5
        )
        self.run = self.open_question(self.cloud)
        for raw in ["Klima", "Klima", "Klima", "Klimawandel", "Wasser", "Wasser", "Boden"]:
            self.vote(self.join(), text=raw)
        self.url = (
            f"/api/runs/{self.run.pk}/questions/{self.cloud.pk}/ai-wordcloud/"
        )

    @override_settings(**AI_ON)
    def test_merges_variants_recomputes_counts_and_clusters(self):
        reply = {
            "groups": [
                {
                    "label": "Klimawandel",
                    "cluster": "Umwelt",
                    # "Regen" is a hallucination — must be ignored.
                    "members": ["Klima", "Klimawandel", "Regen"],
                },
                {"label": "Wasser", "cluster": "Ressourcen", "members": ["Wasser"]},
            ]
        }
        with patch("basicbar_integrations.ai.chat_json", return_value=reply):
            self.client.force_login(self.owner)
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        labels = [c["label"] for c in data["clusters"]]
        # Biggest cluster first; the catch-all "Weitere" sinks to the end.
        self.assertEqual(labels, ["Umwelt", "Ressourcen", "Weitere"])
        umwelt = data["clusters"][0]["words"][0]
        self.assertEqual(umwelt["text"], "Klimawandel")
        self.assertEqual(umwelt["count"], 4)  # 3× Klima + 1× Klimawandel
        self.assertCountEqual(umwelt["variants"], ["Klima", "Klimawandel"])
        # "Boden" was never grouped by the model → its own "Weitere" entry.
        weitere = data["clusters"][-1]
        self.assertEqual(weitere["label"], "Weitere")
        self.assertEqual(weitere["words"][0]["text"], "Boden")
        # merged list is count-sorted and never exceeds the input vocabulary.
        self.assertEqual(data["merged"][0]["text"], "Klimawandel")
        self.assertEqual(sum(w["count"] for w in data["merged"]), 7)

    @override_settings(**AI_OFF)
    def test_disabled_returns_503(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(self.url).status_code, 503)

    @override_settings(**AI_ON)
    def test_requires_owner(self):
        with patch("basicbar_integrations.ai.chat_json", return_value={"groups": []}):
            self.client.force_login(User.objects.create_user(username="eve"))
            self.assertEqual(self.client.post(self.url).status_code, 404)

    @override_settings(**AI_ON)
    def test_non_wordcloud_rejected(self):
        url = f"/api/runs/{self.run.pk}/questions/{self.question.pk}/ai-wordcloud/"
        with patch("basicbar_integrations.ai.chat_json") as chat:
            self.client.force_login(self.owner)
            self.assertEqual(self.client.post(url).status_code, 400)
        chat.assert_not_called()

    @override_settings(**AI_ON)
    def test_empty_wordcloud_skips_model(self):
        empty_cloud = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.WORD_CLOUD, position=6
        )
        url = f"/api/runs/{self.run.pk}/questions/{empty_cloud.pk}/ai-wordcloud/"
        with patch("basicbar_integrations.ai.chat_json") as chat:
            self.client.force_login(self.owner)
            response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"clusters": [], "merged": []})
        chat.assert_not_called()


class AiReportTests(LiveTestCase):
    """Optional AI short report of a run (Paket 3)."""

    def _run_with_votes(self):
        run = self.open_question()  # OPEN on the single-choice question
        self.vote(self.join(), options=[self.correct.pk])
        self.vote(self.join(), options=[self.wrong.pk])
        return run

    @override_settings(**AI_ON)
    def test_returns_html_report(self):
        # editor-unify #49: the LLM still answers in Markdown, but the view
        # renders it to sanitized HTML so the client shows it via RichText.
        run = self._run_with_votes()
        with patch(
            "basicbar_integrations.ai.chat_json", return_value={"report": "**Überblick**\n\n- Punkt"}
        ) as chat:
            self.client.force_login(self.owner)
            response = self.client.post(f"/api/runs/{run.pk}/ai-summary/")
        self.assertEqual(response.status_code, 200)
        report = response.json()["report"]
        self.assertIn("<strong>Überblick</strong>", report)
        self.assertIn("<ul>", report)
        self.assertIn("<li>Punkt</li>", report)
        # The prompt carries the aggregated numbers, not raw personal data.
        prompt = chat.call_args.args[1]
        self.assertIn("Antworten insgesamt: 2", prompt)

    @override_settings(**AI_OFF)
    def test_disabled_returns_503(self):
        run = self._run_with_votes()
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.post(f"/api/runs/{run.pk}/ai-summary/").status_code, 503
        )

    @override_settings(**AI_ON)
    def test_requires_owner(self):
        run = self._run_with_votes()
        with patch("basicbar_integrations.ai.chat_json", return_value={"report": "x"}):
            self.client.force_login(User.objects.create_user(username="eve"))
            self.assertEqual(
                self.client.post(f"/api/runs/{run.pk}/ai-summary/").status_code, 404
            )

    @override_settings(**AI_ON)
    def test_empty_run_skips_model(self):
        run = Run.objects.create(question_set=self.question_set)
        with patch("basicbar_integrations.ai.chat_json") as chat:
            self.client.force_login(self.owner)
            response = self.client.post(f"/api/runs/{run.pk}/ai-summary/")
        self.assertEqual(response.status_code, 400)
        chat.assert_not_called()

    @override_settings(**AI_ON)
    def test_blank_report_is_502(self):
        run = self._run_with_votes()
        with patch("basicbar_integrations.ai.chat_json", return_value={"report": "   "}):
            self.client.force_login(self.owner)
            self.assertEqual(
                self.client.post(f"/api/runs/{run.pk}/ai-summary/").status_code, 502
            )


class AiFreeTextTests(LiveTestCase):
    """Optional AI evaluation of free-text answers (Paket 4)."""

    def setUp(self):
        super().setUp()
        self.q = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.OPEN_TEXT,
            text="<p>Hauptstadt von Frankreich?</p>", position=5,
        )
        self.run = self.open_question(self.q)
        for raw in ["Paris", "paris", "Berlin", "vielleicht Paris", "keine Ahnung"]:
            self.vote(self.join(), text=raw)
        self.url = f"/api/runs/{self.run.pk}/questions/{self.q.pk}/ai-freetext/"

    @override_settings(**AI_ON)
    def test_classifies_and_recomputes_counts(self):
        reply = {
            "items": [
                {"text": "Paris", "verdict": "korrekt", "note": "Hauptstadt"},
                {"text": "Berlin", "verdict": "falsch"},
                {"text": "vielleicht Paris", "verdict": "BOGUS"},  # invalid → unklar
                {"text": "Lyon", "verdict": "falsch"},  # hallucination → ignored
                # "keine Ahnung" omitted → falls back to unklar
            ]
        }
        with patch("basicbar_integrations.ai.chat_json", return_value=reply):
            self.client.force_login(self.owner)
            response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        groups = {g["verdict"]: g for g in response.json()["groups"]}
        self.assertEqual([g["verdict"] for g in response.json()["groups"]],
                         ["korrekt", "unklar", "falsch"])
        self.assertEqual(groups["korrekt"]["items"][0]["text"], "Paris")
        self.assertEqual(groups["korrekt"]["items"][0]["count"], 2)  # Paris + paris
        self.assertEqual(groups["korrekt"]["items"][0]["note"], "Hauptstadt")
        self.assertEqual(groups["falsch"]["count"], 1)  # only Berlin; Lyon dropped
        unklar_texts = {i["text"] for i in groups["unklar"]["items"]}
        self.assertEqual(unklar_texts, {"vielleicht Paris", "keine Ahnung"})
        total = sum(g["count"] for g in response.json()["groups"])
        self.assertEqual(total, 5)

    @override_settings(**AI_ON)
    def test_reference_reaches_prompt(self):
        with patch("basicbar_integrations.ai.chat_json", return_value={"items": []}) as chat:
            self.client.force_login(self.owner)
            self.client.post(self.url, {"reference": "Paris"},
                             content_type="application/json")
        self.assertIn("Erwartete Antwort", chat.call_args.args[1])
        self.assertIn("Paris", chat.call_args.args[1])

    @override_settings(**AI_OFF)
    def test_disabled_returns_503(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(self.url).status_code, 503)

    @override_settings(**AI_ON)
    def test_requires_owner(self):
        with patch("basicbar_integrations.ai.chat_json", return_value={"items": []}):
            self.client.force_login(User.objects.create_user(username="eve"))
            self.assertEqual(self.client.post(self.url).status_code, 404)

    @override_settings(**AI_ON)
    def test_non_open_text_rejected(self):
        url = f"/api/runs/{self.run.pk}/questions/{self.question.pk}/ai-freetext/"
        with patch("basicbar_integrations.ai.chat_json") as chat:
            self.client.force_login(self.owner)
            self.assertEqual(self.client.post(url).status_code, 400)
        chat.assert_not_called()


class AiLiveEvalTests(LiveTestCase):
    """Live free-text evaluation during a run (verschoben in die Frage)."""

    def setUp(self):
        super().setUp()
        self.oq = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.OPEN_TEXT,
            text="<p>Hauptstadt von Frankreich?</p>", position=5,
            ai_evaluate=True, evaluation_hint="Paris",
        )
        self.run = self.open_question(self.oq)

    def _cast(self, text):
        return self.vote(self.join(), text=text)

    @override_settings(**AI_ON)
    def test_evaluate_vote_labels_duplicates_with_one_call(self):
        self._cast("Paris")
        self._cast("paris")  # same text_key → shares the verdict
        first = Vote.objects.filter(question=self.oq).order_by("id").first()
        with patch(
            "basicbar_integrations.ai.chat_json", return_value={"verdict": "korrekt", "note": "ok"}
        ) as chat:
            ai_evaluation.evaluate_vote(first.pk, self.room.pk)
        chat.assert_called_once()
        verdicts = set(
            Vote.objects.filter(question=self.oq).values_list("ai_verdict", flat=True)
        )
        self.assertEqual(verdicts, {"korrekt"})

    @override_settings(**AI_ON)
    def test_evaluate_vote_uses_canonical_language_not_active_thread_language(self):
        # #33 MR2 content-i18n bug: evaluate_vote runs on a ThreadPoolExecutor
        # worker, which never ran LocaleMiddleware, so Django's active
        # language there is settings.LANGUAGE_CODE ("en"), not necessarily
        # the content's canonical language. The AI prompt must still use the
        # canonical (de) question text, never the active-language one.
        self.oq.text_de = "Deutsche Frage"
        self.oq.text_en = "English question"
        self.oq.save()
        self._cast("Paris")
        first = Vote.objects.filter(question=self.oq).order_by("id").first()
        with patch(
            "basicbar_integrations.ai.chat_json", return_value={"verdict": "korrekt", "note": ""}
        ) as chat, translation.override("en"):
            ai_evaluation.evaluate_vote(first.pk, self.room.pk)
        chat.assert_called_once()
        prompt = chat.call_args.args[1]
        self.assertIn("Deutsche Frage", prompt)
        self.assertNotIn("English question", prompt)

    @override_settings(**AI_ON)
    def test_classify_degrades_to_unklar_on_error(self):
        from basicbar_integrations import ai as ai_module

        with patch("basicbar_integrations.ai.chat_json", side_effect=ai_module.AIError("boom")):
            # Failure degrades to the middle category of the scale.
            self.assertEqual(
                ai_evaluation.classify(
                    "Frage", "", "Antwort", ["korrekt", "unklar", "falsch"]
                ),
                ("unklar", ""),
            )

    def test_freetext_evaluation_groups_and_pending(self):
        for text in ["Paris", "Paris", "Berlin", "Lyon"]:
            self._cast(text)
        votes = list(Vote.objects.filter(question=self.oq).order_by("id"))
        Vote.objects.filter(pk__in=[votes[0].pk, votes[1].pk]).update(ai_verdict="korrekt")
        Vote.objects.filter(pk=votes[2].pk).update(ai_verdict="falsch")
        # votes[3] stays pending
        summary = freetext_evaluation(self.run, self.oq)
        groups = {g["verdict"]: g for g in summary["groups"]}
        self.assertEqual(groups["korrekt"]["count"], 2)
        self.assertEqual(groups["korrekt"]["items"][0]["text"], "Paris")
        self.assertEqual(groups["falsch"]["count"], 1)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["total"], 4)

    def test_vote_schedules_evaluation_for_opted_in_question(self):
        with patch("live.ai_evaluation.schedule") as sched:
            self._cast("irgendetwas")
        sched.assert_called_once()

    def test_plain_open_text_does_not_schedule(self):
        plain = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.OPEN_TEXT,
            text="<p>Feedback?</p>", position=6,
        )
        self.run.active_question = plain  # reuse the single active run
        self.run.save(update_fields=["active_question"])
        with patch("live.ai_evaluation.schedule") as sched:
            self.vote(self.join(), text="war gut")
        sched.assert_not_called()

    def test_presenter_payload_includes_evaluation(self):
        self._cast("Paris")
        Vote.objects.filter(question=self.oq).update(ai_verdict="korrekt")
        presenter = build_payloads(self.room)["presenter"]
        self.assertIn("evaluation", presenter)
        self.assertEqual(presenter["evaluation"]["groups"][0]["verdict"], "korrekt")
        self.assertEqual(presenter["evaluation"]["pending"], 0)


class AiLiveWordCloudTests(LiveTestCase):
    """Live AI word-cloud views (consolidate + group) during a run (#Wortwolke)."""

    def setUp(self):
        super().setUp()
        self.wc = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.WORD_CLOUD,
            text="<p>Lieblingsband?</p>", position=7, allow_multiple=True,
            wordcloud_ai_enabled=True, wordcloud_grouping="nach Musikgenre",
        )
        self.run = self.open_question(self.wc)
        # Module state is global; make sure each test starts and ends clean.
        self.addCleanup(ai_wordcloud_live._active.clear)
        self.addCleanup(ai_wordcloud_live._results.clear)

    def _cast(self, text):
        return self.vote(self.join(), text=text)

    def test_grouping_criterion_in_system_prompt(self):
        self.assertIn("nach Musikgenre", ai_wordcloud.optimize_system("nach Musikgenre"))
        # Empty falls back to automatic themes (no criterion echoed).
        self.assertNotIn("nach Musikgenre", ai_wordcloud.optimize_system(""))

    @override_settings(**AI_ON)
    def test_activate_endpoint_toggles(self):
        self.client.force_login(self.owner)
        url = f"/api/runs/{self.run.pk}/wordcloud-ai/"
        with patch("live.ai_wordcloud_live.schedule"):
            resp = self.client.post(
                url, {"question": self.wc.pk, "active": True},
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(ai_wordcloud_live.is_active(self.run.pk, self.wc.pk))
        self.client.post(
            url, {"question": self.wc.pk, "active": False},
            content_type="application/json",
        )
        self.assertFalse(ai_wordcloud_live.is_active(self.run.pk, self.wc.pk))

    @override_settings(**AI_ON)
    def test_activate_rejects_when_not_enabled_for_question(self):
        self.wc.wordcloud_ai_enabled = False
        self.wc.save(update_fields=["wordcloud_ai_enabled"])
        self.client.force_login(self.owner)
        resp = self.client.post(
            f"/api/runs/{self.run.pk}/wordcloud-ai/",
            {"question": self.wc.pk, "active": True},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    @override_settings(**AI_ON)
    def test_activate_rejects_non_word_cloud(self):
        self.client.force_login(self.owner)
        resp = self.client.post(
            f"/api/runs/{self.run.pk}/wordcloud-ai/",
            {"question": self.question.pk, "active": True},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_activate_requires_ai_and_owner(self):
        # AI disabled → 503.
        self.client.force_login(self.owner)
        with override_settings(**AI_OFF):
            resp = self.client.post(
                f"/api/runs/{self.run.pk}/wordcloud-ai/",
                {"question": self.wc.pk, "active": True},
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 503)
        # Foreign user → 404.
        eve = User.objects.create_user(username="eve2")
        self.client.force_login(eve)
        with override_settings(**AI_ON):
            resp = self.client.post(
                f"/api/runs/{self.run.pk}/wordcloud-ai/",
                {"question": self.wc.pk, "active": True},
                content_type="application/json",
            )
        self.assertEqual(resp.status_code, 404)

    @override_settings(**AI_ON)
    def test_compute_stores_views_and_payload_carries_them(self):
        self._cast("Beatles")
        self._cast("Beatls")  # misspelling → merged by the model
        key = (self.run.pk, self.wc.pk)
        ai_wordcloud_live._active.add(key)
        grouped = {
            "groups": [
                {"label": "Beatles", "cluster": "Rock",
                 "members": ["Beatles", "Beatls"]},
            ]
        }
        with patch("basicbar_integrations.ai.chat_json", return_value=grouped) as chat:
            ai_wordcloud_live._compute(self.run.pk, self.wc.pk, self.room.pk)
        chat.assert_called_once()
        result = ai_wordcloud_live.get_result(*key)
        self.assertFalse(result["pending"])
        # Counts recomputed server-side: both spellings collapse to count 2.
        self.assertEqual(result["merged"][0]["text"], "Beatles")
        self.assertEqual(result["merged"][0]["count"], 2)
        self.assertEqual(result["clusters"][0]["label"], "Rock")
        # Presenter payload surfaces the AI views while active.
        presenter = build_payloads(self.room)["presenter"]
        self.assertIn("wordcloud_ai", presenter)
        self.assertEqual(presenter["wordcloud_ai"]["clusters"][0]["label"], "Rock")

    def test_vote_schedules_wordcloud_ai(self):
        with patch("live.ai_wordcloud_live.schedule") as sched:
            self._cast("Queen")
        sched.assert_called_once()


class FreetextScaleTests(LiveTestCase):
    """Configurable free-text scale (correctness / sentiment / custom)."""

    def setUp(self):
        super().setUp()
        from . import ai_freetext
        self.ai_freetext = ai_freetext

    def test_clean_categories_and_middle(self):
        f = self.ai_freetext
        self.assertEqual(f.clean_categories(["A", "a", " B "]), ["A", "B"])
        # <2 or >5 → default correctness scale.
        self.assertEqual(f.clean_categories(["nur eins"]), ["korrekt", "unklar", "falsch"])
        self.assertEqual(f.middle_category(["positiv", "neutral", "negativ"]), "neutral")

    def test_apply_evaluation_sentiment_and_fallback(self):
        answers = [{"text": "Toll", "count": 2}, {"text": "Ok", "count": 1},
                   {"text": "Mist", "count": 1}, {"text": "Hm", "count": 1}]
        data = {"items": [
            {"text": "Toll", "verdict": "positiv"},
            {"text": "Mist", "verdict": "negativ"},
            {"text": "Ok", "verdict": "quatsch"},  # unknown → middle (neutral)
            # "Hm" skipped → middle (neutral)
        ]}
        cats = ["positiv", "neutral", "negativ"]
        out = self.ai_freetext.apply_evaluation(answers, data, cats)
        self.assertEqual(out["categories"], cats)
        groups = {g["verdict"]: g for g in out["groups"]}
        self.assertEqual([g["verdict"] for g in out["groups"]], cats)  # order kept
        self.assertEqual(groups["positiv"]["count"], 2)
        self.assertEqual(groups["negativ"]["count"], 1)
        self.assertEqual(groups["neutral"]["count"], 2)  # Ok + Hm

    def test_freetext_evaluation_uses_scale_and_chart(self):
        q = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.OPEN_TEXT,
            text="<p>Wie fandest du es?</p>", position=8, ai_evaluate=True,
            evaluation_categories=["positiv", "neutral", "negativ"],
            evaluation_chart=True,
        )
        run = self.open_question(q)
        token = self.join()
        self.vote(token, text="Super")
        Vote.objects.filter(question=q).update(ai_verdict="positiv")
        summary = freetext_evaluation(run, q)
        self.assertEqual(summary["categories"], ["positiv", "neutral", "negativ"])
        self.assertTrue(summary["chart"])
        groups = {g["verdict"]: g for g in summary["groups"]}
        self.assertEqual(groups["positiv"]["count"], 1)


class FreetextScaleSerializerTests(LiveTestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.owner)

    def _create(self, categories):
        return self.client.post(
            "/api/questions/",
            {"question_set": self.question_set.pk, "kind": "open_text",
             "evaluation_categories": categories},
            content_type="application/json",
        )

    def test_custom_scale_saved(self):
        r = self._create(["Pro", "Contra"])
        self.assertEqual(r.status_code, 201)
        self.assertEqual(
            Question.objects.get(pk=r.json()["id"]).evaluation_categories,
            ["Pro", "Contra"],
        )

    def test_too_few_or_many_falls_back_to_default(self):
        r = self._create(["nur eins"])
        self.assertEqual(
            Question.objects.get(pk=r.json()["id"]).evaluation_categories,
            ["korrekt", "unklar", "falsch"],
        )


class RecordingModeTests(LiveTestCase):
    """Recording mode (#53) — async viewer voting on the original run."""

    def _start_recording(self, mode="live"):
        self.client.force_login(self.owner)
        data = self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {"mode": mode, "recording": True},
            content_type="application/json",
        ).json()
        self.client.logout()
        return data

    def test_start_run_mints_recording_token_for_live(self):
        data = self._start_recording()
        self.assertTrue(data["recording_token"])
        self.assertTrue(Run.objects.get(pk=data["run"]).recording_token)

    def test_self_paced_ignores_recording(self):
        data = self._start_recording(mode="self_paced")
        self.assertIsNone(data["recording_token"])

    def test_recording_questions_lists_questions(self):
        rec = self._start_recording()["recording_token"]
        payload = self.client.get(f"/api/live/recording/{rec}/").json()
        self.assertEqual(len(payload["questions"]), 1)
        self.assertEqual(payload["room_code"], self.room.code)

    def test_recording_vote_records_recording_source_and_results(self):
        data = self._start_recording()
        run = Run.objects.get(pk=data["run"])
        rec = data["recording_token"]
        viewer = self.join()
        body = {"token": viewer, "question": self.question.pk, "options": [self.correct.pk]}
        resp = self.client.post(
            f"/api/live/recording/{rec}/vote/", body, content_type="application/json"
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIn("results", resp.json())
        vote = Vote.objects.get(run=run, question=self.question)
        self.assertEqual(vote.source, Vote.Source.RECORDING)
        # One vote per viewer/question.
        again = self.client.post(
            f"/api/live/recording/{rec}/vote/", body, content_type="application/json"
        )
        self.assertEqual(again.status_code, 409)

    def test_recording_vote_unknown_token_404(self):
        resp = self.client.post(
            "/api/live/recording/does-not-exist/vote/",
            {"token": "x", "question": self.question.pk, "options": [self.correct.pk]},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_recording_vote_foreign_question_400(self):
        rec = self._start_recording()["recording_token"]
        other_set = QuestionSet.objects.create(room=self.room, title="Other")
        foreign = Question.objects.create(
            question_set=other_set, kind=Question.Kind.SINGLE_CHOICE, text="<p>x</p>"
        )
        viewer = self.join()
        resp = self.client.post(
            f"/api/live/recording/{rec}/vote/",
            {"token": viewer, "question": foreign.pk, "options": []},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_recording_answered_map_resumes_with_results(self):
        data = self._start_recording()
        rec = data["recording_token"]
        viewer = self.join()
        self.client.post(
            f"/api/live/recording/{rec}/vote/",
            {"token": viewer, "question": self.question.pk, "options": [self.correct.pk]},
            content_type="application/json",
        )
        payload = self.client.get(f"/api/live/recording/{rec}/?token={viewer}").json()
        self.assertIn(str(self.question.pk), payload["answered"])
        self.assertIn("results", payload["answered"][str(self.question.pk)])

    def test_control_run_enables_recording(self):
        # The beamer lobby toggle turns on recording on the live run.
        run = self.open_question()
        self.client.force_login(self.owner)
        resp = self.client.post(
            f"/api/runs/{run.pk}/control/",
            {"recording": True},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["recording_token"])
        run.refresh_from_db()
        self.assertTrue(run.recording_token)

    def test_recording_qr_returns_png(self):
        rec = self._start_recording()["recording_token"]
        resp = self.client.get(f"/r/{rec}/qr.png?q={self.question.pk}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/png")

    def test_recording_page_renders(self):
        rec = self._start_recording()["recording_token"]
        resp = self.client.get(f"/r/{rec}/?q={self.question.pk}")
        self.assertEqual(resp.status_code, 200)

    def test_results_split_onsite_recording(self):
        # MR B: results carry the on-site/recording split + combined total.
        from live.results import run_results

        run = self.open_question()
        run.enable_recording()
        onsite_token = self.join()
        self.vote(onsite_token, options=[self.correct.pk])  # on-site
        viewer = ParticipantToken.objects.create(room=self.room)
        rec_vote = Vote.objects.create(
            run=run, question=self.question, token=viewer,
            source=Vote.Source.RECORDING,
        )
        rec_vote.options.set([self.wrong])
        data = run_results(run)
        self.assertEqual(data["recording_votes"], 1)
        q = data["questions"][0]
        self.assertEqual(q["votes_recording"], 1)
        by_text = {resolve_translated_text(o["text"]): o for o in q["options"]}
        self.assertEqual((by_text["4"]["onsite"], by_text["4"]["recording"]), (1, 0))
        self.assertEqual((by_text["5"]["onsite"], by_text["5"]["recording"]), (0, 1))
        self.assertEqual(by_text["5"]["count"], 1)

    def test_csv_has_source_columns(self):
        self.open_question()
        self.client.force_login(self.owner)
        body = self.client.get(
            f"/api/question-sets/{self.question_set.pk}/results.csv"
        ).content.decode("utf-8")
        self.assertIn("vor_ort", body.splitlines()[0])
        self.assertIn("aufzeichnung", body.splitlines()[0])


class DeterministicActiveRunTests(LiveTestCase):
    def test_active_run_prefers_newest_on_created_at_tie(self):
        # Two unfinished runs in the same room (different sets — allowed by
        # the per-set constraint). With identical created_at, selection must
        # fall back to -id, i.e. the newest run wins deterministically.
        set2 = QuestionSet.objects.create(room=self.room, title="Termin 2")
        run_a = Run.objects.create(
            question_set=self.question_set, phase=Run.Phase.OPEN
        )
        run_b = Run.objects.create(question_set=set2, phase=Run.Phase.OPEN)
        ts = timezone.now()
        Run.objects.filter(pk__in=[run_a.pk, run_b.pk]).update(created_at=ts)

        self.assertEqual(active_run(self.room).pk, max(run_a.pk, run_b.pk))


class OneActiveRunPerRoomTests(LiveTestCase):
    def login(self):
        self.client.force_login(self.owner)

    def _open_run_on(self, question_set):
        return Run.objects.create(
            question_set=question_set, phase=Run.Phase.OPEN
        )

    def _start(self):
        return self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {},
            content_type="application/json",
        ).json()

    def test_start_archives_other_set_run_with_votes(self):
        self.login()
        set2 = QuestionSet.objects.create(room=self.room, title="Termin 2")
        other = self._open_run_on(set2)
        tok = ParticipantToken.objects.create(room=self.room)
        Vote.objects.create(run=other, question=self.question, token=tok)

        resp = self._start()

        other.refresh_from_db()
        self.assertEqual(other.phase, Run.Phase.FINISHED)
        self.assertIsNotNone(other.ended_at)
        self.assertEqual(other.votes.count(), 1)  # archived, not lost
        self.assertEqual(active_run(self.room).pk, resp["run"])

    def test_start_deletes_empty_other_set_run(self):
        self.login()
        set2 = QuestionSet.objects.create(room=self.room, title="Termin 2")
        other = self._open_run_on(set2)

        resp = self._start()

        self.assertFalse(Run.objects.filter(pk=other.pk).exists())
        self.assertEqual(active_run(self.room).pk, resp["run"])

    def test_start_archives_other_set_run_with_recording_token(self):
        # Regression: a run with a minted recording token but no live votes
        # yet must be archived, not deleted — deleting it would destroy the
        # shared /r/<token>/ link and lose future async recording votes.
        self.login()
        set2 = QuestionSet.objects.create(room=self.room, title="Termin 2")
        other = self._open_run_on(set2)
        token = other.enable_recording()
        self.assertEqual(other.votes.count(), 0)

        resp = self._start()

        other.refresh_from_db()
        self.assertEqual(other.phase, Run.Phase.FINISHED)
        self.assertIsNotNone(other.ended_at)
        self.assertEqual(other.recording_token, token)
        self.assertEqual(active_run(self.room).pk, resp["run"])

    def test_target_set_own_run_untouched(self):
        # Regression: the target set's own unfinished run must be reused,
        # never swept by the cross-set cleanup.
        self.login()
        own = self._open_run_on(self.question_set)

        resp = self._start()

        self.assertEqual(resp["run"], own.pk)
        self.assertTrue(Run.objects.filter(pk=own.pk).exists())


class PriorityScoreModelTests(LiveTestCase):
    def test_kind_and_model_exist(self):
        from .models import PriorityScore

        q = Question.objects.create(
            question_set=self.question_set,
            kind=Question.Kind.PRIORITIES,
            text="<p>Verteile 100 Punkte</p>",
            position=1,
        )
        opt = AnswerOption.objects.create(question=q, text="A", position=0)
        run = Run.objects.create(
            question_set=self.question_set, phase=Run.Phase.OPEN, active_question=q
        )
        tok = ParticipantToken.objects.create(room=self.room)
        vote = Vote.objects.create(run=run, question=q, token=tok)
        score = PriorityScore.objects.create(vote=vote, option=opt, points=40)

        self.assertEqual(vote.priority_scores.get().points, 40)
        self.assertEqual(score.option, opt)


class OrderingResponseModelTests(LiveTestCase):
    def test_kind_and_model_exist(self):
        from .models import OrderingResponse

        q = Question.objects.create(
            question_set=self.question_set,
            kind=Question.Kind.ORDERING,
            text="<p>Bring in order</p>",
            position=1,
        )
        opt = AnswerOption.objects.create(question=q, text="A", position=0)
        run = Run.objects.create(
            question_set=self.question_set, phase=Run.Phase.OPEN, active_question=q
        )
        tok = ParticipantToken.objects.create(room=self.room)
        vote = Vote.objects.create(run=run, question=q, token=tok)
        resp = OrderingResponse.objects.create(vote=vote, option=opt, position=0)

        self.assertEqual(vote.ordering_responses.get().position, 0)
        self.assertEqual(resp.option, opt)

    def test_unique_per_vote_option(self):
        from django.db import IntegrityError

        from .models import OrderingResponse

        q = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.ORDERING,
            text="<p>O</p>", position=1,
        )
        opt = AnswerOption.objects.create(question=q, text="A", position=0)
        run = Run.objects.create(question_set=self.question_set, phase=Run.Phase.OPEN, active_question=q)
        tok = ParticipantToken.objects.create(room=self.room)
        vote = Vote.objects.create(run=run, question=q, token=tok)
        OrderingResponse.objects.create(vote=vote, option=opt, position=0)
        with self.assertRaises(IntegrityError):
            OrderingResponse.objects.create(vote=vote, option=opt, position=1)


class PrioritiesVoteTests(LiveTestCase):
    def setUp(self):
        super().setUp()
        self.pq = Question.objects.create(
            question_set=self.question_set,
            kind=Question.Kind.PRIORITIES,
            text="<p>Verteile</p>",
            position=1,
        )
        self.oa = AnswerOption.objects.create(question=self.pq, text="A", position=0)
        self.ob = AnswerOption.objects.create(question=self.pq, text="B", position=1)
        self.oc = AnswerOption.objects.create(question=self.pq, text="C", position=2)
        self.run = Run.objects.create(
            question_set=self.question_set,
            phase=Run.Phase.OPEN,
            active_question=self.pq,
        )

    def _vote(self, token, points, **extra):
        return self.client.post(
            f"/api/live/rooms/{self.room.code}/vote/",
            {"token": token, "points": points, **extra},
            content_type="application/json",
        )

    def test_valid_submission_stores_all_options_incl_zero(self):
        token = self.join()
        resp = self._vote(token, {str(self.oa.pk): 60, str(self.ob.pk): 40})
        self.assertEqual(resp.status_code, 201)
        vote = self.run.votes.get(token__key=token)
        scores = {s.option_id: s.points for s in vote.priority_scores.all()}
        self.assertEqual(scores, {self.oa.pk: 60, self.ob.pk: 40, self.oc.pk: 0})

    def test_partial_under_100_allowed(self):
        token = self.join()
        self.assertEqual(self._vote(token, {str(self.oa.pk): 30}).status_code, 201)

    def test_sum_over_100_rejected(self):
        token = self.join()
        resp = self._vote(token, {str(self.oa.pk): 60, str(self.ob.pk): 50})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.run.votes.count(), 0)

    def test_negative_or_too_large_rejected(self):
        token = self.join()
        self.assertEqual(self._vote(token, {str(self.oa.pk): -1}).status_code, 400)
        self.assertEqual(self._vote(token, {str(self.oa.pk): 101}).status_code, 400)

    def test_unknown_option_rejected(self):
        token = self.join()
        other = AnswerOption.objects.create(question=self.question, text="X", position=9)
        self.assertEqual(self._vote(token, {str(other.pk): 10}).status_code, 400)

    def test_double_vote_rejected(self):
        token = self.join()
        self.assertEqual(self._vote(token, {str(self.oa.pk): 10}).status_code, 201)
        self.assertEqual(self._vote(token, {str(self.oa.pk): 20}).status_code, 409)

    def test_self_paced_submission(self):
        self.run.mode = Run.Mode.SELF_PACED
        self.run.save(update_fields=["mode"])
        token = self.join()
        resp = self._vote(token, {str(self.oa.pk): 50}, question=self.pq.pk)
        self.assertEqual(resp.status_code, 201)


class OrderingVoteTests(LiveTestCase):
    def setUp(self):
        super().setUp()
        self.oq = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.ORDERING,
            text="<p>Order</p>", position=1,
        )
        self.oa = AnswerOption.objects.create(question=self.oq, text="A", position=0)
        self.ob = AnswerOption.objects.create(question=self.oq, text="B", position=1)
        self.oc = AnswerOption.objects.create(question=self.oq, text="C", position=2)
        self.run = Run.objects.create(
            question_set=self.question_set, phase=Run.Phase.OPEN, active_question=self.oq,
        )

    def _vote(self, token, order, **extra):
        return self.client.post(
            f"/api/live/rooms/{self.room.code}/vote/",
            {"token": token, "order": order, **extra},
            content_type="application/json",
        )

    def test_valid_submission_stores_positions(self):
        token = self.join()
        resp = self._vote(token, [self.ob.pk, self.oa.pk, self.oc.pk])
        self.assertEqual(resp.status_code, 201)
        vote = self.run.votes.get(token__key=token)
        pos = {r.option_id: r.position for r in vote.ordering_responses.all()}
        self.assertEqual(pos, {self.ob.pk: 0, self.oa.pk: 1, self.oc.pk: 2})

    def test_incomplete_order_rejected(self):
        token = self.join()
        resp = self._vote(token, [self.oa.pk, self.ob.pk])  # missing C
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.run.votes.count(), 0)

    def test_duplicate_in_order_rejected(self):
        token = self.join()
        resp = self._vote(token, [self.oa.pk, self.oa.pk, self.ob.pk])
        self.assertEqual(resp.status_code, 400)

    def test_unknown_option_rejected(self):
        token = self.join()
        other = AnswerOption.objects.create(question=self.question, text="X", position=9)
        resp = self._vote(token, [self.oa.pk, self.ob.pk, other.pk])
        self.assertEqual(resp.status_code, 400)

    def test_double_vote_rejected(self):
        token = self.join()
        self.assertEqual(self._vote(token, [self.oa.pk, self.ob.pk, self.oc.pk]).status_code, 201)
        self.assertEqual(self._vote(token, [self.oc.pk, self.ob.pk, self.oa.pk]).status_code, 409)

    def test_self_paced_submission(self):
        self.run.mode = Run.Mode.SELF_PACED
        self.run.save(update_fields=["mode"])
        token = self.join()
        resp = self._vote(token, [self.oa.pk, self.ob.pk, self.oc.pk], question=self.oq.pk)
        self.assertEqual(resp.status_code, 201)

    def test_recording_vote_stores_ordering(self):
        self.run.enable_recording()
        token = self.join()
        resp = self.client.post(
            f"/api/live/recording/{self.run.recording_token}/vote/",
            {"token": token, "question": self.oq.pk,
             "order": [self.oa.pk, self.ob.pk, self.oc.pk]},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIn("ordering", resp.json())


class OrderingStatsTests(LiveTestCase):
    def setUp(self):
        super().setUp()
        from .models import OrderingResponse
        self.OrderingResponse = OrderingResponse
        self.oq = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.ORDERING,
            text="<p>O</p>", position=1,
        )
        self.oa = AnswerOption.objects.create(question=self.oq, text="A", position=0)
        self.ob = AnswerOption.objects.create(question=self.oq, text="B", position=1)
        self.oc = AnswerOption.objects.create(question=self.oq, text="C", position=2)
        self.run = Run.objects.create(
            question_set=self.question_set, phase=Run.Phase.CLOSED, active_question=self.oq,
        )

    def _submit(self, order):  # order = list of options in the participant's sequence
        tok = ParticipantToken.objects.create(room=self.room)
        vote = Vote.objects.create(run=self.run, question=self.oq, token=tok)
        self.OrderingResponse.objects.bulk_create(
            [self.OrderingResponse(vote=vote, option=opt, position=idx)
             for idx, opt in enumerate(order)]
        )

    def test_correct_rates_and_full_rate(self):
        from .results import ordering_stats
        self._submit([self.oa, self.ob, self.oc])          # fully correct
        self._submit([self.oa, self.oc, self.ob])          # A right, B/C wrong
        stats = ordering_stats(self.run, self.oq)
        items = {it["id"]: it for it in stats["items"]}
        self.assertEqual([it["correct_position"] for it in stats["items"]], [1, 2, 3])
        self.assertEqual(items[self.oa.pk]["correct_rate"], 100.0)   # 2/2
        self.assertEqual(items[self.ob.pk]["correct_rate"], 50.0)    # 1/2
        self.assertEqual(items[self.oc.pk]["correct_rate"], 50.0)    # 1/2
        self.assertEqual(stats["full_correct_rate"], 50.0)           # 1/2 fully correct
        self.assertEqual(stats["n"], 2)

    def test_empty_run(self):
        from .results import ordering_stats
        stats = ordering_stats(self.run, self.oq)
        self.assertEqual(stats["n"], 0)
        self.assertEqual(stats["full_correct_rate"], 0)
        self.assertEqual([it["correct_rate"] for it in stats["items"]], [0, 0, 0])

    def test_run_results_includes_ordering(self):
        from .results import run_results
        self._submit([self.oa, self.ob, self.oc])
        item = next(q for q in run_results(self.run)["questions"] if q["id"] == self.oq.pk)
        self.assertEqual(item["kind"], "ordering")
        self.assertIn("ordering", item)

    def test_presenter_and_participant_payloads(self):
        from .state import build_payloads
        # Participant results are gated per-set (v2 option); enable them so
        # the participant branch is exercised too, mirroring
        # PriorityRecordingAndResetTests.test_participant_results_when_enabled.
        self.question_set.show_results_to_participants = True
        self.question_set.save(update_fields=["show_results_to_participants"])
        self.run.phase = Run.Phase.RESULTS
        self.run.save(update_fields=["phase"])
        self._submit([self.oa, self.ob, self.oc])
        payloads = build_payloads(self.room)
        self.assertIn("ordering", payloads["presenter"])
        self.assertIn("ordering", payloads["participant"])

    def test_links_full_correct_single_chain(self):
        from .results import ordering_stats
        self._submit([self.oa, self.ob, self.oc])
        self._submit([self.oa, self.ob, self.oc])
        stats = ordering_stats(self.run, self.oq)
        self.assertEqual(
            [(l["from"], l["to"], l["rate"]) for l in stats["links"]],
            [(self.oa.pk, self.ob.pk, 100.0), (self.ob.pk, self.oc.pk, 100.0)],
        )
        self.assertEqual(stats["chains"], [{"start": 0, "end": 2, "rate": 100.0}])

    def test_links_partial_swap(self):
        from .results import ordering_stats
        self._submit([self.oa, self.ob, self.oc])   # A,B,C
        self._submit([self.ob, self.oa, self.oc])   # B,A,C (A/B swapped)
        stats = ordering_stats(self.run, self.oq)
        # A->B adjacency holds only in submission 1; B->C only in submission 1.
        self.assertEqual([l["rate"] for l in stats["links"]], [50.0, 50.0])
        # Both links >= 50 -> one chain over all items; whole-run correct = 1/2.
        self.assertEqual(stats["chains"], [{"start": 0, "end": 2, "rate": 50.0}])

    def test_chains_split_on_weak_link(self):
        from .results import ordering_stats
        od = AnswerOption.objects.create(question=self.oq, text="D", position=3)
        a, b, c, d = self.oa, self.ob, self.oc, od
        self._submit([a, b, c, d])   # all links hold
        self._submit([a, b, d, c])   # A->B holds; B->C, C->D fail
        self._submit([b, a, c, d])   # A->B fails; B->C fails; C->D holds
        stats = ordering_stats(self.run, self.oq)
        rates = [round(l["rate"], 1) for l in stats["links"]]
        self.assertEqual(rates, [66.7, 33.3, 66.7])  # link1 < 50 breaks the run
        self.assertEqual(
            [(ch["start"], ch["end"]) for ch in stats["chains"]],
            [(0, 1), (2, 3)],
        )

    def test_empty_run_links_chains(self):
        from .results import ordering_stats
        stats = ordering_stats(self.run, self.oq)
        self.assertEqual([l["rate"] for l in stats["links"]], [0, 0])
        self.assertEqual(stats["chains"], [])


class PriorityStatsTests(LiveTestCase):
    def setUp(self):
        super().setUp()
        from .models import PriorityScore

        self.PriorityScore = PriorityScore
        self.pq = Question.objects.create(
            question_set=self.question_set,
            kind=Question.Kind.PRIORITIES,
            text="<p>P</p>",
            position=1,
        )
        self.oa = AnswerOption.objects.create(question=self.pq, text="A", position=0)
        self.ob = AnswerOption.objects.create(question=self.pq, text="B", position=1)
        self.run = Run.objects.create(
            question_set=self.question_set,
            phase=Run.Phase.CLOSED,
            active_question=self.pq,
        )

    def _submit(self, a, b):
        tok = ParticipantToken.objects.create(room=self.room)
        vote = Vote.objects.create(run=self.run, question=self.pq, token=tok)
        self.PriorityScore.objects.bulk_create(
            [
                self.PriorityScore(vote=vote, option=self.oa, points=a),
                self.PriorityScore(vote=vote, option=self.ob, points=b),
            ]
        )

    def test_avg_min_max_and_sorting(self):
        from .results import priority_stats

        self._submit(80, 20)
        self._submit(40, 0)
        stats = priority_stats(self.run, self.pq)
        by_id = {s["id"]: s for s in stats}
        self.assertEqual(by_id[self.oa.pk]["avg"], 60.0)
        self.assertEqual(by_id[self.oa.pk]["min"], 40)
        self.assertEqual(by_id[self.oa.pk]["max"], 80)
        self.assertEqual(by_id[self.oa.pk]["n"], 2)
        self.assertEqual(by_id[self.ob.pk]["avg"], 10.0)
        self.assertEqual(by_id[self.ob.pk]["min"], 0)
        self.assertEqual(stats[0]["id"], self.oa.pk)  # sorted by avg desc

    def test_run_results_includes_priorities(self):
        from .results import run_results

        self._submit(70, 30)
        item = next(
            i for i in run_results(self.run)["questions"] if i["id"] == self.pq.pk
        )
        self.assertIn("priorities", item)
        self.assertNotIn("options", item)


class PriorityPayloadTests(LiveTestCase):
    def setUp(self):
        super().setUp()
        from .models import PriorityScore

        self.PriorityScore = PriorityScore
        self.pq = Question.objects.create(
            question_set=self.question_set,
            kind=Question.Kind.PRIORITIES,
            text="<p>P</p>",
            position=1,
        )
        self.oa = AnswerOption.objects.create(question=self.pq, text="A", position=0)
        self.ob = AnswerOption.objects.create(question=self.pq, text="B", position=1)

    def _run(self, phase):
        return Run.objects.create(
            question_set=self.question_set, phase=phase, active_question=self.pq
        )

    def _score(self, run, a, b):
        tok = ParticipantToken.objects.create(room=self.room)
        vote = Vote.objects.create(run=run, question=self.pq, token=tok)
        self.PriorityScore.objects.bulk_create(
            [
                self.PriorityScore(vote=vote, option=self.oa, points=a),
                self.PriorityScore(vote=vote, option=self.ob, points=b),
            ]
        )

    def test_open_payload_lists_options(self):
        self._run(Run.Phase.OPEN)
        q = build_payloads(self.room)["participant"]["question"]
        self.assertEqual(q["kind"], "priorities")
        self.assertEqual(len(q["options"]), 2)

    def test_presenter_results_has_priority_stats(self):
        run = self._run(Run.Phase.CLOSED)
        self._score(run, 70, 30)
        presenter = build_payloads(self.room)["presenter"]
        self.assertIn("priorities", presenter)
        self.assertNotIn("results", presenter)

    def test_participant_results_when_enabled(self):
        self.question_set.show_results_to_participants = True
        self.question_set.save(update_fields=["show_results_to_participants"])
        run = self._run(Run.Phase.RESULTS)
        self._score(run, 70, 30)
        participant = build_payloads(self.room)["participant"]
        self.assertIn("priorities", participant)


class PriorityCsvTests(LiveTestCase):
    def test_csv_has_priority_avg_min_max(self):
        from .models import PriorityScore

        pq = Question.objects.create(
            question_set=self.question_set,
            kind=Question.Kind.PRIORITIES,
            text="<p>P</p>",
            position=1,
        )
        oa = AnswerOption.objects.create(question=pq, text="Alpha", position=0)
        ob = AnswerOption.objects.create(question=pq, text="Beta", position=1)
        run = Run.objects.create(
            question_set=self.question_set, phase=Run.Phase.CLOSED, active_question=pq
        )
        for a, b in ((80, 20), (40, 0)):
            tok = ParticipantToken.objects.create(room=self.room)
            vote = Vote.objects.create(run=run, question=pq, token=tok)
            PriorityScore.objects.bulk_create(
                [
                    PriorityScore(vote=vote, option=oa, points=a),
                    PriorityScore(vote=vote, option=ob, points=b),
                ]
            )
        self.client.force_login(self.owner)
        response = self.client.get(
            f"/api/question-sets/{self.question_set.pk}/results.csv"
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode("utf-8-sig")
        # Alpha: avg 60.0, min 40, max 80  → stimmen;vor_ort;aufzeichnung
        self.assertIn("Alpha;;60.0;40;80;", body)
        self.assertNotIn("{", body)


class PriorityRecordingAndResetTests(LiveTestCase):
    def login(self):
        self.client.force_login(self.owner)

    def test_start_without_recording_clears_stale_token(self):
        # Bugfix: a resumed run must not keep a recording token when the new
        # start did not request recording.
        self.login()
        run = Run.objects.create(
            question_set=self.question_set, phase=Run.Phase.LOBBY
        )
        run.enable_recording()
        self.assertTrue(run.recording_token)
        self.client.post(
            f"/api/question-sets/{self.question_set.pk}/start-run/",
            {}, content_type="application/json",
        )
        run.refresh_from_db()
        self.assertIsNone(run.recording_token)

    def test_recording_vote_stores_priorities(self):
        pq = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.PRIORITIES,
            text="<p>P</p>", position=1,
        )
        oa = AnswerOption.objects.create(question=pq, text="A", position=0)
        ob = AnswerOption.objects.create(question=pq, text="B", position=1)
        run = Run.objects.create(
            question_set=self.question_set, phase=Run.Phase.OPEN, active_question=pq
        )
        run.enable_recording()
        token = self.join()
        resp = self.client.post(
            f"/api/live/recording/{run.recording_token}/vote/",
            {"token": token, "question": pq.pk,
             "points": {str(oa.pk): 70, str(ob.pk): 30}},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIn("priorities", resp.json())
        vote = run.votes.get(token__key=token, source=Vote.Source.RECORDING)
        self.assertEqual(
            {s.option_id: s.points for s in vote.priority_scores.all()},
            {oa.pk: 70, ob.pk: 30},
        )


class OrderingPayloadTests(LiveTestCase):
    def test_payload_shuffles_and_omits_position(self):
        from .state import question_payload

        q = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.ORDERING,
            text="<p>O</p>", position=1, shuffle_options=False,
        )
        # 8 options → identity ordering has 1/8! chance; assert not-identity
        # across a few seeds to prove shuffling is active for ordering.
        opts = [AnswerOption.objects.create(question=q, text=f"O{i}", position=i)
                for i in range(8)]
        payload = question_payload(q, shuffle_seed=1)
        ids = [o["id"] for o in payload["options"]]
        self.assertEqual(sorted(ids), sorted(o.pk for o in opts))
        self.assertNotIn("position", payload["options"][0])
        self.assertNotEqual(ids, [o.pk for o in opts])  # shuffled vs authored order


class OrderingCsvTests(LiveTestCase):
    def test_csv_has_ordering_rows(self):
        from .models import OrderingResponse

        oq = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.ORDERING,
            text="<p>Order</p>", position=0,
        )
        oa = AnswerOption.objects.create(question=oq, text="Erst", position=0)
        ob = AnswerOption.objects.create(question=oq, text="Dann", position=1)
        run = Run.objects.create(question_set=self.question_set, phase=Run.Phase.CLOSED)
        tok = ParticipantToken.objects.create(room=self.room)
        vote = Vote.objects.create(run=run, question=oq, token=tok)
        OrderingResponse.objects.bulk_create([
            OrderingResponse(vote=vote, option=oa, position=0),
            OrderingResponse(vote=vote, option=ob, position=1),
        ])
        self.client.force_login(self.owner)
        resp = self.client.get(f"/api/question-sets/{self.question_set.pk}/results.csv")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8")
        self.assertIn("Erst", body)
        self.assertIn("Dann", body)
        # full-correct summary row present
        self.assertIn("komplett richtig", body.lower())


class QuestionPreviewTests(LiveTestCase):
    """Owner-only interactive question preview reusing the participant page (#74)."""

    def _make_question(self):
        q = Question.objects.create(
            question_set=self.question_set, kind=Question.Kind.SINGLE_CHOICE,
            text_de="<p>Welche Farbe?</p>", position=1,
        )
        AnswerOption.objects.create(question=q, text_de="Blau", position=0)
        AnswerOption.objects.create(question=q, text_de="Rot", position=1)
        return q

    def test_preview_renders_for_owner(self):
        self.client.force_login(self.owner)
        q = self._make_question()
        resp = self.client.get(f"/question-preview/{q.pk}/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # The question + option texts ride along in the embedded preview state.
        self.assertIn("Welche Farbe?", body)
        self.assertIn("Blau", body)
        self.assertIn("Rot", body)
        self.assertIn("preview-state", body)  # seeded JSON present

    def test_preview_forbidden_for_non_owner(self):
        other = User.objects.create_user(username="mallory")
        self.client.force_login(other)
        q = self._make_question()
        self.assertEqual(self.client.get(f"/question-preview/{q.pk}/").status_code, 404)

    def test_preview_unknown_question_404(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get("/question-preview/99999/").status_code, 404)

    def test_preview_is_frameable_by_own_app(self):
        # #74: the editor embeds this in an iframe — allow 'self' + the SPA via
        # CSP frame-ancestors, and drop the blanket X-Frame-Options: DENY.
        self.client.force_login(self.owner)
        q = self._make_question()
        resp = self.client.get(f"/question-preview/{q.pk}/")
        self.assertIn("frame-ancestors", resp.headers.get("Content-Security-Policy", ""))
        self.assertNotIn("X-Frame-Options", resp.headers)
