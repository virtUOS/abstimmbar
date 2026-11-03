# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from rooms.models import Question, QuestionSet, Room

from . import services
from .models import (
    CommitteeGroup,
    CommitteeMember,
    GroupTemplate,
    MeetingInvite,
    MeetingSubstitution,
)
from .services import parse_member_list


def make_room(kind=Room.Kind.COMMITTEE, title="R"):
    return Room.objects.create(title=title, kind=kind)


class ModelTests(TestCase):
    def test_observer_group_created_for_committee_room(self):
        room = make_room()
        groups = list(room.committee_groups.all())
        self.assertEqual(len(groups), 1)
        self.assertTrue(groups[0].is_observer)
        self.assertEqual(groups[0].name_de, "Beobachtende")

    def test_no_groups_for_standard_room(self):
        room = make_room(Room.Kind.STANDARD)
        self.assertEqual(room.committee_groups.count(), 0)

    def test_second_observer_group_rejected(self):
        room = make_room()
        with self.assertRaises(IntegrityError), transaction.atomic():
            CommitteeGroup.objects.create(
                room=room, is_observer=True, name_de="X", name_en="X",
            )

    def test_seeded_templates(self):
        t = list(GroupTemplate.objects.all())
        self.assertEqual([x.position for x in t], [1, 2, 3])
        self.assertEqual(t[0].groups[0], {"de": "Professor*innen", "en": "Professors"})
        self.assertEqual(len(t[1].groups), 4)
        self.assertEqual(len(t[2].groups), 3)

    def _group(self, room, name="G"):
        return CommitteeGroup.objects.create(room=room, name_de=name, name_en=name)

    def test_member_group_must_match_room(self):
        a, b = make_room(title="A"), make_room(title="B")
        m = CommitteeMember(room=a, group=self._group(b), name="M")
        with self.assertRaises(ValidationError):
            m.full_clean()

    def test_observer_cannot_be_deputy(self):
        room = make_room()
        obs = room.committee_groups.get(is_observer=True)
        m = CommitteeMember(room=room, group=obs, name="M", role="deputy")
        with self.assertRaises(ValidationError):
            m.full_clean()

    def test_duplicate_email_in_room_rejected(self):
        room = make_room()
        g = self._group(room)
        CommitteeMember.objects.create(room=room, group=g, name="A", email="a@x.de")
        with self.assertRaises(IntegrityError), transaction.atomic():
            CommitteeMember.objects.create(
                room=room, group=g, name="B", email="a@x.de",
            )

    def test_blank_emails_may_repeat(self):
        room = make_room()
        g = self._group(room)
        CommitteeMember.objects.create(room=room, group=g, name="A")
        CommitteeMember.objects.create(room=room, group=g, name="B")
        self.assertEqual(room.committee_members.count(), 2)

    def test_invite_tokens_unique_and_long(self):
        room = make_room()
        g = self._group(room)
        m1 = CommitteeMember.objects.create(room=room, group=g, name="A")
        m2 = CommitteeMember.objects.create(room=room, group=g, name="B")
        qs = QuestionSet.objects.create(
            room=room, title="M", type=QuestionSet.SetType.MEETING,
        )
        i1 = MeetingInvite.objects.create(meeting=qs, member=m1)
        i2 = MeetingInvite.objects.create(meeting=qs, member=m2)
        self.assertNotEqual(i1.token, i2.token)
        self.assertGreaterEqual(len(i1.token), 40)


User = get_user_model()


class ApiBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("owner", password="x")
        self.other = User.objects.create_user("other", password="x")
        self.room = make_room()
        self.room.owners.add(self.user)
        self.room.owner = self.user
        self.room.save()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.foreign = APIClient()
        self.foreign.force_authenticate(self.other)

    def add_group(self, name="G", room=None):
        return CommitteeGroup.objects.create(
            room=room or self.room, name_de=name, name_en=name, position=1,
        )


