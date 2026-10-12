# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Mindmap stage 3, part 2: AI colouring by criteria — classification pass,
validity (fingerprint, renames), payload visibility, endpoint, results/CSV.
The LLM is always faked (no network); the pass runs synchronously."""
import json
from unittest.mock import patch

from basicbar_integrations import ai as ai_module
from django.test import override_settings

from . import ai_mindmap_criteria as crit
from . import mindmap
from . import tests as base
from .models import MindmapNode, MindmapPhase, ParticipantToken, Run
from .results import run_results
from .state import build_payloads
from .test_ai_mindmap import MindmapAiTestCase

CRITERIA = [{"de": "Erneuerbar", "en": "Renewable"}, {"de": "Infrastruktur", "en": ""}]


class FakeLLM:
    """Records every call; answers with ``answer(terms)`` → {id: number|None}
    (criterion numbers from 1) or raises/returns what it is told."""

    def __init__(self, answer=None, reply=None, error=None, during=None):
        self.calls = []
        self.answer = answer or (lambda terms: {})
        self.reply = reply
        self.error = error
        self.during = during

    def terms(self, index=-1):
        user = self.calls[index][1]
        return json.loads(user.split("Begriffe:\n", 1)[1])

    def texts(self, index=-1):
        return sorted(term["text"] for term in self.terms(index))

    def __call__(self, system, user):
        self.calls.append((system, user))
        if self.during:
            self.during()
        if self.error:
            raise self.error
        if self.reply is not None:
            return self.reply
        terms = json.loads(user.split("Begriffe:\n", 1)[1])
        numbers = self.answer(terms)
        return {"assignments": [
            {"id": term["id"], "criterion": numbers.get(term["text"])} for term in terms
        ]}


def by_text(mapping):
    return lambda terms: mapping


class CriteriaTestCase(MindmapAiTestCase):
    def setUp(self):
        super().setUp()
        self.mq.mindmap_criteria = CRITERIA
        self.mq.save()
        self.key = (self.run.pk, self.mq.pk)
        self.addCleanup(crit._errors.clear)
        self.addCleanup(crit._running.clear)
        self.addCleanup(crit._dirty.clear)
        self.addCleanup(crit._omissions.clear)
        self.addCleanup(crit._retried.clear)
        # Never start real worker threads or timers in tests.
        self.submit = patch.object(crit._executor, "submit").start()
        self.timer = patch.object(crit, "_timer").start()
        self.addCleanup(patch.stopall)

    def classify(self, llm=None, **mapping):
        llm = llm or FakeLLM(by_text(mapping))
        with patch("live.ai_mindmap_criteria._broadcast"):
            more = crit.classify_pass(self.run.pk, self.mq.pk, self.room.pk, chat_json=llm)
        self.llm = llm
        return more

    def stored(self, node_id):
        self.mq.refresh_from_db()
        return crit.valid_assignments(self.run, self.mq).get(node_id, "unclassified")

    def activate(self, on=True):
        MindmapPhase.objects.update_or_create(
            run=self.run, question=self.mq, defaults={"ai_criteria_active": on}
        )

    def find(self, nodes, text):
        for node in nodes:
            if node["text"] == text:
                return node
            found = self.find(node["children"], text)
            if found:
                return found
        return None


class ClassifyPassTests(CriteriaTestCase):
    def test_classifies_visible_terms_and_stores_them(self):
        more = self.classify(Wind=1, Windkraft=1, Speicher=2)
        self.assertFalse(more)
        self.assertEqual(
            self.llm.texts(), ["Energy", "Solar", "Speicher", "Wind", "Windkraft"]
        )  # hidden "Spam" never sent
        self.assertEqual(self.stored(self.wind), 0)
        self.assertEqual(self.stored(self.speicher), 1)
        self.assertIsNone(self.stored(self.solar))  # classified: none fits
        self.assertEqual(self.stored(self.spam), "unclassified")

    def test_prompt_content_and_no_tokens(self):
        self.contribute("Rotor", parent=self.wind)
        self.classify()
        system, user = self.llm.calls[0]
        for token in ParticipantToken.objects.values_list("key", flat=True):
            self.assertNotIn(token, system + user)
        self.assertIn("Energiewende", user)  # question context
        self.assertIn("Erneuerbar / Renewable", user)
        self.assertIn('"nr": 2', user)
        rotor = next(t for t in self.llm.terms() if t["text"] == "Rotor")
        self.assertEqual(rotor["path"], "Wind › Rotor")
        self.assertNotIn("key", rotor)
        self.assertIn("höchstens ein Kriterium", system)

    def test_incremental_only_new_and_renamed_terms_sent(self):
        self.classify(Wind=1)
        self.contribute("Geothermie")
        self.owner_mod("rename", node=self.solar, text="Solarenergie")
        self.classify(Solarenergie=1)
        self.assertEqual(self.llm.texts(), ["Geothermie", "Solarenergie"])
        self.assertEqual(self.stored(self.solar), 0)
        self.assertEqual(self.stored(self.wind), 0)  # kept
        # Nothing left: no LLM call at all.
        llm = FakeLLM()
        self.classify(llm)
        self.assertEqual(llm.calls, [])

    def test_criteria_change_invalidates_everything(self):
        self.classify(Wind=1)
        self.mq.mindmap_criteria = [{"de": "Neu", "en": ""}]
        self.mq.save()
        self.assertEqual(self.stored(self.wind), "unclassified")
        self.classify(Wind=1)
        self.assertEqual(len(self.llm.terms()), 5)
        self.assertEqual(self.stored(self.wind), 0)

    def test_translation_only_change_keeps_classification(self):
        self.classify(Wind=1)
        self.mq.mindmap_criteria = [{**CRITERIA[0], "en": "Renewables"}, CRITERIA[1]]
        self.mq.save()
        self.assertEqual(self.stored(self.wind), 0)

    def test_stale_write_guarded_when_renamed_during_call(self):
        def rename():
            mindmap.rename_node(self.run, self.mq, self.solar, "Photovoltaik")

        self.classify(FakeLLM(by_text({"Solar": 1, "Wind": 2}), during=rename))
        self.assertEqual(self.stored(self.solar), "unclassified")
        self.assertEqual(self.stored(self.wind), 1)
        self.classify(Photovoltaik=1)
        self.assertEqual(self.llm.texts(), ["Photovoltaik"])

    def test_criteria_changed_during_call_writes_nothing(self):
        def change():
            self.mq.mindmap_criteria = [{"de": "Anders", "en": ""}]
            self.mq.save()

        self.classify(FakeLLM(by_text({"Wind": 1}), during=change))
        self.assertEqual(self.stored(self.wind), "unclassified")

    def test_merge_keeps_target_assignment(self):
        self.classify(Wind=1, Windkraft=2)
        self.owner_mod("merge", source=self.windkraft, target=self.wind)
        self.assertEqual(self.stored(self.wind), 0)
        llm = FakeLLM()
        self.classify(llm)
        self.assertEqual(llm.calls, [])

    def test_merge_into_unclassified_target_classifies_it(self):
        self.classify(Windkraft=2)
        new = self.owner_mod("add", parent=None, text="Wind-Energie").json()["node_id"]
        self.owner_mod("merge", source=self.windkraft, target=new)
        self.classify(**{"Wind-Energie": 1})
        self.assertEqual(self.llm.texts(), ["Wind-Energie"])
        self.assertEqual(self.stored(new), 0)

    def test_omitted_terms_retried_then_stored_as_none(self):
        only_wind = FakeLLM(reply={"assignments": [{"id": self.wind, "criterion": 1}]})
        self.assertTrue(self.classify(only_wind))  # omitted terms: retry
        self.assertEqual(self.stored(self.wind), 0)
        self.assertEqual(self.stored(self.solar), "unclassified")
        self.assertFalse(self.classify(FakeLLM(by_text({"Solar": 1}))))
        self.assertEqual(self.llm.texts(), ["Energy", "Solar", "Speicher", "Windkraft"])
        self.assertEqual(self.stored(self.solar), 0)
        self.assertIsNone(self.stored(self.energy))  # answered: none fits
        # A term left out twice is stored as "none" and not re-sent.
        self.classify(FakeLLM(reply={"assignments": [{"id": self.wind, "criterion": 1}]}))
        self.contribute("Geothermie")
        self.contribute("Biogas")
        geo = MindmapNode.objects.get(run=self.run, text="Geothermie").pk
        self.classify(FakeLLM(reply={"assignments": [{"id": geo, "criterion": 2}]}))
        biogas = MindmapNode.objects.get(text="Biogas").pk
        self.assertEqual(self.stored(biogas), "unclassified")  # omitted once
        self.contribute("Wasserstoff")
        h2 = MindmapNode.objects.get(text="Wasserstoff").pk
        self.classify(FakeLLM(reply={"assignments": [{"id": h2, "criterion": 1}]}))
        self.assertEqual(self.llm.texts(), ["Biogas", "Wasserstoff"])
        self.assertIsNone(self.stored(biogas))  # omitted twice: none
        llm = FakeLLM()
        self.classify(llm)
        self.assertEqual(llm.calls, [])

    def test_omitted_terms_do_not_starve_fresh_ones(self):
        with patch.object(crit, "BATCH_MAX", 2):
            # Batch 1: Wind + Windkraft; the model only answers Wind.
            self.classify(FakeLLM(reply={"assignments": [{"id": self.wind, "criterion": 1}]}))
            self.classify(Solar=1, Energy=1)
            # The omitted Windkraft goes behind the fresh terms.
            self.assertEqual(self.llm.texts(), ["Energy", "Solar"])
            self.classify()
            self.assertEqual(self.llm.texts(), ["Speicher", "Windkraft"])

    def test_invalid_entries_dropped(self):
        reply = {"assignments": [
            {"id": self.wind, "criterion": 3},  # out of range
            {"id": str(self.solar), "criterion": 1},  # string id
            {"id": self.energy, "criterion": True},  # bool
            {"id": 999999, "criterion": 1},  # not sent
            {"id": self.speicher, "criterion": 2},
            {"id": self.speicher, "criterion": 1},  # second entry ignored
        ]}
        self.classify(FakeLLM(reply=reply))
        self.assertEqual(self.stored(self.wind), "unclassified")  # retried later
        self.assertEqual(self.stored(self.speicher), 1)

    def test_batches_capped(self):
        with patch.object(crit, "BATCH_MAX", 2):
            self.assertTrue(self.classify())
            self.assertEqual(len(self.llm.terms()), 2)
            self.assertTrue(self.classify())
            self.assertFalse(self.classify())  # last one: nothing remains
        self.assertEqual(len(self.llm.terms()), 1)

    def test_ai_error_stored_and_cleared_on_success(self):
        self.classify(FakeLLM(error=ai_module.AIError("timeout")))
        self.assertEqual(crit.get_error(*self.key), crit.ERROR_AI)
        self.timer.assert_called_once()
        self.assertEqual(self.timer.call_args[0][0], crit.RETRY_DELAY)
        self.classify(FakeLLM(error=ai_module.AIError("timeout")))
        self.timer.assert_called_once()  # only one automatic retry
        self.assertEqual(self.stored(self.wind), "unclassified")
        self.activate()
        payload = build_payloads(self.room)["presenter"]["mindmap"]["criteria"]
        self.assertEqual(payload["error"], crit.ERROR_AI)
        self.classify(FakeLLM(reply={"oops": 1}))
        self.assertEqual(crit.get_error(*self.key), crit.ERROR_REPLY)
        self.classify(FakeLLM(reply={"assignments": []}))
        self.assertEqual(crit.get_error(*self.key), crit.ERROR_REPLY)
        self.classify(Wind=1)
        self.assertIsNone(crit.get_error(*self.key))
        payload = build_payloads(self.room)["presenter"]["mindmap"]["criteria"]
        self.assertNotIn("error", payload)
        # A success re-arms the automatic retry.
        self.contribute("Geothermie")
        self.classify(FakeLLM(error=ai_module.AIError("x")))
        self.assertEqual(self.timer.call_count, 2)

    @override_settings(**base.AI_ON)
    def test_delayed_retry_schedules(self):
        self.activate()
        crit._delayed_retry(*self.key, self.room.pk)
        self.submit.assert_called_once()

    def test_unexpected_exception_becomes_error_state(self):
        self.activate()
        with patch.object(crit, "_write", side_effect=RuntimeError("db gone")), \
                self.assertLogs("live.ai_mindmap_criteria", level="ERROR"):
            self.assertFalse(self.classify(Wind=1))
        self.assertEqual(crit.get_error(*self.key), crit.ERROR_AI)
        payload = build_payloads(self.room)["presenter"]["mindmap"]["criteria"]
        self.assertEqual(payload["error"], crit.ERROR_AI)

    def test_ai_switch_off_sends_nothing(self):
        self.activate()
        self.mq.wordcloud_ai_enabled = False
        self.mq.save()
        llm = FakeLLM()
        self.assertFalse(self.classify(llm))
        self.assertEqual(llm.calls, [])
        payload = build_payloads(self.room)["presenter"]["mindmap"]
        self.assertFalse(payload["criteria"]["active"])
        self.assertNotIn("criterion", self.find(payload["nodes"], "Wind"))

    @override_settings(**base.AI_OFF)
    def test_ai_not_configured_sends_nothing(self):
        with patch("basicbar_integrations.ai.chat_json") as chat:
            self.assertFalse(crit.classify_pass(self.run.pk, self.mq.pk, self.room.pk))
        chat.assert_not_called()

    def test_no_criteria_no_call(self):
        self.mq.mindmap_criteria = []
        self.mq.save()
        llm = FakeLLM()
        self.assertFalse(self.classify(llm))
        self.assertEqual(llm.calls, [])


class SchedulingTests(CriteriaTestCase):
    @override_settings(**base.AI_ON)
    def test_schedule_only_when_active_and_single_flight(self):
        crit.schedule(*self.key, self.room.pk)
        self.submit.assert_not_called()
        self.activate()
        crit.schedule(*self.key, self.room.pk)
        crit.schedule(*self.key, self.room.pk)
        self.assertEqual(self.submit.call_count, 1)
        self.assertIn(self.key, crit._dirty)

    @override_settings(**base.AI_ON)
    def test_schedule_respects_question_ai_switch(self):
        self.activate()
        self.mq.wordcloud_ai_enabled = False
        self.mq.save()
        crit.schedule(*self.key, self.room.pk)
        self.submit.assert_not_called()
        self.assertFalse(crit.is_active(*self.key))

    @override_settings(**base.AI_ON)
    def test_switch_is_persisted(self):
        self.assertFalse(crit.is_active(*self.key))  # no row = off
        crit.set_active(*self.key, self.room.pk, True)
        phase = MindmapPhase.objects.get(run=self.run, question=self.mq)
        self.assertTrue(phase.ai_criteria_active)
        self.assertEqual(phase.stage, MindmapPhase.Stage.COLLECT)
        # "Restart": in-memory bookkeeping gone, the switch survives.
        crit._running.clear()
        self.assertTrue(crit.is_active(*self.key))
        crit.set_active(*self.key, self.room.pk, False)
        self.assertFalse(crit.is_active(*self.key))

    @override_settings(**base.AI_ON)
    def test_presenter_payload_schedules_waiting_terms(self):
        self.activate()
        build_payloads(self.room)
        self.submit.assert_called_once()
        crit._running.clear()
        self.submit.reset_mock()
        crit._errors[self.key] = crit.ERROR_AI  # no automatic loop on errors
        build_payloads(self.room)
        self.submit.assert_not_called()

    @override_settings(**base.AI_OFF)
    def test_no_schedule_without_ai(self):
        self.activate()
        crit.schedule(*self.key, self.room.pk)
        self.submit.assert_not_called()

    @override_settings(**base.AI_ON)
    def test_tree_changes_schedule(self):
        with patch("live.views.ai_mindmap_criteria.schedule") as schedule:
            self.owner_mod("rename", node=self.solar, text="Sonne")
            self.owner_mod("move", node=self.solar, parent=self.wind)
            self.owner_mod("merge", source=self.energy, target=self.wind)
            self.contribute("Biogas")
            self.client.force_login(self.owner)
            with patch("live.views.broadcast"):
                self.hide(self.run, self.spam, hidden=False)
        self.assertEqual(schedule.call_count, 5)
        schedule.assert_called_with(self.run.pk, self.mq.pk, self.room.pk)

    @override_settings(**base.AI_ON)
    def test_criteria_changed_schedules_active_maps_of_the_question(self):
        self.activate()
        with patch.object(crit, "schedule") as schedule:
            crit.criteria_changed(self.mq.pk)
            crit.criteria_changed(self.mq.pk + 1000)
        schedule.assert_called_once_with(self.run.pk, self.mq.pk, self.room.pk)

    def test_loop_releases_on_exception(self):
        self.activate()
        crit._running.add(self.key)
        with patch.object(crit, "classify_pass", side_effect=KeyboardInterrupt), \
                self.assertRaises(KeyboardInterrupt):
            crit._run_loop(*self.key, self.room.pk)
        self.assertNotIn(self.key, crit._running)

    def test_loop_stops_when_switched_off(self):
        self.activate()
        crit._running.add(self.key)
        calls = []

        def fake_pass(*args):
            calls.append(args)
            crit._dirty.add(self.key)
            self.activate(False)
            return True

        with patch.object(crit, "classify_pass", side_effect=fake_pass), \
                patch.object(crit.time, "sleep"):
            crit._run_loop(*self.key, self.room.pk)
        self.assertEqual(len(calls), 1)
        self.assertNotIn(self.key, crit._running)

    @override_settings(**base.AI_ON)
    def test_loop_runs_trailing_pass_and_releases(self):
        self.activate()
        crit._running.add(self.key)
        calls = []

        def fake_pass(*args):
            calls.append(args)
            if len(calls) == 1:
                crit._dirty.add(self.key)  # a change during the first pass
            return False

        with patch.object(crit, "classify_pass", side_effect=fake_pass), \
                patch.object(crit.time, "sleep"):
            crit._run_loop(*self.key, self.room.pk)
        self.assertEqual(len(calls), 2)
        self.assertNotIn(self.key, crit._running)


class EndpointTests(CriteriaTestCase):
    def criteria(self, body, user=None):
        return self.post("ai-criteria", body, user=user)

    @override_settings(**base.AI_ON)
    def test_activate_saves_criteria_and_reports_state(self):
        response = self.criteria({"active": True, "criteria": ["Orte", {"de": "Flüsse", "en": "Rivers"}]})
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body, {
            "active": True,
            "criteria": [{"de": "Orte", "en": ""}, {"de": "Flüsse", "en": "Rivers"}],
            "pending": 5,
        })
        self.assertTrue(crit.is_active(*self.key))
        self.submit.assert_called_once()
        self.mq.refresh_from_db()
        self.assertEqual(self.mq.mindmap_criteria[1]["en"], "Rivers")
        response = self.criteria({"active": False})
        self.assertEqual(response.json()["active"], False)
        self.assertFalse(crit.is_active(*self.key))

    @override_settings(**base.AI_ON)
    def test_reactivate_clears_error(self):
        self.activate()
        crit._errors[self.key] = crit.ERROR_AI
        self.assertEqual(self.criteria({}).json()["error"], crit.ERROR_AI)
        self.assertNotIn("error", self.criteria({"active": True}).json())

    @override_settings(**base.AI_ON)
    def test_criteria_follow_to_after_question(self):
        after = base.Question.objects.create(
            question_set=self.question_set, kind=base.Question.Kind.MINDMAP,
            text="<p>Nachher</p>", position=5, before_question=self.mq,
        )
        self.criteria({"criteria": ["Orte"]})
        after.refresh_from_db()
        self.assertEqual(after.mindmap_criteria, [{"de": "Orte", "en": ""}])

    @override_settings(**base.AI_ON)
    def test_bad_input(self):
        for body in (
            {"active": "yes"},
            {"active": 1},
            {"criteria": "Orte"},
            {"criteria": [f"K{i}" for i in range(7)]},
            {"criteria": ["x" * 81]},
            {"criteria": [{"de": ["x"]}]},
        ):
            self.assertEqual(self.criteria(body).status_code, 400, body)
        self.client.force_login(self.owner)
        response = self.client.post(
            self.url("ai-criteria"), "[1]", content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)
        self.mq.refresh_from_db()
        self.assertEqual(self.mq.mindmap_criteria, CRITERIA)

    @override_settings(**base.AI_ON)
    def test_non_owner_404(self):
        other = base.User.objects.create_user(username="eve")
        self.assertEqual(self.criteria({"active": True}, user=other).status_code, 404)
        self.assertFalse(crit.is_active(*self.key))
        wrong = self.post("ai-criteria", {}, question=self.question)
        self.assertEqual(wrong.status_code, 404)  # not a mind map

    @override_settings(**base.AI_OFF)
    def test_ai_off_refuses_activation_but_saves_criteria(self):
        self.assertEqual(self.criteria({"active": True}).status_code, 503)
        self.assertFalse(crit.is_active(*self.key))
        response = self.criteria({"criteria": ["Orte"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["active"], False)

    @override_settings(**base.AI_ON)
    def test_ai_switch_off_refused(self):
        self.mq.wordcloud_ai_enabled = False
        self.mq.save()
        self.assertEqual(self.criteria({"active": True}).status_code, 400)
        self.assertFalse(crit.is_active(*self.key))


class PayloadTests(CriteriaTestCase):
    def presenter(self):
        return build_payloads(self.room)["presenter"]["mindmap"]

    def participant(self):
        return build_payloads(self.room)["participant"]["mindmap"]

    def test_presenter_inactive_has_criteria_but_no_node_colours(self):
        self.classify(Wind=1)
        tree = self.presenter()
        self.assertEqual(tree["criteria"], {"active": False, "items": CRITERIA, "pending": 0})
        self.assertNotIn("criterion", self.find(tree["nodes"], "Wind"))

    def test_presenter_active_colours_nodes_and_counts_pending(self):
        self.activate()
        self.classify(FakeLLM(reply={"assignments": [
            {"id": self.wind, "criterion": 1}, {"id": self.solar, "criterion": None},
        ]}))
        self.contribute("Geothermie")
        tree = self.presenter()
        # Geothermie + the three terms the reply left out (retried later).
        self.assertEqual(tree["criteria"]["pending"], 4)
        self.assertTrue(tree["criteria"]["active"])
        self.assertEqual(self.find(tree["nodes"], "Wind")["criterion"], 0)
        self.assertIsNone(self.find(tree["nodes"], "Solar")["criterion"])
        self.assertIsNone(self.find(tree["nodes"], "Geothermie")["criterion"])
        serialized = json.dumps(tree)
        for internal in ("ai_criteria_fp", "ai_text_key", "fingerprint"):
            self.assertNotIn(internal, serialized)

    def set_phase(self, phase, shown=True):
        self.run.phase = phase
        self.run.save()
        self.question_set.show_results_to_participants = shown
        self.question_set.save()

    def test_participant_only_in_results_phase_with_released_results(self):
        self.activate()
        self.classify(Wind=1)
        tree = self.participant()
        self.assertNotIn("criteria", tree)
        self.assertNotIn("criterion", self.find(tree["nodes"], "Wind"))
        self.set_phase(Run.Phase.CLOSED)
        self.assertNotIn("criteria", self.participant())
        self.set_phase(Run.Phase.RESULTS, shown=False)
        self.assertNotIn("criteria", self.participant())
        self.set_phase(Run.Phase.RESULTS)
        tree = self.participant()
        self.assertEqual(tree["criteria"], {"items": CRITERIA})
        self.assertEqual(self.find(tree["nodes"], "Wind")["criterion"], 0)
        self.assertIsNone(self.find(tree["nodes"], "Solar")["criterion"])
        self.assertNotIn("ai_criteria_fp", json.dumps(tree))
        # Colouring switched off on the beamer: gone for participants too…
        self.activate(False)
        tree = self.participant()
        self.assertNotIn("criteria", tree)
        self.assertNotIn("criterion", self.find(tree["nodes"], "Wind"))
        # …but the teacher's results page keeps the stored classification.
        item = next(q for q in run_results(self.run)["questions"] if q["kind"] == "mindmap")
        self.assertEqual(self.find(item["mindmap"]["nodes"], "Wind")["criterion"], 0)

    def test_participant_nothing_without_assigned_terms(self):
        self.activate()
        self.classify()  # every term: none fits
        self.set_phase(Run.Phase.RESULTS)
        self.assertNotIn("criteria", self.participant())


class ResultsTests(CriteriaTestCase):
    def test_results_page_payload(self):
        self.classify(Wind=1, Speicher=2)
        item = next(q for q in run_results(self.run)["questions"] if q["kind"] == "mindmap")
        self.assertEqual(item["mindmap"]["criteria"], {"items": CRITERIA})
        self.assertEqual(self.find(item["mindmap"]["nodes"], "Wind")["criterion"], 0)
        self.assertEqual(self.find(item["mindmap"]["nodes"], "Speicher")["criterion"], 1)

    def test_csv_column(self):
        child = self.contribute("Rotor", parent=self.wind)
        self.classify(Wind=1, Rotor=2)
        self.mq.mindmap_criteria = [CRITERIA[0], {"de": "Infrastruktur", "en": "Grid"}]
        self.mq.save()  # translation only: still valid
        self.client.force_login(self.owner)
        response = self.client.get(
            f"/api/question-sets/{self.question_set.pk}/results.csv?run={self.run.pk}",
            HTTP_ACCEPT_LANGUAGE="de",
        )
        self.assertEqual(response.status_code, 200)
        lines = response.content.decode("utf-8-sig").splitlines()
        self.assertTrue(lines[0].endswith(";bewertung;kriterium"))
        wind = next(line for line in lines if ";Wind;" in line)
        self.assertTrue(wind.endswith(";Erneuerbar"), wind)
        rotor = next(line for line in lines if ";Wind > Rotor;" in line)
        self.assertTrue(rotor.endswith(";Infrastruktur"), rotor)
        solar = next(line for line in lines if ";Solar;" in line)
        self.assertTrue(solar.endswith(";"), solar)
        self.assertTrue(child)