class ParseMemberListTests(TestCase):
    def test_mixed_input(self):
        text = "Anna Muster <anna@uni.de>, bert@uni.de; ; nonsense\nanna@uni.de"
        entries, skipped = parse_member_list(text)
        self.assertEqual(
            entries, [("Anna Muster", "anna@uni.de"), ("bert", "bert@uni.de")],
        )
        self.assertEqual(skipped, [
            {"line": "nonsense", "reason": "invalid_email"},
            {"line": "anna@uni.de", "reason": "duplicate"},
        ])


class GroupApiTests(ApiBase):
    def test_templates_list(self):
        r = self.client.get("/api/committee-templates/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()[0]["groups"][0]["de"], "Professor*innen")
        self.assertIn("de", r.json()[0]["name"])

    def test_apply_template_twice(self):
        t = GroupTemplate.objects.first()
        body = {"room": self.room.pk, "template": t.pk}
        r = self.client.post("/api/committee-groups/apply-template/", body, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        names = [g["name"]["de"] for g in r.json()]
        self.assertEqual(names, ["Professor*innen", "Andere"])
        r = self.client.get(f"/api/committee-groups/?room={self.room.pk}")
        self.assertEqual(len(r.json()), 3)
        r = self.client.post("/api/committee-groups/apply-template/", body, format="json")
        self.assertEqual(r.status_code, 400)

    def test_create_group(self):
        r = self.client.post("/api/committee-groups/", {
            "room": self.room.pk, "name": {"de": "Neu", "en": "New"}, "position": 2,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertFalse(r.json()["is_observer"])
        self.assertEqual(r.json()["member_count"], 0)

    def test_delete_observer_group(self):
        obs = self.room.committee_groups.get(is_observer=True)
        r = self.client.delete(f"/api/committee-groups/{obs.pk}/")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], "The observer group cannot be deleted.")

    def test_delete_group_with_member(self):
        g = self.add_group()
        CommitteeMember.objects.create(room=self.room, group=g, name="A")
        r = self.client.delete(f"/api/committee-groups/{g.pk}/")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(
            r.json()["detail"], "Move or remove the group's members first.",
        )

    def test_delete_empty_group(self):
        g = self.add_group()
        r = self.client.delete(f"/api/committee-groups/{g.pk}/")
        self.assertEqual(r.status_code, 204)

    def test_foreign_user(self):
        g = self.add_group()
        r = self.foreign.get(f"/api/committee-groups/?room={self.room.pk}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])
        self.assertEqual(self.foreign.get(f"/api/committee-groups/{g.pk}/").status_code, 404)
        t = GroupTemplate.objects.first()
        r = self.foreign.post(
            "/api/committee-groups/apply-template/",
            {"room": self.room.pk, "template": t.pk}, format="json",
        )
        self.assertEqual(r.status_code, 404)

    def test_staff_sees_all(self):
        staff = User.objects.create_user("staff", password="x", is_staff=True)
        c = APIClient()
        c.force_authenticate(staff)
        self.assertEqual(c.get(f"/api/committee-groups/?room={self.room.pk}").status_code, 200)
        self.assertEqual(len(c.get(f"/api/committee-groups/?room={self.room.pk}").json()), 1)


class MemberApiTests(ApiBase):
    def test_create(self):
        g = self.add_group()
        r = self.client.post("/api/committee-members/", {
            "room": self.room.pk, "group": g.pk, "name": "Anna",
            "email": "anna@uni.de",
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["role"], "voting")

    def test_group_from_other_room(self):
        other_room = make_room(title="O")
        other_room.owners.add(self.user)
        g = self.add_group(room=other_room)
        r = self.client.post("/api/committee-members/", {
            "room": self.room.pk, "group": g.pk, "name": "Anna",
        }, format="json")
        self.assertEqual(r.status_code, 400)

    def test_deputy_in_observer_group(self):
        obs = self.room.committee_groups.get(is_observer=True)
        r = self.client.post("/api/committee-members/", {
            "room": self.room.pk, "group": obs.pk, "name": "A", "role": "deputy",
        }, format="json")
        self.assertEqual(r.status_code, 400)

    def test_duplicate_email_is_400(self):
        g = self.add_group()
        body = {"room": self.room.pk, "group": g.pk, "name": "A", "email": "a@uni.de"}
        self.assertEqual(
            self.client.post("/api/committee-members/", body, format="json").status_code, 201,
        )
        r = self.client.post("/api/committee-members/", body, format="json")
        self.assertEqual(r.status_code, 400, r.content)

    def test_bulk(self):
        g = self.add_group()
        CommitteeMember.objects.create(
            room=self.room, group=g, name="bert", email="bert@uni.de",
        )
        text = "Anna Muster <anna@uni.de>, bert@uni.de; ; nonsense\nanna@uni.de"
        r = self.client.post("/api/committee-members/bulk/", {
            "room": self.room.pk, "group": g.pk, "role": "voting", "text": text,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        data = r.json()
        self.assertEqual(len(data["created"]), 1)
        self.assertEqual(data["created"][0]["email"], "anna@uni.de")
        self.assertIn({"line": "bert@uni.de", "reason": "exists"}, data["skipped"])
        self.assertIn({"line": "nonsense", "reason": "invalid_email"}, data["skipped"])

    def test_bulk_bad_group(self):
        r = self.client.post("/api/committee-members/bulk/", {
            "room": self.room.pk, "group": 999999, "role": "voting", "text": "a@b.de",
        }, format="json")
        self.assertEqual(r.status_code, 400)

    def test_foreign_user(self):
        g = self.add_group()
        m = CommitteeMember.objects.create(room=self.room, group=g, name="A")
        self.assertEqual(self.foreign.get(f"/api/committee-members/{m.pk}/").status_code, 404)
        r = self.foreign.get(f"/api/committee-members/?room={self.room.pk}")
        self.assertEqual(r.json(), [])
        r = self.foreign.post("/api/committee-members/bulk/", {
            "room": self.room.pk, "group": g.pk, "role": "voting", "text": "a@b.de",
        }, format="json")
        self.assertEqual(r.status_code, 404)


class MeetingFixture:
    """A committee room with groups A, B, observers and one meeting."""

    def make_fixture(self, room=None):
        self.room = room or make_room()
        self.obs_group = self.room.committee_groups.get(is_observer=True)
        self.ga = CommitteeGroup.objects.create(
            room=self.room, name_de="Gruppe A", name_en="Group A", position=1,
        )
        self.gb = CommitteeGroup.objects.create(
            room=self.room, name_de="Gruppe B", name_en="Group B", position=2,
        )
        self.meeting = QuestionSet.objects.create(
            room=self.room, title="Sitzung", type=QuestionSet.SetType.MEETING,
        )

    def member(self, name, group, role="voting", rank=None, email=""):
        return CommitteeMember.objects.create(
            room=self.room, group=group, name=name, role=role,
            deputy_rank=rank, email=email,
        )


class MeetingServiceTests(MeetingFixture, TestCase):
    def setUp(self):
        self.make_fixture()

    def test_suggest_deputy_by_rank(self):
        absent = self.member("Anna", self.ga)
        absent2 = self.member("Bert", self.ga)
        absent3 = self.member("Carla", self.ga)
        a2 = self.member("Zoe", self.ga, "deputy", 2)
        a1 = self.member("Yan", self.ga, "deputy", 1)
        self.member("Bea", self.gb, "deputy", 1)
        self.assertEqual(services.suggest_deputy(self.meeting, absent), a1)
        services.add_substitution(self.meeting, absent, a1)
        self.assertEqual(services.suggest_deputy(self.meeting, absent2), a2)
        services.add_substitution(self.meeting, absent2, a2)
        self.assertIsNone(services.suggest_deputy(self.meeting, absent3))

    def test_suggest_deputy_unranked_last_then_name(self):
        absent = self.member("Anna", self.ga)
        self.member("Aaron", self.ga, "deputy", None)
        ranked = self.member("Zoe", self.ga, "deputy", 5)
        self.assertEqual(services.suggest_deputy(self.meeting, absent), ranked)

    def test_substitute_other_group_rejected(self):
        absent = self.member("Anna", self.ga)
        deputy = self.member("Bea", self.gb, "deputy", 1)
        with self.assertRaisesMessage(
            ValidationError, "The substitute must belong to the same group.",
        ):
            services.add_substitution(self.meeting, absent, deputy)

    def test_voting_member_cannot_substitute(self):
        absent = self.member("Anna", self.ga)
        other = self.member("Bert", self.ga)
        with self.assertRaisesMessage(ValidationError, "Only deputies can substitute."):
            services.add_substitution(self.meeting, absent, other)

    def test_observer_cannot_be_absent(self):
        absent = self.member("Olga", self.obs_group)
        deputy = self.member("Yan", self.ga, "deputy", 1)
        with self.assertRaises(ValidationError):
            services.add_substitution(self.meeting, absent, deputy)

    def test_substitution_rejected_after_end(self):
        absent = self.member("Anna", self.ga)
        deputy = self.member("Yan", self.ga, "deputy", 1)
        services.start_meeting(self.meeting)
        services.end_meeting(self.meeting)
        with self.assertRaises(ValidationError):
            services.add_substitution(self.meeting, absent, deputy)

    def test_from_question_must_belong_to_meeting(self):
        absent = self.member("Anna", self.ga)
        deputy = self.member("Yan", self.ga, "deputy", 1)
        other = QuestionSet.objects.create(
            room=self.room, title="Other", type=QuestionSet.SetType.MEETING,
        )
        q = Question.objects.create(question_set=other, kind="single_choice", text="Q")
        with self.assertRaises(ValidationError):
            services.add_substitution(self.meeting, absent, deputy, from_question=q)

    def test_deputy_used_twice_rejected(self):
        a = self.member("Anna", self.ga)
        b = self.member("Bert", self.ga)
        deputy = self.member("Yan", self.ga, "deputy", 1)
        services.add_substitution(self.meeting, a, deputy)
        with self.assertRaises(IntegrityError), transaction.atomic():
            services.add_substitution(self.meeting, b, deputy)

    def test_remove_substitution_in_running_meeting(self):
        anna = self.member("Anna", self.ga)
        deputy = self.member("Yan", self.ga, "deputy", 1)
        sub = services.add_substitution(self.meeting, anna, deputy)
        services.start_meeting(self.meeting)
        self.assertFalse(self.meeting.invites.filter(member=anna).exists())
        services.remove_substitution(sub)
        invite = self.meeting.invites.get(member=anna)
        self.assertEqual(services.resolve_invite(invite.token)[1], "active")
        services.end_meeting(self.meeting)
        sub = MeetingSubstitution.objects.create(
            meeting=self.meeting, absent=anna, deputy=deputy,
        )
        with self.assertRaises(ValidationError):
            services.remove_substitution(sub)

    def test_deputy_link_inactive_after_substitution_removed(self):
        anna = self.member("Anna", self.ga)
        deputy = self.member("Yan", self.ga, "deputy", 1)
        sub = services.add_substitution(self.meeting, anna, deputy)
        services.start_meeting(self.meeting)
        idep = self.meeting.invites.get(member=deputy)
        self.assertEqual(services.resolve_invite(idep.token)[1], "active")
        services.remove_substitution(sub)
        self.assertEqual(services.resolve_invite(idep.token)[1], "inactive")
        # re-added as substitute -> valid again
        services.add_substitution(self.meeting, anna, deputy)
        self.assertEqual(services.resolve_invite(idep.token)[1], "active")

    def test_voting_member_changed_to_deputy_inactive(self):
        anna = self.member("Anna", self.ga)
        services.ensure_invites(self.meeting)
        invite = self.meeting.invites.get(member=anna)
        self.assertEqual(services.resolve_invite(invite.token)[1], "waiting")
        anna.role = "deputy"
        anna.save()
        self.assertEqual(services.resolve_invite(invite.token)[1], "inactive")
        self.assertNotIn(anna, services.participants(self.meeting))

    def test_inactive_checked_before_removed(self):
        anna = self.member("Anna", self.ga)
        services.start_meeting(self.meeting)
        invite = self.meeting.invites.get(member=anna)
        services.remove_invite(invite)
        anna.role = "deputy"
        anna.save()
        self.assertEqual(services.resolve_invite(invite.token)[1], "inactive")

    def test_participants_and_invites(self):
        v1 = self.member("Anna", self.ga)
        v2 = self.member("Bert", self.ga)
        v3 = self.member("Carla", self.gb)
        obs = self.member("Olga", self.obs_group)
        used = self.member("Yan", self.ga, "deputy", 1)
        self.member("Zoe", self.ga, "deputy", 2)
        services.add_substitution(self.meeting, v1, used)
        self.assertEqual(
            {m.pk for m in services.participants(self.meeting)},
            {v2.pk, v3.pk, obs.pk, used.pk},
        )
        invites = services.ensure_invites(self.meeting)
        self.assertEqual(len(invites), 4)
        services.ensure_invites(self.meeting)
        self.assertEqual(self.meeting.invites.count(), 4)

    def test_partial_substitution_keeps_absent_participant(self):
        v1 = self.member("Anna", self.ga)
        used = self.member("Yan", self.ga, "deputy", 1)
        q = Question.objects.create(
            question_set=self.meeting, kind="single_choice", text="TOP 2",
        )
        services.add_substitution(self.meeting, v1, used, from_question=q)
        self.assertEqual(
            {m.pk for m in services.participants(self.meeting)}, {v1.pk, used.pk},
        )

    def test_resolve_states(self):
        anna = self.member("Anna", self.ga)
        bert = self.member("Bert", self.ga)
        carla = self.member("Carla", self.ga)
        deputy = self.member("Yan", self.ga, "deputy", 1)
        self.assertEqual(services.resolve_invite("nope"), (None, "unknown"))
        services.ensure_invites(self.meeting)
        ia = self.meeting.invites.get(member=anna)
        ib = self.meeting.invites.get(member=bert)
        ic = self.meeting.invites.get(member=carla)
        self.assertEqual(services.resolve_invite(ia.token), (ia, "waiting"))
        services.start_meeting(self.meeting)
        self.assertEqual(services.resolve_invite(ia.token)[1], "active")
        services.remove_invite(ib)
        self.assertEqual(services.resolve_invite(ib.token)[1], "removed")
        services.readmit_invite(ib)
        self.assertEqual(services.resolve_invite(ib.token)[1], "active")
        services.remove_invite(ib)
        services.add_substitution(self.meeting, carla, deputy)
        self.assertEqual(services.resolve_invite(ic.token)[1], "replaced")
        # the deputy got a link when substituting into a running meeting
        idep = self.meeting.invites.get(member=deputy)
        self.assertEqual(services.resolve_invite(idep.token)[1], "active")
        services.end_meeting(self.meeting)
        for invite in (ia, ib, ic, idep):
            self.assertEqual(services.resolve_invite(invite.token)[1], "ended")

    def test_remove_after_question_must_belong(self):
        anna = self.member("Anna", self.ga)
        services.start_meeting(self.meeting)
        invite = self.meeting.invites.get(member=anna)
        other = QuestionSet.objects.create(
            room=self.room, title="Other", type=QuestionSet.SetType.MEETING,
        )
        q_other = Question.objects.create(question_set=other, kind="single_choice", text="Q")
        with self.assertRaises(ValidationError):
            services.remove_invite(invite, after_question=q_other)
        q = Question.objects.create(question_set=self.meeting, kind="single_choice", text="Q")
        services.remove_invite(invite, after_question=q)
        invite.refresh_from_db()
        self.assertIsNotNone(invite.removed_at)
        self.assertEqual(invite.removed_after, q)

    def test_remove_rejected_after_end(self):
        anna = self.member("Anna", self.ga)
        services.start_meeting(self.meeting)
        invite = self.meeting.invites.get(member=anna)
        services.end_meeting(self.meeting)
        with self.assertRaises(ValidationError):
            services.remove_invite(invite)
        with self.assertRaises(ValidationError):
            services.readmit_invite(invite)

    def test_start_twice_rejected(self):
        services.start_meeting(self.meeting)
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.meeting_state, QuestionSet.MeetingState.STARTED)
        with self.assertRaisesMessage(ValidationError, "The meeting has already started."):
            services.start_meeting(self.meeting)

    def test_end_requires_started(self):
        with self.assertRaises(ValidationError):
            services.end_meeting(self.meeting)
        services.start_meeting(self.meeting)
        services.end_meeting(self.meeting)
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.meeting_state, QuestionSet.MeetingState.ENDED)
        with self.assertRaises(ValidationError):
            services.end_meeting(self.meeting)


class MeetingApiTests(MeetingFixture, ApiBase):
    def setUp(self):
        super().setUp()
        self.make_fixture(room=self.room)
        self.base = f"/api/meetings/{self.meeting.pk}/"

    def test_foreign_user_404(self):
        self.assertEqual(self.foreign.get(self.base).status_code, 404)
        self.assertEqual(self.foreign.post(self.base + "start/").status_code, 404)
        self.assertEqual(self.foreign.get(self.base + "invites.csv").status_code, 404)

    def test_non_meeting_set_404(self):
        qs = QuestionSet.objects.create(room=self.room, title="X")
        self.assertEqual(self.client.get(f"/api/meetings/{qs.pk}/").status_code, 404)

    def test_detail_with_invites(self):
        anna = self.member("Anna", self.ga, email="anna@uni.de")
        r = self.client.post(self.base + "invites/")
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.get(self.base)
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["meeting_state"], "draft")
        self.assertEqual(len(data["invites"]), 1)
        invite = data["invites"][0]
        token = MeetingInvite.objects.get(member=anna).token
        self.assertTrue(invite["url"].endswith(f"/g/{token}/"))
        self.assertTrue(invite["url"].startswith("http"))
        self.assertEqual(invite["state"], "waiting")
        self.assertEqual(invite["member"]["name"], "Anna")
        self.assertEqual(invite["member"]["group"], self.ga.pk)
        self.assertEqual(data["substitutions"], [])

    def test_start_and_end(self):
        self.member("Anna", self.ga)
        r = self.client.post(self.base + "start/")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["meeting_state"], "started")
        self.assertEqual(len(r.json()["invites"]), 1)
        r = self.client.post(self.base + "start/")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], "The meeting has already started.")
        r = self.client.post(self.base + "end/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["meeting_state"], "ended")
        self.assertEqual(self.client.post(self.base + "end/").status_code, 400)

    def test_csv(self):
        self.member("=cmd", self.ga, email="x@uni.de")
        self.member("Bert", self.obs_group)
        carla = self.member("Carla", self.ga)
        dora = self.member("Dora", self.gb)
        self.client.post(self.base + "start/")
        # invalid links are left out of the export
        services.remove_invite(MeetingInvite.objects.get(member=carla))
        dora.role = "deputy"
        dora.save()
        r = self.client.get(self.base + "invites.csv", HTTP_ACCEPT_LANGUAGE="de")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r["Content-Disposition"],
            f'attachment; filename="links-{self.meeting.pk}.csv"',
        )
        lines = r.content.decode("utf-8-sig").strip().splitlines()
        self.assertEqual(lines[0], "Name,E-Mail,Gruppe,Rolle,Link")
        self.assertEqual(len(lines), 3)
        body = "\n".join(lines[1:])
        self.assertIn("'=cmd", body)
        self.assertIn("Gruppe A", body)
        self.assertNotIn("Carla", body)
        self.assertNotIn("Dora", body)
        r = self.client.get(self.base + "invites.csv", HTTP_ACCEPT_LANGUAGE="en")
        lines = r.content.decode("utf-8-sig").strip().splitlines()
        self.assertEqual(lines[0], "Name,E-Mail,Group,Role,Link")

    def test_substitutions_api(self):
        absent = self.member("Anna", self.ga)
        b = self.member("Bert", self.ga)
        deputy = self.member("Yan", self.ga, "deputy", 1)
        r = self.client.get(self.base + f"substitutions/suggest/?absent={absent.pk}")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["deputy"]["id"], deputy.pk)
        r = self.client.post(self.base + "substitutions/", {
            "absent": absent.pk, "deputy": deputy.pk,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        sub_id = r.json()["id"]
        r = self.client.get(self.base + f"substitutions/suggest/?absent={b.pk}")
        self.assertIsNone(r.json()["deputy"])
        # deputy used twice -> 400, not 500
        r = self.client.post(self.base + "substitutions/", {
            "absent": b.pk, "deputy": deputy.pk,
        }, format="json")
        self.assertEqual(r.status_code, 400, r.content)
        r = self.client.get(self.base)
        self.assertEqual(len(r.json()["substitutions"]), 1)
        r = self.client.delete(self.base + f"substitutions/{sub_id}/")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(MeetingSubstitution.objects.exists())

    def test_substitution_member_from_other_room(self):
        other_room = make_room(title="O")
        og = CommitteeGroup.objects.create(room=other_room, name_de="X", name_en="X")
        stranger = CommitteeMember.objects.create(room=other_room, group=og, name="S")
        deputy = self.member("Yan", self.ga, "deputy", 1)
        r = self.client.post(self.base + "substitutions/", {
            "absent": stranger.pk, "deputy": deputy.pk,
        }, format="json")
        self.assertEqual(r.status_code, 400)
        r = self.client.get(self.base + f"substitutions/suggest/?absent={stranger.pk}")
        self.assertEqual(r.status_code, 400)

    def test_remove_and_readmit(self):
        anna = self.member("Anna", self.ga)
        self.client.post(self.base + "start/")
        invite = MeetingInvite.objects.get(member=anna)
        q = Question.objects.create(question_set=self.meeting, kind="single_choice", text="Q")
        r = self.client.post(
            self.base + f"invites/{invite.pk}/remove/", {"after_question": q.pk},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["state"], "removed")
        self.assertEqual(r.json()["removed_after"], q.pk)
        r = self.client.post(self.base + f"invites/{invite.pk}/readmit/")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["state"], "active")
        self.assertIsNone(r.json()["removed_at"])


class EntryPageTests(MeetingFixture, TestCase):
    def setUp(self):
        self.make_fixture()
        self.room.title_de, self.room.title_en = "Fakultätsrat", "Faculty Council"
        self.room.save()
        self.meeting.title_de, self.meeting.title_en = "Sitzung 1", "Meeting 1"
        self.meeting.scheduled_at = timezone.now()
        self.meeting.save()
        self.anna = self.member("Anna Muster", self.ga)
        self.obs = self.member("Olga Beobachtet", self.obs_group)

    def _invite(self, member):
        return MeetingInvite.objects.create(meeting=self.meeting, member=member)

    def _get(self, invite, lang=None):
        suffix = f"?lang={lang}" if lang else ""
        return self.client.get(f"/g/{invite.token}/{suffix}")

    def test_unknown_token_404_generic(self):
        r = self.client.get("/g/nope/?lang=en")
        self.assertEqual(r.status_code, 404)
        self.assertContains(r, "This link is not valid (any more).", status_code=404)

    def test_waiting(self):
        invite = self._invite(self.anna)
        r = self._get(invite, "de")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Die Sitzung hat noch nicht begonnen.")
        self.assertContains(r, "Sie nehmen teil als Anna Muster (Gruppe A).")
        self.assertContains(r, "Fakultätsrat")
        self.assertContains(r, "Sitzung 1")
        r = self._get(invite, "en")
        self.assertContains(r, "The meeting has not started yet.")
        self.assertContains(r, "You are taking part as Anna Muster (Group A).")
        self.assertContains(r, "Faculty Council")

    def test_member_language_default_and_query_override(self):
        self.anna.language = "en"
        self.anna.save()
        invite = self._invite(self.anna)
        self.assertContains(self._get(invite), "The meeting has not started yet.")
        self.assertContains(self._get(invite, "de"), "Die Sitzung hat noch nicht begonnen.")

    def test_active(self):
        invite = self._invite(self.anna)
        self.meeting.meeting_state = "started"
        self.meeting.save()
        self.assertContains(self._get(invite, "en"), "The meeting is in progress.")
        self.assertContains(self._get(invite, "de"), "Die Sitzung läuft.")

    def test_headers(self):
        r = self._get(self._invite(self.anna), "de")
        self.assertEqual(r["Cache-Control"], "no-store")
        self.assertEqual(r["Referrer-Policy"], "no-referrer")
        r = self.client.get("/g/nope/")
        self.assertEqual(r["Cache-Control"], "no-store")

    def test_observer(self):
        invite = self._invite(self.obs)
        self.assertContains(
            self._get(invite, "de"), "Sie nehmen als Beobachter*in teil und können nicht abstimmen.",
        )
        self.assertContains(self._get(invite, "en"), "You are taking part as an observer.")

    def test_invalid_states_reveal_nothing(self):
        ended = self._invite(self.anna)
        removed = self._invite(self.obs)
        bert = self.member("Bert Geheim", self.ga)
        replaced = self._invite(bert)
        dora = self.member("Dora Vertretung", self.ga, role="deputy")
        services.add_substitution(self.meeting, bert, dora)
        inactive = self._invite(self.member("Ina Inaktiv", self.ga, role="deputy"))
        services.remove_invite(removed)
        cases = {"removed": removed, "replaced": replaced, "inactive": inactive}
        for state, invite in cases.items():
            for lang, text in (("en", "This link is not valid (any more)."),
                               ("de", "Dieser Link ist nicht (mehr) gültig.")):
                r = self._get(invite, lang)
                self.assertEqual(r.status_code, 200, state)
                self.assertContains(r, text)
                for secret in ("Fakultätsrat", "Faculty Council", "Sitzung 1", "Meeting 1",
                               invite.member.name, "Gruppe A", "Group A"):
                    self.assertNotContains(r, secret, msg_prefix=state)
        self.meeting.meeting_state = "ended"
        self.meeting.save()
        r = self._get(ended, "en")
        self.assertContains(r, "This link is not valid (any more).")
        self.assertNotContains(r, "Anna Muster")


class RoomDeleteCascadeTests(MeetingFixture, ApiBase):
    def test_delete_room_with_everything(self):
        self.make_fixture(self.room)
        anna = self.member("Anna", self.ga)
        bert = self.member("Bert", self.ga, role="deputy")
        invite = MeetingInvite.objects.create(meeting=self.meeting, member=anna)
        services.add_substitution(self.meeting, anna, bert)
        r = self.client.delete(f"/api/rooms/{self.room.pk}/")
        self.assertEqual(r.status_code, 204)
        self.assertFalse(Room.objects.filter(pk=self.room.pk).exists())
        self.assertFalse(CommitteeMember.objects.filter(pk__in=[anna.pk, bert.pk]).exists())
        self.assertFalse(CommitteeGroup.objects.filter(room_id=self.room.pk).exists())
        self.assertFalse(MeetingInvite.objects.filter(pk=invite.pk).exists())
        self.assertFalse(MeetingSubstitution.objects.exists())
        self.assertFalse(QuestionSet.objects.filter(pk=self.meeting.pk).exists())


class EntryPageAcceptLanguageTests(TestCase):
    def test_unknown_token_uses_accept_language(self):
        r = self.client.get("/g/nope/", HTTP_ACCEPT_LANGUAGE="en")
        self.assertContains(r, "This link is not valid (any more).", status_code=404)
