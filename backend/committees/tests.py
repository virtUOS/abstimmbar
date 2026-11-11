# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

import json
import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone, translation
from rest_framework.test import APIClient

from rooms.models import AnswerOption, Question, QuestionSet, Room, Section

from . import agenda, ballots, eligibility, payloads, seals, services, versions
from .models import (
    Ballot,
    BallotSeat,
    BallotText,
    CommitteeGroup,
    CommitteeMember,
    GroupTemplate,
    MeetingControl,
    MeetingInvite,
    MeetingSubstitution,
    MotionVersion,
    NamedVote,
    SealLink,
    TopNote,
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

    def test_last_first_name_with_angle_address(self):
        text = "Rolf, Rüdiger <rrolf@example.org>; Weg, Karl <k@example.org>"
        entries, skipped = parse_member_list(text)
        self.assertEqual(entries, [
            ("Rolf, Rüdiger", "rrolf@example.org"), ("Weg, Karl", "k@example.org"),
        ])
        self.assertEqual(skipped, [])

    def test_quoted_name_with_comma(self):
        entries, skipped = parse_member_list(
            '"Weg, Karl" <k@example.org>, "Muster, Anna" <a@example.org>',
        )
        self.assertEqual(entries, [
            ("Weg, Karl", "k@example.org"), ("Muster, Anna", "a@example.org"),
        ])
        self.assertEqual(skipped, [])

    def test_comma_list_of_last_first_names(self):
        entries, _ = parse_member_list(
            "Rolf, Rüdiger <rrolf@example.org>, Weg, Karl <k@example.org>, c@example.org",
        )
        self.assertEqual(entries, [
            ("Rolf, Rüdiger", "rrolf@example.org"), ("Weg, Karl", "k@example.org"),
            ("c", "c@example.org"),
        ])

    def test_stray_word_before_bare_mail_stays_separate(self):
        entries, skipped = parse_member_list("nonsense, bert@uni.de")
        self.assertEqual(entries, [("bert", "bert@uni.de")])
        self.assertEqual(skipped, [{"line": "nonsense", "reason": "invalid_email"}])

    def test_email_longer_than_column_rejected(self):
        email = "a" * 64 + "@" + ".".join(["b" * 63] * 3) + ".de"
        self.assertGreater(len(email), 254)
        entries, skipped = parse_member_list(email)
        self.assertEqual(entries, [])
        self.assertEqual(skipped, [{"line": email, "reason": "invalid_email"}])


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

    def test_bulk_too_long_email_no_500(self):
        g = self.add_group()
        email = "a" * 64 + "@" + ".".join(["b" * 63] * 3) + ".de"
        r = self.client.post("/api/committee-members/bulk/", {
            "room": self.room.pk, "group": g.pk, "role": "voting", "text": email,
        }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["created"], [])
        self.assertEqual(r.json()["skipped"], [{"line": email, "reason": "invalid_email"}])

    def test_bulk_integrity_error_skips_row(self):
        # Two rows for the same address that slip past the parser's dedupe
        # (as with a concurrent insert): the second is skipped, no 500.
        g = self.add_group()
        rows = ([("A", "a@uni.de"), ("A2", "a@uni.de"), ("B", "b@uni.de")], [])
        with mock.patch("committees.views.parse_member_list", return_value=rows):
            r = self.client.post("/api/committee-members/bulk/", {
                "room": self.room.pk, "group": g.pk, "role": "voting", "text": "x",
            }, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(
            [m["email"] for m in r.json()["created"]], ["a@uni.de", "b@uni.de"],
        )
        self.assertEqual(r.json()["skipped"], [{"line": "a@uni.de", "reason": "exists"}])
        self.assertEqual(self.room.committee_members.count(), 2)

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


class KnownPeopleTests(ApiBase):
    """Autocomplete for adding members: only people from the requester's own
    committee rooms and the co-owners of their rooms — never other accounts."""

    URL = "/api/committee-members/known/"

    def setUp(self):
        super().setUp()
        self.mine = make_room(title="Mine")
        self.mine.owners.add(self.user)
        group = self.add_group(room=self.mine)
        CommitteeMember.objects.create(
            room=self.mine, group=group, name="Anna Muster", email="anna@uni.de",
        )
        CommitteeMember.objects.create(room=self.mine, group=group, name="No Mail")
        foreign_room = make_room(title="Foreign")
        foreign_room.owners.add(self.other)
        CommitteeMember.objects.create(
            room=foreign_room, group=self.add_group(room=foreign_room),
            name="Annabel Fremd", email="annabel@uni.de",
        )
        self.colleague = User.objects.create_user(
            "colleague", email="carla@uni.de", first_name="Carla", last_name="Kollegin",
        )
        course = make_room(kind=Room.Kind.STANDARD, title="Course")
        course.owners.add(self.user, self.colleague)
        User.objects.create_user("stranger", email="anton@uni.de", first_name="Anton")

    def search(self, q, client=None):
        return (client or self.client).get(self.URL, {"room": self.room.pk, "q": q})

    def test_finds_members_of_own_committees(self):
        r = self.search("ann")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json(), [{"name": "Anna Muster", "email": "anna@uni.de"}])

    def test_finds_co_owners_by_name_or_email(self):
        expected = [{"name": "Carla Kollegin", "email": "carla@uni.de"}]
        self.assertEqual(self.search("kolleg").json(), expected)
        self.assertEqual(self.search("carla@").json(), expected)

    def test_never_other_accounts_or_foreign_committees(self):
        self.assertEqual(self.search("anton").json(), [])
        self.assertEqual(self.search("annabel").json(), [])

    def test_excludes_people_already_in_the_room(self):
        CommitteeMember.objects.create(
            room=self.room, group=self.add_group(), name="Anna", email="ANNA@uni.de",
        )
        self.assertEqual(self.search("ann").json(), [])

    def test_short_query_returns_nothing(self):
        self.assertEqual(self.search("a").json(), [])

    def test_room_must_be_managed(self):
        self.assertEqual(self.search("ann", client=self.foreign).status_code, 404)


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


def add_vote(meeting):
    """A meeting can only start with at least one item to vote on."""
    return Question.objects.create(
        question_set=meeting, kind="resolution", text_de="Antrag", position=1,
    )


class MeetingServiceTests(MeetingFixture, TestCase):
    def setUp(self):
        self.make_fixture()
        add_vote(self.meeting)

    def test_start_marks_connected_invites_entered(self):
        from .presence import presence

        anna = self.member("Anna", self.ga)
        bert = self.member("Bert", self.ga)
        services.ensure_invites(self.meeting)
        connected = MeetingInvite.objects.get(meeting=self.meeting, member=anna)
        presence.connect(connected.pk)
        self.addCleanup(presence.disconnect, connected.pk)
        services.start_meeting(self.meeting)
        connected.refresh_from_db()
        self.assertIsNotNone(connected.entered_at)
        self.assertIsNone(
            MeetingInvite.objects.get(meeting=self.meeting, member=bert).entered_at,
        )
        self.assertEqual(eligibility.eligible_voters(self.meeting, Question.objects.create(
            question_set=self.meeting, kind="resolution", text_de="X",
        )), [anna])

    def test_ensure_invites_notifies_in_running_meeting(self):
        self.member("Anna", self.ga)
        with mock.patch("committees.live.broadcast_meeting") as broadcast:
            with self.captureOnCommitCallbacks(execute=True):
                services.ensure_invites(self.meeting)  # draft: no broadcast
            broadcast.assert_not_called()
            services.start_meeting(self.meeting)
            self.member("Bert", self.ga)
            with self.captureOnCommitCallbacks(execute=True):
                services.ensure_invites(self.meeting)
            broadcast.assert_called_once()
            broadcast.reset_mock()
            with self.captureOnCommitCallbacks(execute=True):
                services.ensure_invites(self.meeting)  # nothing new
            broadcast.assert_not_called()

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
        add_vote(self.meeting)
        self.base = f"/api/meetings/{self.meeting.pk}/"

    def test_foreign_user_404(self):
        self.assertEqual(self.foreign.get(self.base).status_code, 404)
        self.assertEqual(self.foreign.post(self.base + "start/").status_code, 404)
        self.assertEqual(self.foreign.get(self.base + "invites.csv").status_code, 404)

    def test_non_meeting_set_404(self):
        qs = QuestionSet.objects.create(room=self.room, title="X")
        self.assertEqual(self.client.get(f"/api/meetings/{qs.pk}/").status_code, 404)

    def test_invites_rejected_after_end(self):
        self.member("Anna", self.ga, email="anna@uni.de")
        services.start_meeting(self.meeting)
        services.end_meeting(self.meeting)
        before = MeetingInvite.objects.filter(meeting=self.meeting).count()
        self.member("Bert", self.ga, email="bert@uni.de")
        r = self.client.post(self.base + "invites/")
        self.assertEqual(r.status_code, 400, r.content)
        self.assertEqual(MeetingInvite.objects.filter(meeting=self.meeting).count(), before)

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

    def test_start_needs_an_item_with_a_vote(self):
        self.meeting.questions.all().delete()
        Section.objects.create(question_set=self.meeting, title_de="Bericht", position=1)
        for body in ({}, {"trial": True}):
            r = self.client.post(self.base + "start/", body, format="json")
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.json()["code"], "empty_agenda")
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.meeting_state, "draft")

    def test_start_and_end_times(self):
        data = self.client.get(self.base).json()
        self.assertIsNone(data["started_at"])
        self.assertIsNone(data["ended_at"])
        started = self.client.post(self.base + "start/").json()
        self.assertIsNotNone(started["started_at"])
        self.assertIsNone(started["ended_at"])
        ended = self.client.post(self.base + "end/").json()
        self.assertEqual(ended["started_at"], started["started_at"])
        self.assertIsNotNone(ended["ended_at"])

    def test_chair_is_member(self):
        self.user.email = "Chair@Uni.de"
        self.user.save()
        self.assertFalse(self.client.get(self.base).json()["chair_is_member"])
        self.member("Chair", self.obs_group, email="chair@uni.de")
        self.assertFalse(self.client.get(self.base).json()["chair_is_member"])
        CommitteeMember.objects.all().delete()
        self.member("Chair", self.ga, role="deputy", email="chair@uni.de")
        self.assertFalse(self.client.get(self.base).json()["chair_is_member"])
        CommitteeMember.objects.all().delete()
        self.member("Chair", self.ga, email="chair@uni.de")
        self.assertTrue(self.client.get(self.base).json()["chair_is_member"])

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
        # Removed "after" an item: still there until the agenda passes it.
        self.assertEqual(r.json()["state"], "active")
        self.assertEqual(r.json()["removed_after"], q.pk)
        q2 = Question.objects.create(
            question_set=self.meeting, kind="single_choice", text="Q2", position=q.position + 1,
        )
        self.assertEqual(self.client.post(
            self.base + "show/", {"question": q2.pk}, format="json",
        ).status_code, 200)
        r = self.client.get(self.base)
        state = next(i["state"] for i in r.json()["invites"] if i["id"] == invite.pk)
        self.assertEqual(state, "removed")
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
        self.assertContains(r, "Sie stimmen als Anna Muster (Gruppe A).")
        self.assertContains(r, "Fakultätsrat")
        self.assertContains(r, "Sitzung 1")
        r = self._get(invite, "en")
        self.assertContains(r, "The meeting has not started yet.")
        # Group names are content: canonical language only (PR 2).
        self.assertContains(r, "You are voting as Anna Muster (Gruppe A).")
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
        self.assertContains(self._get(invite, "en"), "Please wait for the next vote.")
        self.assertContains(self._get(invite, "de"), "Bitte warten Sie auf die nächste Abstimmung.")

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


class BallotPreviewTests(MeetingFixture, ApiBase):
    def setUp(self):
        super().setUp()
        self.make_fixture(room=self.room)
        self.q = Question.objects.create(
            question_set=self.meeting, kind=Question.Kind.RESOLUTION,
            text_de="<p>Der Antrag wird angenommen.</p>", position=0,
        )
        self.url = f"/g/preview/{self.q.pk}/"

    def test_owner_sees_ballot_preview(self):
        self.client.force_login(self.user)
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        config = r.context["config"]
        self.assertTrue(config["preview"])
        item = config["snapshot"]["item"]
        self.assertEqual(item["kind"], "resolution")
        self.assertEqual(item["label"], "1")
        self.assertNotIn("number", item)
        self.assertEqual(item["ballot"]["status"], "open")
        self.assertIn("Der Antrag wird angenommen.", item["text"])
        self.assertIn("frame-ancestors", r["Content-Security-Policy"])
        self.assertNotIn("X-Frame-Options", r)

    def test_foreign_user_and_anonymous_404(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_non_meeting_question_404(self):
        qs = QuestionSet.objects.create(room=self.room, title="X")
        q = Question.objects.create(question_set=qs, kind=Question.Kind.SINGLE_CHOICE, position=0)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(f"/g/preview/{q.pk}/").status_code, 404)


class BallotPageTests(MeetingFixture, TestCase):
    def setUp(self):
        self.make_fixture()
        self.anna = self.member("Anna Muster", self.ga)
        self.obs = self.member("Olga Beobachtet", self.obs_group)
        self.anna_invite = MeetingInvite.objects.create(meeting=self.meeting, member=self.anna)
        self.obs_invite = MeetingInvite.objects.create(meeting=self.meeting, member=self.obs)

    def _start(self):
        self.meeting.meeting_state = "started"
        self.meeting.save()

    def _strings(self, response):
        """The UI strings handed to the inline script (json_script escapes
        non-ASCII, so read them back as JSON)."""
        match = re.search(
            r'<script id="ballot-i18n" type="application/json">(.*?)</script>',
            response.content.decode(),
        )
        self.assertIsNotNone(match)
        return json.loads(match.group(1))

    def test_member_page(self):
        self._start()
        r = self.client.get(f"/g/{self.anna_invite.token}/?lang=de")
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "committees/ballot.html")
        self.assertContains(r, "Sie stimmen als Anna Muster (Gruppe A).")
        self.assertContains(r, f'"token": "{self.anna_invite.token}"')
        self.assertContains(r, '"stream/"')
        strings = set(self._strings(r).values())
        for text in (
            "Ein Tipp gibt Ihre Stimme sofort und endgültig ab.",
            "Ihre Stimme ist endgültig, sobald Sie sie abgeben.",
            "Geheime Abstimmung",
            "Namentliche Abstimmung – Ihre Stimme wird mit Ihrem Namen gespeichert.",
            "Auch Ihr Schreibstil kann Rückschlüsse auf Sie erlauben.",
            "Ihre Stimme ist abgegeben.",
            "Sie sind für diese Abstimmung nicht stimmberechtigt.",
            "Bitte warten Sie auf die nächste Abstimmung.",
            "Verbindung unterbrochen – wird wiederhergestellt …",
            "Stimme abgeben", "Enthaltung", "Ja", "Nein", "Antworten",
        ):
            self.assertIn(text, strings)

    def test_member_page_english(self):
        self._start()
        r = self.client.get(f"/g/{self.anna_invite.token}/?lang=en")
        self.assertContains(r, "You are voting as Anna Muster (Gruppe A).")
        self.assertIn("One tap casts your vote immediately and for good.",
                      self._strings(r).values())

    def test_observer_page(self):
        self._start()
        r = self.client.get(f"/g/{self.obs_invite.token}/?lang=de")
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "committees/ballot.html")
        self.assertContains(r, "Sie nehmen als Beobachter*in teil und können nicht abstimmen.")
        self.assertNotContains(r, "Sie stimmen als")

    def test_entered_at_set_by_me_not_by_page(self):
        self.client.get(f"/g/{self.anna_invite.token}/me/")
        self.anna_invite.refresh_from_db()
        self.assertIsNone(self.anna_invite.entered_at)
        self._start()
        # Link scanners and previews fetch the page: that is no entering.
        self.assertEqual(self.client.get(f"/g/{self.anna_invite.token}/").status_code, 200)
        self.anna_invite.refresh_from_db()
        self.assertIsNone(self.anna_invite.entered_at)
        self.client.get(f"/g/{self.anna_invite.token}/me/")
        self.anna_invite.refresh_from_db()
        self.assertIsNotNone(self.anna_invite.entered_at)

    def test_invalid_link_has_no_script(self):
        services.remove_invite(self.anna_invite)
        r = self.client.get(f"/g/{self.anna_invite.token}/?lang=en")
        self.assertContains(r, "This link is not valid (any more).")
        self.assertNotContains(r, "/stream/")
        self.assertNotContains(r, "ballot-i18n")


class MeetingDefaultTitleTests(ApiBase):
    def create(self, scheduled_at):
        r = self.client.post(
            "/api/question-sets/",
            {"room": self.room.pk, "type": "meeting", "scheduled_at": scheduled_at},
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        return r.json()["title"]

    def test_blank_meeting_title_names_the_date(self):
        title = self.create("2030-01-15T09:00:00Z")
        self.assertEqual(title["de"], "Sitzung vom 15. Januar 2030")
        self.assertEqual(title["en"], "Meeting on January 15, 2030")

    def test_same_day_gets_a_suffix(self):
        self.create("2030-01-15T09:00:00Z")
        title = self.create("2030-01-15T13:00:00Z")
        self.assertEqual(title["de"], "Sitzung vom 15. Januar 2030 (2)")
        self.assertEqual(title["en"], "Meeting on January 15, 2030 (2)")


class AgendaGuardTests(MeetingFixture, ApiBase):
    def setUp(self):
        super().setUp()
        self.make_fixture(room=self.room)
        self.q = Question.objects.create(
            question_set=self.meeting, kind="open_text", text_de="A", text_en="A",
        )

    def test_delete_blocked_while_started(self):
        services.start_meeting(self.meeting)
        r = self.client.delete(f"/api/questions/{self.q.pk}/")
        self.assertEqual(r.status_code, 400)
        self.assertTrue(Question.objects.filter(pk=self.q.pk).exists())

    def test_everything_read_only_after_end(self):
        services.start_meeting(self.meeting)
        services.end_meeting(self.meeting)
        r = self.client.patch(
            f"/api/questions/{self.q.pk}/", {"text": {"de": "B"}}, format="json",
        )
        self.assertEqual(r.status_code, 400)
        r = self.client.post(
            "/api/questions/",
            {"question_set": self.meeting.pk, "kind": "open_text", "text": {"de": "C"}},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_lock_hook_blocks_text_but_not_position(self):
        from rooms import hooks
        hooks.question_lock_checks.append(
            lambda q: "locked" if q.pk == self.q.pk else None
        )
        self.addCleanup(hooks.question_lock_checks.pop)
        r = self.client.patch(
            f"/api/questions/{self.q.pk}/", {"text": {"de": "B"}}, format="json",
        )
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "locked"))
        r = self.client.patch(
            f"/api/questions/{self.q.pk}/", {"position": 5}, format="json",
        )
        self.assertEqual(r.status_code, 200)

    def test_deleting_meeting_with_substitution_from_question_works(self):
        a = self.member("Anna", self.ga)
        d = self.member("Dora", self.ga, "deputy", 1)
        services.add_substitution(self.meeting, a, d, from_question=self.q)
        self.meeting.delete()  # RESTRICT allows the cascade


class AgendaGuardDetailTests(MeetingFixture, ApiBase):
    def setUp(self):
        super().setUp()
        self.make_fixture(room=self.room)
        self.q = Question.objects.create(
            question_set=self.meeting, kind="open_text", text_de="A", text_en="A",
        )
        self.other = QuestionSet.objects.create(room=self.room, title="Other")

    def end(self):
        services.start_meeting(self.meeting)
        services.end_meeting(self.meeting)

    def assertBlocked(self, r, detail):
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["detail"], detail)

    def test_started_allows_edit_and_add(self):
        services.start_meeting(self.meeting)
        r = self.client.patch(
            f"/api/questions/{self.q.pk}/", {"text": {"de": "B"}}, format="json",
        )
        self.assertEqual(r.status_code, 200)
        r = self.client.post(
            "/api/questions/",
            {"question_set": self.meeting.pk, "kind": "open_text", "text": {"de": "C"}},
            format="json",
        )
        self.assertEqual(r.status_code, 201)

    def test_started_delete_and_move_out_blocked(self):
        services.start_meeting(self.meeting)
        msg = "Items cannot be deleted during a meeting."
        self.assertBlocked(self.client.delete(f"/api/questions/{self.q.pk}/"), msg)
        r = self.client.post(
            f"/api/questions/{self.q.pk}/move/", {"question_set": self.other.pk},
            format="json",
        )
        self.assertBlocked(r, msg)

    def test_ended_blocks_move_in_copy_reorders_add_after(self):
        msg = "The meeting has ended."
        src = Question.objects.create(
            question_set=self.other, kind="open_text", text_de="S", text_en="S",
        )
        self.end()
        r = self.client.post(
            f"/api/questions/{src.pk}/move/", {"question_set": self.meeting.pk},
            format="json",
        )
        self.assertBlocked(r, msg)
        r = self.client.post(
            f"/api/question-sets/{self.meeting.pk}/copy-questions/",
            {"question_ids": [src.pk]}, format="json",
        )
        self.assertBlocked(r, msg)
        r = self.client.post(
            f"/api/question-sets/{self.meeting.pk}/reorder-outline/",
            {"items": [{"type": "question", "id": self.q.pk}]}, format="json",
        )
        self.assertBlocked(r, msg)
        r = self.client.post(
            f"/api/question-sets/{self.meeting.pk}/reorder/",
            {"question_ids": [self.q.pk]}, format="json",
        )
        self.assertBlocked(r, msg)
        sc = Question.objects.create(
            question_set=self.meeting, kind="single_choice", text_de="X", text_en="X",
        )
        r = self.client.post(f"/api/questions/{sc.pk}/add-after/")
        self.assertBlocked(r, msg)

    def test_ended_blocks_section_writes(self):
        msg = "The meeting has ended."
        services.start_meeting(self.meeting)
        r = self.client.post(
            "/api/sections/",
            {"question_set": self.meeting.pk, "title": {"de": "S"}}, format="json",
        )
        self.assertEqual(r.status_code, 201)
        sid = r.json()["id"]
        services.end_meeting(self.meeting)
        r = self.client.post(
            "/api/sections/",
            {"question_set": self.meeting.pk, "title": {"de": "T"}}, format="json",
        )
        self.assertBlocked(r, msg)
        r = self.client.patch(
            f"/api/sections/{sid}/", {"title": {"de": "U"}}, format="json",
        )
        self.assertBlocked(r, msg)
        self.assertBlocked(self.client.delete(f"/api/sections/{sid}/"), msg)

    def test_locked_options_blocked_unchanged_resend_passes(self):
        from rooms import hooks
        from rooms.models import AnswerOption
        sc = Question.objects.create(
            question_set=self.meeting, kind="single_choice", text_de="X", text_en="X",
        )
        o1 = AnswerOption.objects.create(question=sc, text_de="a", text_en="a", position=0)
        o2 = AnswerOption.objects.create(question=sc, text_de="b", text_en="b", position=1)
        hooks.question_lock_checks.append(lambda q: "locked" if q.pk == sc.pk else None)
        self.addCleanup(hooks.question_lock_checks.pop)

        def opts(second="b"):
            return [
                {"id": o1.pk, "text": {"de": "a", "en": "a"}, "is_correct": False},
                {"id": o2.pk, "text": {"de": second, "en": second}, "is_correct": False},
            ]

        url = f"/api/questions/{sc.pk}/"
        r = self.client.patch(url, {"options": opts("changed")}, format="json")
        self.assertBlocked(r, "locked")
        r = self.client.patch(url, {"options": opts()}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

    def test_after_saved_hook_fires_on_create_and_update(self):
        from rooms import hooks
        seen = []
        hooks.after_question_saved.append(lambda q: seen.append(q.pk))
        self.addCleanup(hooks.after_question_saved.pop)
        r = self.client.post(
            "/api/questions/",
            {"question_set": self.meeting.pk, "kind": "open_text", "text": {"de": "C"}},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(seen, [r.json()["id"]])
        r = self.client.patch(
            f"/api/questions/{self.q.pk}/", {"text": {"de": "D"}}, format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(seen[-1], self.q.pk)


class MotionVersionTests(MeetingFixture, ApiBase):
    def setUp(self):
        super().setUp()
        self.make_fixture(room=self.room)
        self.q1 = Question.objects.create(
            question_set=self.meeting, kind="open_text", text_de="A", text_en="A",
            position=1,
        )
        self.q2 = Question.objects.create(
            question_set=self.meeting, kind="open_text", text_de="B", text_en="B",
            position=2,
        )

    def patch(self, q, payload):
        return self.client.patch(f"/api/questions/{q.pk}/", payload, format="json")

    def test_start_freezes_version_one(self):
        services.start_meeting(self.meeting)
        for q in (self.q1, self.q2):
            versions = list(q.motion_versions.all())
            self.assertEqual([v.number for v in versions], [1])
        self.assertEqual(self.q1.motion_versions.get().text_de, "A")

    def test_edit_after_start_creates_version_two(self):
        services.start_meeting(self.meeting)
        self.assertEqual(self.patch(self.q1, {"text": {"de": "A2"}}).status_code, 200)
        latest = self.q1.motion_versions.order_by("-number").first()
        self.assertEqual((latest.number, latest.text_de), (2, "A2"))
        self.assertEqual(self.patch(self.q1, {"position": 5}).status_code, 200)
        self.assertEqual(self.q1.motion_versions.count(), 2)

    def test_no_versions_before_start(self):
        self.assertEqual(self.patch(self.q1, {"text": {"de": "A2"}}).status_code, 200)
        self.assertEqual(self.q1.motion_versions.count(), 0)

    def test_item_added_during_meeting_gets_version_one(self):
        services.start_meeting(self.meeting)
        r = self.client.post(
            "/api/questions/",
            {"question_set": self.meeting.pk, "kind": "open_text", "text": {"de": "C"}},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        versions = list(Question.objects.get(pk=r.json()["id"]).motion_versions.all())
        self.assertEqual([(v.number, v.text_de) for v in versions], [(1, "C")])


class EligibilityTests(MeetingFixture, TestCase):
    def setUp(self):
        self.make_fixture()
        self.q1, self.q2, self.q3 = (
            Question.objects.create(
                question_set=self.meeting, kind="open_text", text_de=f"TOP {n}",
                position=n,
            )
            for n in (1, 2, 3)
        )
        self.anna = self.member("Anna", self.ga)
        self.bert = self.member("Bert", self.ga)
        self.dora = self.member("Dora", self.ga, role="deputy", rank=1)
        self.ben = self.member("Ben", self.gb)
        self.olga = self.member("Olga", self.obs_group)
        services.start_meeting(self.meeting)
        self.enter_all()

    def enter_all(self):
        self.meeting.invites.filter(entered_at__isnull=True).update(entered_at=timezone.now())

    def voters(self, question):
        return [m.name for m in eligibility.eligible_voters(self.meeting, question)]

    def invite(self, member):
        return self.meeting.invites.get(member=member)

    def test_agenda_and_numbers(self):
        self.assertEqual(eligibility.agenda(self.meeting), [self.q1, self.q2, self.q3])
        self.assertEqual(eligibility.numbers(self.meeting)[self.q3.pk], 3)

    def test_observers_and_deputies_hold_no_seat(self):
        self.assertEqual(self.voters(self.q1), ["Anna", "Bert", "Ben"])

    def test_not_entered_is_not_eligible(self):
        MeetingInvite.objects.filter(pk=self.invite(self.bert).pk).update(entered_at=None)
        self.assertEqual(self.voters(self.q1), ["Anna", "Ben"])

    def test_substitution_from_item(self):
        services.add_substitution(self.meeting, self.anna, self.dora, from_question=self.q2)
        self.enter_all()
        self.assertEqual(self.voters(self.q1), ["Anna", "Bert", "Ben"])
        self.assertEqual(self.voters(self.q2), ["Bert", "Dora", "Ben"])
        self.assertEqual(self.voters(self.q3), ["Bert", "Dora", "Ben"])
        holder = eligibility.seat_holder(self.meeting, self.anna, self.q2)
        self.assertEqual(holder, self.dora)

    def test_whole_meeting_substitution(self):
        services.add_substitution(self.meeting, self.anna, self.dora)
        self.enter_all()
        self.assertEqual(self.voters(self.q1), ["Bert", "Dora", "Ben"])

    def test_deputy_votes_in_seat_group(self):
        services.add_substitution(self.meeting, self.anna, self.dora)
        self.enter_all()
        groups = {m.name: m.group for m in eligibility.eligible_voters(self.meeting, self.q1)}
        self.assertEqual(groups["Dora"], self.ga)

    def test_removed_after_item(self):
        services.remove_invite(self.invite(self.bert), after_question=self.q1)
        self.assertIn("Bert", self.voters(self.q1))
        self.assertNotIn("Bert", self.voters(self.q2))
        services.remove_invite(self.invite(self.bert))
        self.assertNotIn("Bert", self.voters(self.q1))

    def test_is_present_for_without_invite(self):
        self.assertFalse(eligibility.is_present_for(None, self.meeting, self.q1))

    def test_lock_reason_follows_ballots(self):
        version = self.q1.motion_versions.get()
        ballot = Ballot.objects.create(question=self.q1, version=version, round=1, secret=True)
        self.assertEqual(versions.lock_reason(self.q1), "A vote on this item is open.")
        ballot.status = Ballot.Status.CLOSED
        ballot.save()
        self.assertIn("Reset the vote", versions.lock_reason(self.q1))
        ballot.status = Ballot.Status.DISCARDED
        ballot.discard_reason = Ballot.DiscardReason.RESET
        ballot.save()
        self.assertIsNone(versions.lock_reason(self.q1))

    def test_one_open_ballot_per_question(self):
        version = self.q1.motion_versions.get()
        Ballot.objects.create(question=self.q1, version=version, round=1, secret=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Ballot.objects.create(question=self.q1, version=version, round=2, secret=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Ballot.objects.create(
                question=self.q1, version=version, round=1, secret=True,
                status=Ballot.Status.CLOSED,
            )


class BallotBase(MeetingFixture, ApiBase):
    def setUp(self):
        super().setUp()
        self.make_fixture(room=self.room)
        self.q1 = Question.objects.create(
            question_set=self.meeting, kind="resolution", text_de="Beschluss", position=1,
        )
        self.q2 = Question.objects.create(
            question_set=self.meeting, kind="open_text", text_de="Freitext", position=2,
        )
        self.anna = self.member("Anna", self.ga)
        self.bert = self.member("Bert", self.ga)
        self.dora = self.member("Dora", self.ga, role="deputy", rank=1)
        self.ben = self.member("Ben", self.gb)
        self.olga = self.member("Olga", self.obs_group)
        services.start_meeting(self.meeting)
        self.meeting.invites.update(entered_at=timezone.now())

    def invite(self, member):
        return MeetingInvite.objects.select_related("meeting", "member").get(
            meeting=self.meeting, member=member,
        )

    def vote(self, member, ballot, answer):
        ballots.cast_vote(self.invite(member), ballot.pk, answer)

    def assertCode(self, code, fn, *args):
        with self.assertRaises(ValidationError) as ctx:
            fn(*args)
        self.assertEqual(ctx.exception.code, code)

    def group_result(self, result, group):
        return next(g for g in result["groups"] if g["group"] == group.pk)

    def election(self, n=3, max_votes=1, cumulate=False, named=False):
        q = Question.objects.create(
            question_set=self.meeting, kind="election", text_de="Wahl", position=3,
            max_votes=max_votes, cumulate=cumulate, named_vote=named,
        )
        opts = [
            AnswerOption.objects.create(question=q, text_de=f"K{i}", position=i)
            for i in range(n)
        ]
        return q, [o.pk for o in opts]

    def result(self, ballot):
        ballot.refresh_from_db()
        if ballot.status == Ballot.Status.OPEN:
            with self.captureOnCommitCallbacks(execute=True):
                ballot = ballots.close_ballot(ballot)
        return ballot.result


class BallotFlowTests(BallotBase):
    def test_secret_vote_counts_only_in_memory(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.assertTrue(ballot.secret)
        self.vote(self.anna, ballot, {"choice": "yes"})
        self.vote(self.ben, ballot, {"choice": "no"})
        self.assertFalse(NamedVote.objects.exists())
        fields = {f.name for f in BallotSeat._meta.get_fields()}
        self.assertEqual(fields, {"id", "ballot", "member", "group", "voted"})
        ballot.refresh_from_db()
        self.assertIsNone(ballot.result)
        with self.captureOnCommitCallbacks(execute=True):
            ballot = ballots.close_ballot(ballot)
        result = ballot.result
        self.assertEqual(ballot.status, Ballot.Status.CLOSED)
        self.assertEqual(result["total"]["counts"], {"yes": 1, "no": 1, "abstain": 0})
        self.assertEqual(result["voted"], 2)
        self.assertEqual(result["tally_sum"], 2)
        self.assertEqual(self.group_result(result, self.ga)["eligible"], 2)
        self.assertEqual([g["group"] for g in result["groups"]], [self.ga.pk, self.gb.pk])
        self.assertFalse(ballots.secret_tally.has(ballot.pk))

    def test_second_vote_rejected(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.vote(self.anna, ballot, {"choice": "yes"})
        self.assertCode("already_voted", self.vote, self.anna, ballot, {"choice": "no"})
        self.assertEqual(ballots.close_ballot(ballot).result["tally_sum"], 1)

    def test_not_eligible_and_observer(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.assertCode("not_eligible", self.vote, self.olga, ballot, {"choice": "yes"})

    def test_closed_and_invalid_link(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        services.remove_invite(self.invite(self.bert))
        self.assertCode("invalid_link", self.vote, self.bert, ballot, {"choice": "yes"})
        ballots.close_ballot(ballot)
        self.assertCode("closed", self.vote, self.anna, ballot, {"choice": "yes"})
        self.assertCode("not_open", ballots.close_ballot, ballot)

    def test_late_entry_gets_seat(self):
        MeetingInvite.objects.filter(meeting=self.meeting, member=self.bert).update(
            entered_at=None,
        )
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.assertEqual(ballot.seats.filter(group=self.ga).count(), 1)
        ballots.enter(self.invite(self.bert))
        self.assertIsNotNone(self.invite(self.bert).entered_at)
        self.assertEqual(ballot.seats.filter(group=self.ga).count(), 2)
        self.vote(self.bert, ballot, {"choice": "yes"})
        result = ballots.close_ballot(ballot).result
        self.assertEqual(self.group_result(result, self.ga)["eligible"], 2)
        self.assertEqual(result["total"]["counts"]["yes"], 1)

    def test_restart_discards_secret_ballot(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.vote(self.anna, ballot, {"choice": "yes"})
        with mock.patch("committees.tally.EPOCH", "other"):
            ballots.abort_stale(self.meeting)
            ballot.refresh_from_db()
            self.assertEqual(ballot.status, Ballot.Status.DISCARDED)
            self.assertEqual(ballot.discard_reason, Ballot.DiscardReason.RESTART)
            self.assertEqual(ballot.discard_comment, "Abgebrochen durch Serverneustart.")
            self.assertIsNotNone(ballot.discarded_at)
            self.assertEqual(ballot.seats.count(), 0)
            self.assertEqual(ballots.open_ballot(self.meeting, self.q1).round, 2)

    def test_restart_keeps_named_ballot(self):
        self.q1.named_vote = True
        self.q1.save()
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.assertFalse(ballot.secret)
        self.vote(self.anna, ballot, {"choice": "yes"})
        with mock.patch("committees.tally.EPOCH", "other"):
            ballots.abort_stale(self.meeting)
        ballot.refresh_from_db()
        self.assertEqual(ballot.status, Ballot.Status.OPEN)
        self.assertEqual(
            NamedVote.objects.get(ballot=ballot).answer, {"keys": ["yes"], "text": None},
        )
        result = ballots.close_ballot(ballot).result
        self.assertEqual(result["total"]["counts"], {"yes": 1, "no": 0, "abstain": 0})
        self.assertEqual(result["tally_sum"], 1)

    def test_reset_after_close_deletes_everything(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.vote(self.anna, ballot, {"choice": "yes"})
        ballots.close_ballot(ballot)
        r = self.client.patch(
            f"/api/questions/{self.q1.pk}/", {"text": {"de": "Neu"}}, format="json",
        )
        self.assertEqual(r.status_code, 400)
        ballot = ballots.reset_ballot(ballot, "Fehlbedienung")
        ballot.refresh_from_db()
        self.assertEqual(ballot.status, Ballot.Status.DISCARDED)
        self.assertEqual(ballot.discard_reason, Ballot.DiscardReason.RESET)
        self.assertIsNone(ballot.result)
        self.assertEqual(ballot.seats.count(), 0)
        self.assertEqual(ballot.discard_comment, "Fehlbedienung")
        r = self.client.patch(
            f"/api/questions/{self.q1.pk}/", {"text": {"de": "Neu"}}, format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(versions.current(self.q1).number, 2)

    def test_reset_open_discards_tally_on_commit(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.vote(self.anna, ballot, {"choice": "yes"})
        with self.captureOnCommitCallbacks(execute=True):
            ballots.reset_ballot(ballot, "")
        self.assertFalse(ballots.secret_tally.has(ballot.pk))

    def test_close_rollback_keeps_tally(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.vote(self.anna, ballot, {"choice": "yes"})
        self.vote(self.ben, ballot, {"choice": "no"})
        with mock.patch.object(
            BallotText.objects, "bulk_create", side_effect=RuntimeError("boom"),
        ), self.assertRaises(RuntimeError):
            ballots.close_ballot(ballot)
        ballot.refresh_from_db()
        self.assertEqual(ballot.status, Ballot.Status.OPEN)
        self.assertIsNone(ballot.result)
        self.assertTrue(ballots.secret_tally.has(ballot.pk))
        # The last vote closes the ballot automatically.
        with self.captureOnCommitCallbacks(execute=True):
            self.vote(self.bert, ballot, {"choice": "abstain"})
        ballot.refresh_from_db()
        self.assertEqual(ballot.status, Ballot.Status.CLOSED)
        result = ballot.result
        self.assertEqual(result["total"]["counts"], {"yes": 1, "no": 1, "abstain": 1})
        self.assertEqual((result["voted"], result["tally_sum"]), (3, 3))
        self.assertFalse(ballots.secret_tally.has(ballot.pk))

    def test_reset_comment_too_long(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.assertCode("invalid", ballots.reset_ballot, ballot, "x" * 1001)

    def test_one_open_ballot_per_meeting(self):
        ballots.open_ballot(self.meeting, self.q1)
        self.assertCode("other_open", ballots.open_ballot, self.meeting, self.q2)

    def test_open_guards(self):
        draft = QuestionSet.objects.create(
            room=self.room, title="Neu", type=QuestionSet.SetType.MEETING,
        )
        q = Question.objects.create(question_set=draft, kind="resolution", text_de="X")
        self.assertCode("not_started", ballots.open_ballot, draft, q)
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.assertEqual(self.meeting.meeting_control.current_question, self.q1)
        ballots.close_ballot(ballot)
        self.assertCode("already_voted_on", ballots.open_ballot, self.meeting, self.q1)

    def test_freetext_secret_texts_written_at_close(self):
        ballot = ballots.open_ballot(self.meeting, self.q2)
        self.vote(self.anna, ballot, {"text": "  Erstens  "})
        self.vote(self.ben, ballot, {"text": "Zweitens"})
        self.assertEqual(BallotText.objects.count(), 0)
        ballot = ballots.close_ballot(ballot)
        self.assertEqual(
            sorted(BallotText.objects.values_list("text", flat=True)), ["Erstens", "Zweitens"],
        )
        self.assertEqual(ballot.result["total"]["counts"], {"text": 2, "abstain": 0})
        self.assertTrue(ballots.release_texts(ballot).texts_released)
        resolution = ballots.close_ballot(ballots.open_ballot(self.meeting, self.q1))
        self.assertCode("invalid", ballots.release_texts, resolution)

    def test_end_meeting_blocked_while_open(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.assertCode("vote_open", services.end_meeting, self.meeting)
        ballots.close_ballot(ballot)
        services.end_meeting(self.meeting)
        self.assertEqual(self.meeting.meeting_state, QuestionSet.MeetingState.ENDED)

    def test_multiple_choice_validation(self):
        q3 = Question.objects.create(
            question_set=self.meeting, kind="multiple_choice", text_de="MC", position=3,
        )
        o1 = AnswerOption.objects.create(question=q3, text_de="A", position=1)
        o2 = AnswerOption.objects.create(question=q3, text_de="B", position=2)
        other = AnswerOption.objects.create(question=self.q2, text_de="X")
        for bad in (
            {"options": []}, {"options": [o1.pk, o1.pk]}, {"options": [other.pk]},
            {"options": [True]}, {"choice": "yes"}, {}, "x",
        ):
            self.assertCode("invalid", ballots.parse_answer, q3, bad)
        self.assertEqual(
            ballots.parse_answer(q3, {"options": [o2.pk, o1.pk]}),
            ([f"opt:{o2.pk}", f"opt:{o1.pk}"], None),
        )
        self.assertEqual(ballots.parse_answer(q3, {"choice": "abstain"}), (["abstain"], None))
        self.assertCode("invalid", ballots.parse_answer, self.q2, {"text": "   "})
        self.assertCode("invalid", ballots.parse_answer, self.q2, {"text": "x" * 2001})
        self.assertCode("invalid", ballots.parse_answer, self.q1, {"choice": "maybe"})

    def test_single_choice_zero_counts(self):
        q3 = Question.objects.create(
            question_set=self.meeting, kind="single_choice", text_de="SC", position=3,
        )
        o1 = AnswerOption.objects.create(question=q3, text_de="A", position=1)
        o2 = AnswerOption.objects.create(question=q3, text_de="B", position=2)
        ballot = ballots.open_ballot(self.meeting, q3)
        self.vote(self.anna, ballot, {"option": o1.pk})
        result = ballots.close_ballot(ballot).result
        self.assertEqual(
            result["total"]["counts"], {f"opt:{o1.pk}": 1, f"opt:{o2.pk}": 0, "abstain": 0},
        )


def _keys(value):
    """All dict keys in a nested payload."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


class AutoCloseTests(BallotBase):
    def vote_all(self, ballot, upto=None):
        members = [seat.member for seat in ballot.seats.select_related("member")]
        for member in members[:upto]:
            self.vote(member, ballot, {"choice": "yes"})
        return members

    def test_secret_closes_when_all_voted(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        with self.captureOnCommitCallbacks(execute=True):
            members = self.vote_all(ballot)
        ballot.refresh_from_db()
        self.assertEqual(ballot.status, Ballot.Status.CLOSED)
        self.assertTrue(ballot.closed_automatically)
        self.assertEqual(ballot.result["total"]["counts"]["yes"], len(members))
        self.assertEqual(ballot.result["voted"], len(members))
        self.assertFalse(ballots.secret_tally.has(ballot.pk))
        self.assertEqual(SealLink.objects.filter(kind="result", ballot=ballot).count(), 1)
        self.assertTrue(payloads.manager_payload(self.meeting)["item"]["ballot"]["closed_automatically"])

    def test_named_closes_when_all_voted(self):
        self.q1.named_vote = True
        self.q1.save()
        ballot = ballots.open_ballot(self.meeting, self.q1)
        members = self.vote_all(ballot)
        ballot.refresh_from_db()
        self.assertEqual(ballot.status, Ballot.Status.CLOSED)
        self.assertTrue(ballot.closed_automatically)
        self.assertEqual(ballot.result["total"]["counts"]["yes"], len(members))

    def test_partial_stays_open(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.vote_all(ballot, upto=ballot.seats.count() - 1)
        ballot.refresh_from_db()
        self.assertEqual(ballot.status, Ballot.Status.OPEN)
        self.assertFalse(ballot.closed_automatically)

    def test_manual_close_is_not_automatic(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.vote(self.anna, ballot, {"choice": "yes"})
        ballots.close_ballot(ballot)
        ballot.refresh_from_db()
        self.assertFalse(ballot.closed_automatically)

    def test_latecomer_cannot_vote_after_auto_close(self):
        MeetingInvite.objects.filter(meeting=self.meeting, member=self.bert).update(
            entered_at=None,
        )
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.vote_all(ballot)
        ballot.refresh_from_db()
        self.assertEqual(ballot.status, Ballot.Status.CLOSED)
        ballots.enter(self.invite(self.bert))
        self.assertFalse(ballot.seats.filter(member=self.bert).exists())
        self.assertCode("closed", self.vote, self.bert, ballot, {"choice": "yes"})

    def test_last_two_votes_close_exactly_once(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        members = [seat.member for seat in ballot.seats.select_related("member")]
        for member in members[:-2]:
            self.vote(member, ballot, {"choice": "yes"})
        self.vote(members[-2], ballot, {"choice": "no"})
        self.vote(members[-1], ballot, {"choice": "yes"})
        # A would-be simultaneous voter arriving afterwards sees it closed.
        self.assertCode("closed", self.vote, members[-1], ballot, {"choice": "yes"})
        self.assertEqual(SealLink.objects.filter(kind="result", ballot=ballot).count(), 1)
        ballot.refresh_from_db()
        self.assertEqual(ballot.result["voted"], len(members))

    def test_failed_auto_close_keeps_vote_and_ballot_open(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        members = [seat.member for seat in ballot.seats.select_related("member")]
        for member in members[:-1]:
            self.vote(member, ballot, {"choice": "yes"})
        with mock.patch.object(
            BallotText.objects, "bulk_create", side_effect=RuntimeError("boom"),
        ), self.assertLogs("committees.ballots", level="WARNING") as logs:
            self.vote(members[-1], ballot, {"choice": "yes"})
        self.assertEqual(len(logs.records), 1)
        self.assertIn(str(ballot.pk), logs.output[0])
        self.assertNotIn("choice", logs.output[0])
        self.assertIsNone(logs.records[0].exc_info)
        ballot.refresh_from_db()
        self.assertEqual(ballot.status, Ballot.Status.OPEN)
        self.assertFalse(ballot.seats.filter(voted=False).exists())
        snapshot = ballots.secret_tally.snapshot(ballot.pk)
        self.assertEqual(sum(g["ballots"] for g in snapshot["groups"].values()), len(members))
        self.assertCode("already_voted", self.vote, members[-1], ballot, {"choice": "yes"})
        with self.captureOnCommitCallbacks(execute=True):
            closed = ballots.close_ballot(ballot)
        self.assertEqual(closed.result["tally_sum"], len(members))

    def test_trial_auto_closes_without_seal(self):
        MeetingControl.objects.update_or_create(meeting=self.meeting, defaults={"trial": True})
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.vote_all(ballot)
        ballot.refresh_from_db()
        self.assertEqual(ballot.status, Ballot.Status.CLOSED)
        self.assertTrue(ballot.closed_automatically)
        self.assertFalse(SealLink.objects.exists())


class PayloadTests(BallotBase):
    """Meeting snapshots (public beamer/ballot, manager console)."""

    def payloads(self):
        from . import payloads

        return payloads.public_payload(self.meeting), payloads.manager_payload(self.meeting)

    def test_no_counts_before_close(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.vote(self.anna, ballot, {"choice": "yes"})
        self.vote(self.ben, ballot, {"choice": "no"})
        for payload in self.payloads():
            item_ballot = payload["item"]["ballot"]
            self.assertEqual(item_ballot["status"], "open")
            self.assertIsNone(item_ballot["result"])
            self.assertNotIn("counts", _keys(payload))
            self.assertEqual(item_ballot["progress"]["voted"], 2)
            self.assertEqual(item_ballot["progress"]["eligible"], 3)
        public, manager = self.payloads()
        self.assertEqual(manager["open_ballot"], ballot.pk)
        self.assertEqual(public["item"]["label"], "1")
        self.assertEqual(public["item"]["text"], "Beschluss")
        groups = public["item"]["ballot"]["progress"]["groups"]
        self.assertEqual(
            [(g["name"], g["voted"], g["eligible"]) for g in groups],
            [("Gruppe A", 1, 2), ("Gruppe B", 1, 1)],
        )
        ballots.close_ballot(ballot)
        public, _ = self.payloads()
        result = public["item"]["ballot"]["result"]
        self.assertEqual(result["total"]["counts"], {"yes": 1, "no": 1, "abstain": 0})
        self.assertEqual(result["groups"][0]["name"], "Gruppe A")

    def test_texts_hidden_until_released(self):
        ballot = ballots.open_ballot(self.meeting, self.q2)
        self.vote(self.anna, ballot, {"text": "Erstens"})
        self.vote(self.ben, ballot, {"text": "Zweitens"})
        public, manager = self.payloads()
        self.assertIsNone(public["item"]["ballot"]["texts"])
        self.assertIsNone(manager["texts"])
        ballot = ballots.close_ballot(ballot)
        public, manager = self.payloads()
        self.assertIsNone(public["item"]["ballot"]["texts"])
        self.assertEqual(len(manager["texts"]), 2)
        ballots.release_texts(ballot)
        public, manager = self.payloads()
        self.assertEqual(len(public["item"]["ballot"]["texts"]), 2)
        self.assertEqual(len(manager["texts"]), 2)
        self.assertEqual(
            sorted(t["text"] for t in public["item"]["ballot"]["texts"]),
            ["Erstens", "Zweitens"],
        )

    def test_named_texts_carry_no_names(self):
        import json

        self.q2.named_vote = True
        self.q2.save()
        ballot = ballots.open_ballot(self.meeting, self.q2)
        self.vote(self.anna, ballot, {"text": "Erstens"})
        self.vote(self.ben, ballot, {"text": "Zweitens"})
        ballots.release_texts(ballots.close_ballot(ballot))
        public, manager = self.payloads()
        dumped = json.dumps([public, manager["texts"], manager["items"]])
        self.assertIn("Erstens", dumped)
        for name in ("Anna", "Ben", "Bert", "Dora", "Olga"):
            self.assertNotIn(name, dumped)

    def test_presence_status(self):
        from .presence import presence

        invite = self.invite(self.anna)
        presence.connect(invite.pk)
        self.assertEqual(presence.status(invite.pk), (True, None))
        _, manager = self.payloads()
        row = next(a for a in manager["attendance"] if a["invite"] == invite.pk)
        self.assertTrue(row["connected"])
        self.assertIsNone(row["disconnected_since"])
        presence.disconnect(invite.pk)
        _, manager = self.payloads()
        row = next(a for a in manager["attendance"] if a["invite"] == invite.pk)
        self.assertFalse(row["connected"])
        self.assertIsNotNone(row["disconnected_since"])
        self.assertEqual(row["name"], "Anna")
        self.assertEqual(row["group"], "Gruppe A")
        self.assertTrue(row["entered"])
        olga = next(a for a in manager["attendance"] if a["name"] == "Olga")
        self.assertTrue(olga["observer"])


    def test_mutations_broadcast_after_commit(self):
        with mock.patch("committees.live.broadcast_meeting") as broadcast:
            with self.captureOnCommitCallbacks(execute=False) as callbacks:
                ballot = ballots.open_ballot(self.meeting, self.q1)
            broadcast.assert_not_called()
            for callback in callbacks:
                callback()
            broadcast.assert_called_with(self.meeting, debounce=False)
            broadcast.reset_mock()
            with self.captureOnCommitCallbacks(execute=True):
                self.vote(self.anna, ballot, {"choice": "yes"})
            self.assertEqual(broadcast.call_args.kwargs, {"debounce": True})
            for action in (
                lambda: ballots.close_ballot(ballot),
                lambda: services.remove_invite(self.invite(self.bert)),
                lambda: services.readmit_invite(self.invite(self.bert)),
                lambda: services.end_meeting(self.meeting),
            ):
                broadcast.reset_mock()
                with self.captureOnCommitCallbacks(execute=True):
                    action()
                broadcast.assert_called()


class MemberStreamTests(TestCase):
    # Own class with a single test: the stream view closes the DB connection
    # (connections.close_all), which breaks the test transaction for any
    # test that would run after it in the same class.
    def test_member_stream_rejects_invalid_token(self):
        self.assertEqual(self.client.get("/g/xxx/stream/").status_code, 404)


class BallotApiTests(BallotBase):
    def url(self, suffix):
        return f"/api/meetings/{self.meeting.pk}/{suffix}"

    def token(self, member):
        return self.invite(member).token

    def cast(self, member, ballot_id, answer):
        return self.client.post(
            f"/g/{self.token(member)}/vote/", {"ballot": ballot_id, "answer": answer},
            format="json",
        )

    def open_resolution(self):
        resp = self.client.post(self.url(f"items/{self.q1.pk}/open/"))
        self.assertEqual(resp.status_code, 201)
        return resp.data["open_ballot"]

    def test_full_flow_via_api(self):
        resp = self.client.post(self.url("show/"), {"question": self.q1.pk}, format="json")
        self.assertEqual(resp.status_code, 200)
        bid = self.open_resolution()
        self.assertEqual(self.cast(self.anna, bid, {"choice": "yes"}).status_code, 200)
        self.assertEqual(self.cast(self.ben, bid, {"choice": "no"}).status_code, 200)
        resp = self.client.post(self.url(f"ballots/{bid}/close/"))
        self.assertEqual(resp.status_code, 200)
        resp = self.client.get(self.url("control/"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('"yes": 1', json.dumps(resp.data))
        resp = self.client.post(self.url("show/"), {"question": None}, format="json")
        self.assertEqual(resp.status_code, 200)

    def test_show_foreign_question_400(self):
        other = QuestionSet.objects.create(
            room=self.room, title="X", type=QuestionSet.SetType.MEETING,
        )
        q = Question.objects.create(question_set=other, kind="open_text", text_de="x")
        resp = self.client.post(self.url("show/"), {"question": q.pk}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_foreign_manager_404(self):
        for method, suffix in (
            ("get", "control/"), ("post", "show/"),
            ("post", f"items/{self.q1.pk}/open/"), ("post", "ballots/1/close/"),
        ):
            resp = getattr(self.foreign, method)(self.url(suffix), {}, format="json")
            self.assertEqual(resp.status_code, 404, suffix)

    def test_manager_error_has_code(self):
        self.open_resolution()
        resp = self.client.post(self.url(f"items/{self.q2.pk}/open/"))
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "other_open")
        self.assertIn("detail", resp.data)

    def test_vote_codes(self):
        bid = self.open_resolution()
        self.assertEqual(self.cast(self.anna, bid, {"choice": "yes"}).status_code, 200)
        resp = self.cast(self.anna, bid, {"choice": "no"})
        self.assertEqual((resp.status_code, resp.json()["code"]), (409, "already_voted"))
        resp = self.cast(self.olga, bid, {"choice": "yes"})
        self.assertEqual((resp.status_code, resp.json()["code"]), (403, "not_eligible"))
        resp = self.cast(self.bert, bid, {"choice": "maybe"})
        self.assertEqual((resp.status_code, resp.json()["code"]), (400, "invalid"))
        resp = self.client.post(
            f"/g/{self.token(self.bert)}/vote/", "{not json", content_type="application/json",
        )
        self.assertEqual((resp.status_code, resp.json()["code"]), (400, "invalid"))
        self.assertEqual(resp["Cache-Control"], "no-store")
        self.client.post(self.url(f"ballots/{bid}/close/"))
        resp = self.cast(self.bert, bid, {"choice": "yes"})
        self.assertEqual((resp.status_code, resp.json()["code"]), (409, "closed"))
        resp = self.client.post(
            "/g/nonsense/vote/", {"ballot": bid, "answer": {}}, format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_me_reports_voted(self):
        bid = self.open_resolution()
        url = f"/g/{self.token(self.anna)}/me/"
        data = self.client.get(url).json()
        self.assertEqual(
            data,
            {"state": "active", "observer": False, "ballot": bid, "eligible": True, "voted": False},
        )
        self.cast(self.anna, bid, {"choice": "yes"})
        resp = self.client.get(url)
        self.assertTrue(resp.json()["voted"])
        self.assertEqual(resp["Cache-Control"], "no-store")
        obs = self.client.get(f"/g/{self.token(self.olga)}/me/").json()
        self.assertEqual((obs["observer"], obs["eligible"]), (True, False))
        self.assertEqual(self.client.get("/g/nonsense/me/").status_code, 404)

    def test_vote_response_never_echoes_answer(self):
        bid = self.open_resolution()
        resp = self.cast(self.anna, bid, {"choice": "yes"})
        self.assertNotIn("yes", resp.content.decode())
        resp = self.cast(self.anna, bid, {"choice": "yes"})
        self.assertNotIn("yes", resp.content.decode())

    def test_reset_and_release_texts(self):
        bid = self.open_resolution()
        resp = self.client.post(
            self.url(f"ballots/{bid}/reset/"), {"comment": "oops"}, format="json",
        )
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(self.url(f"ballots/{bid}/release-texts/"))
        self.assertEqual((resp.status_code, resp.data["code"]), (400, "not_closed"))


class FindingTests(BallotBase):
    def url(self, ballot):
        return f"/api/meetings/{self.meeting.pk}/ballots/{ballot.pk}/finding/"

    def closed(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.vote(self.anna, ballot, {"choice": "yes"})
        with self.captureOnCommitCallbacks(execute=True):
            return ballots.close_ballot(ballot)

    def post(self, ballot, value):
        return self.client.post(self.url(ballot), {"finding": value}, format="json")

    def test_set_finding_on_closed_ballot(self):
        ballot = self.closed()
        self.assertEqual(self.post(ballot, "adopted").status_code, 200)
        ballot.refresh_from_db()
        self.assertEqual(ballot.finding, "adopted")
        resp = self.post(ballot, "")
        self.assertEqual(resp.status_code, 200)
        ballot.refresh_from_db()
        self.assertEqual(ballot.finding, "")

    def test_finding_needs_closed_ballot(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        resp = self.post(ballot, "adopted")
        self.assertEqual((resp.status_code, resp.data["code"]), (400, "not_closed"))
        ballots.reset_ballot(ballot, "")
        resp = self.post(ballot, "adopted")
        self.assertEqual((resp.status_code, resp.data["code"]), (400, "not_closed"))

    def test_finding_invalid_value(self):
        ballot = self.closed()
        resp = self.post(ballot, "maybe")
        self.assertEqual((resp.status_code, resp.data["code"]), (400, "invalid"))

    def test_finding_after_end_allowed(self):
        ballot = self.closed()
        services.end_meeting(self.meeting)
        self.assertEqual(self.post(ballot, "rejected").status_code, 200)
        ballot.refresh_from_db()
        self.assertEqual(ballot.finding, "rejected")

    def test_finding_in_public_payload(self):
        ballot = self.closed()
        self.post(ballot, "adopted")
        self.client.post(
            f"/api/meetings/{self.meeting.pk}/show/", {"question": self.q1.pk}, format="json",
        )
        public = payloads.public_payload(self.meeting)
        self.assertEqual(public["item"]["ballot"]["finding"], "adopted")
        self.assertEqual(public["item"]["ballot"]["result"]["voted"], 1)
        self.assertEqual(public["item"]["ballot"]["result"]["tally_sum"], 1)


class StatusTests(BallotBase):
    def run_command(self):
        import io

        from django.core.management import call_command

        out = io.StringIO()
        code = 0
        try:
            call_command("committee_status", stdout=out)
        except SystemExit as exc:
            code = exc.code
        return json.loads(out.getvalue()), code

    def test_command_exit_zero_without_open_secret_ballot(self):
        data, code = self.run_command()
        self.assertEqual(data, {"meetings_running": 1, "secret_ballots_open": 0})
        self.assertEqual(code, 0)

    def test_command_exit_one_with_open_secret_ballot(self):
        ballots.open_ballot(self.meeting, self.q1)
        data, code = self.run_command()
        self.assertEqual(data["secret_ballots_open"], 1)
        self.assertEqual(code, 1)

    def test_prometheus_lines_and_admin_stats(self):
        with override_settings(METRICS_TOKEN="secret"):
            text = self.client.get("/metrics", HTTP_AUTHORIZATION="Bearer secret").content.decode()
        self.assertIn("abstimmbar_committee_meetings_running 1", text)
        self.assertIn("abstimmbar_committee_secret_ballots_open 0", text)


class RemovedAfterItemTests(BallotBase):
    """A member removed "after item n" keeps voting up to and including n."""

    def test_votes_at_that_item_not_after(self):
        services.remove_invite(self.invite(self.bert), after_question=self.q1)
        self.assertEqual(services.invite_state(self.invite(self.bert)), "active")
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.assertTrue(ballot.seats.filter(member=self.bert).exists())
        resp = self.client.get(f"/g/{self.invite(self.bert).token}/me/").json()
        self.assertEqual((resp["state"], resp["eligible"]), ("active", True))
        resp = self.client.get(f"/g/{self.invite(self.bert).token}/")
        self.assertFalse(resp.context["invalid"])
        self.vote(self.bert, ballot, {"choice": "yes"})
        result = ballots.close_ballot(ballot).result
        self.assertEqual(self.group_result(result, self.ga)["eligible"], 2)
        self.assertEqual(self.group_result(result, self.ga)["voted"], 1)

        ballot = ballots.open_ballot(self.meeting, self.q2)
        self.assertFalse(ballot.seats.filter(member=self.bert).exists())
        self.assertEqual(services.invite_state(self.invite(self.bert)), "removed")
        self.assertCode("invalid_link", self.vote, self.bert, ballot, {"text": "x"})

    def test_vote_via_api_at_that_item(self):
        services.remove_invite(self.invite(self.bert), after_question=self.q1)
        ballot = ballots.open_ballot(self.meeting, self.q1)
        resp = self.client.post(
            f"/g/{self.invite(self.bert).token}/vote/",
            {"ballot": ballot.pk, "answer": {"choice": "no"}}, format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_removed_after_item_off_agenda_counts_from_start(self):
        services.remove_invite(self.invite(self.bert), after_question=self.q2)
        other = QuestionSet.objects.create(room=self.room, title="Other")
        Question.objects.filter(pk=self.q2.pk).update(question_set=other)
        self.assertEqual(services.invite_state(self.invite(self.bert)), "removed")
        self.assertNotIn(self.bert, eligibility.eligible_voters(self.meeting, self.q1))


class CourseTests(EligibilityTests):
    """Eligibility follows the meeting's actual course: items already voted
    on in the order they were opened, the rest in agenda order."""

    def vote_on(self, question):
        ballot = ballots.open_ballot(self.meeting, question)
        ballots.close_ballot(ballot)
        return ballot

    def test_out_of_order_departure_stays_gone(self):
        # TOP 3 is called before TOP 2; Bert leaves after TOP 3.
        self.vote_on(self.q3)
        services.remove_invite(self.invite(self.bert), after_question=self.q3)
        self.assertNotIn("Bert", self.voters(self.q2))
        self.assertIn("Bert", self.voters(self.q3))

    def test_planned_departure_not_yet_reached(self):
        # Bert will leave after TOP 3; TOP 2 is still before it.
        self.vote_on(self.q1)
        services.remove_invite(self.invite(self.bert), after_question=self.q3)
        self.assertIn("Bert", self.voters(self.q2))

    def test_resolution_added_to_earlier_top_after_departure(self):
        self.vote_on(self.q1)
        self.vote_on(self.q2)
        services.remove_invite(self.invite(self.bert), after_question=self.q2)
        late = services.add_resolution(self.meeting, "Nachtrag", None, False)
        Question.objects.filter(pk=late.pk).update(position=0)
        self.assertNotIn("Bert", self.voters(late))

    def test_substitution_keeps_seat_for_later_item_on_earlier_top(self):
        self.vote_on(self.q1)
        services.add_substitution(self.meeting, self.anna, self.dora, from_question=self.q2)
        self.enter_all()
        self.vote_on(self.q2)
        late = services.add_resolution(self.meeting, "Nachtrag", None, False)
        Question.objects.filter(pk=late.pk).update(position=0)
        self.assertEqual(self.voters(late), ["Bert", "Dora", "Ben"])

    def test_reset_revote_keeps_its_place(self):
        # TOP 2 was voted before TOP 1; Bert left after TOP 1. A re-vote of
        # TOP 2 keeps its earlier place, so Bert may vote again.
        first = self.vote_on(self.q2)
        self.vote_on(self.q1)
        services.remove_invite(self.invite(self.bert), after_question=self.q1)
        ballots.reset_ballot(first, "Fehler")
        again = ballots.open_ballot(self.meeting, self.q2)
        self.assertTrue(again.seats.filter(member=self.bert).exists())
        self.assertNotIn("Bert", self.voters(self.q3))

    def test_invite_state_follows_course(self):
        self.vote_on(self.q3)
        services.remove_invite(self.invite(self.bert), after_question=self.q3)
        self.assertEqual(services.invite_state(self.invite(self.bert), self.q2), "removed")
        self.assertEqual(services.invite_state(self.invite(self.bert), self.q3), "active")


class DeputyPresenceTests(EligibilityTests):
    """Deferred Task-4 cases: a seat held by a deputy is empty when the
    deputy is not present — the absent member never falls back in."""

    def test_deputy_removed_leaves_seat_empty(self):
        services.add_substitution(self.meeting, self.anna, self.dora)
        self.enter_all()
        services.remove_invite(self.invite(self.dora))
        self.assertEqual(self.voters(self.q1), ["Bert", "Ben"])

    def test_deputy_not_entered_leaves_seat_empty(self):
        services.add_substitution(self.meeting, self.anna, self.dora, from_question=self.q2)
        self.assertEqual(self.voters(self.q1), ["Anna", "Bert", "Ben"])
        self.assertEqual(self.voters(self.q2), ["Bert", "Ben"])

    def test_substitution_from_item_off_agenda_covers_whole_meeting(self):
        services.add_substitution(self.meeting, self.anna, self.dora, from_question=self.q3)
        self.enter_all()
        other = QuestionSet.objects.create(room=self.room, title="Other")
        Question.objects.filter(pk=self.q3.pk).update(question_set=other)
        self.assertEqual(self.voters(self.q1), ["Bert", "Dora", "Ben"])


class ConsoleGuardTests(BallotBase):
    def url(self, suffix):
        return f"/api/meetings/{self.meeting.pk}/{suffix}"

    def post(self, suffix, data=None):
        return self.client.post(self.url(suffix), data or {}, format="json")

    def test_show_blocked_while_another_vote_is_open(self):
        self.assertEqual(self.post(f"items/{self.q1.pk}/open/").status_code, 201)
        for question in (self.q2.pk, None):
            resp = self.post("show/", {"question": question})
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(resp.data["code"], "vote_open")
            self.assertEqual(resp.data["detail"], "Another vote is still open.")
        self.assertEqual(self.meeting.meeting_control.current_question, self.q1)
        self.assertEqual(self.post("show/", {"question": self.q1.pk}).status_code, 200)

    def test_show_reset_release_need_running_meeting(self):
        ballot = ballots.open_ballot(self.meeting, self.q2)
        self.vote(self.anna, ballot, {"text": "A"})
        ballots.close_ballot(ballot)
        services.end_meeting(self.meeting)
        for suffix, data in (
            ("show/", {"question": self.q1.pk}),
            (f"ballots/{ballot.pk}/reset/", {"comment": ""}),
            (f"ballots/{ballot.pk}/release-texts/", None),
        ):
            resp = self.post(suffix, data)
            self.assertEqual(resp.status_code, 400, suffix)
            self.assertEqual(resp.data["code"], "not_started", suffix)
            self.assertEqual(resp.data["detail"], "The meeting is not running.")
        ballot.refresh_from_db()
        self.assertEqual(ballot.status, Ballot.Status.CLOSED)
        self.assertFalse(ballot.texts_released)

    def test_show_in_draft_meeting(self):
        draft = QuestionSet.objects.create(
            room=self.room, title="Neu", type=QuestionSet.SetType.MEETING,
        )
        q = Question.objects.create(question_set=draft, kind="resolution", text_de="X")
        resp = self.client.post(
            f"/api/meetings/{draft.pk}/show/", {"question": q.pk}, format="json",
        )
        self.assertEqual((resp.status_code, resp.data["code"]), (400, "not_started"))

    def test_texts_stored_in_fixed_group_order(self):
        ballot = ballots.open_ballot(self.meeting, self.q2)
        self.vote(self.ben, ballot, {"text": "B zuerst"})
        self.vote(self.anna, ballot, {"text": "A danach"})
        ballots.close_ballot(ballot)
        groups = list(BallotText.objects.order_by("id").values_list("group_id", flat=True))
        self.assertEqual(groups, [self.ga.pk, self.gb.pk])


class ReferencedEditTests(BallotBase):
    """Deletes and edits that would break vote data or meeting references
    answer 400 instead of failing (500) or silently cascading."""

    def draft(self):
        meeting = QuestionSet.objects.create(
            room=self.room, title="Entwurf", type=QuestionSet.SetType.MEETING,
        )
        q = Question.objects.create(question_set=meeting, kind="resolution", text_de="X")
        return meeting, q

    def test_delete_item_referenced_by_substitution_or_removal(self):
        meeting, q = self.draft()
        services.add_substitution(meeting, self.anna, self.dora, from_question=q)
        resp = self.client.delete(f"/api/questions/{q.pk}/")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json()["detail"],
            "This item is still referenced (substitution or attendance) and cannot be deleted.",
        )
        MeetingSubstitution.objects.filter(meeting=meeting).delete()
        services.ensure_invites(meeting)
        services.remove_invite(meeting.invites.get(member=self.bert), after_question=q)
        self.assertEqual(self.client.delete(f"/api/questions/{q.pk}/").status_code, 400)
        self.assertTrue(Question.objects.filter(pk=q.pk).exists())

    def test_move_of_referenced_item_blocked(self):
        meeting, q = self.draft()
        services.add_substitution(meeting, self.anna, self.dora, from_question=q)
        other = QuestionSet.objects.create(
            room=self.room, title="Other", type=QuestionSet.SetType.MEETING,
        )
        resp = self.client.post(
            f"/api/questions/{q.pk}/move/", {"question_set": other.pk}, format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("cannot be moved", resp.json()["detail"])
        q.refresh_from_db()
        self.assertEqual(q.question_set_id, meeting.pk)
        unreferenced = Question.objects.create(
            question_set=meeting, kind="resolution", text_de="Y",
        )
        resp = self.client.post(
            f"/api/questions/{unreferenced.pk}/move/", {"question_set": other.pk},
            format="json",
        )
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_delete_group_that_took_part_in_votes(self):
        ballots.close_ballot(ballots.open_ballot(self.meeting, self.q1))
        services.end_meeting(self.meeting)
        CommitteeMember.objects.filter(group=self.gb).update(group=self.ga)
        resp = self.client.delete(f"/api/committee-groups/{self.gb.pk}/")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json()["detail"], "This group took part in votes and cannot be deleted.",
        )
        self.assertTrue(CommitteeGroup.objects.filter(pk=self.gb.pk).exists())

    def test_delete_member_who_took_part_in_votes(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        ballots.close_ballot(ballot)
        services.end_meeting(self.meeting)
        resp = self.client.delete(f"/api/committee-members/{self.ben.pk}/")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(
            resp.json()["detail"], "This member took part in votes and cannot be deleted.",
        )
        self.assertTrue(BallotSeat.objects.filter(member=self.ben).exists())
        # A deputy without seats can go.
        resp = self.client.delete(f"/api/committee-members/{self.dora.pk}/")
        self.assertEqual(resp.status_code, 204)

    def test_delete_member_with_named_vote(self):
        self.q1.named_vote = True
        self.q1.save()
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.vote(self.ben, ballot, {"choice": "yes"})
        BallotSeat.objects.filter(member=self.ben).delete()  # only the named vote is left
        resp = self.client.delete(f"/api/committee-members/{self.ben.pk}/")
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(NamedVote.objects.filter(member=self.ben).exists())

    def test_delete_member_after_reset_allowed(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        ballots.reset_ballot(ballot, "")
        resp = self.client.delete(f"/api/committee-members/{self.dora.pk}/")
        self.assertEqual(resp.status_code, 204)

    def test_role_or_group_change_blocked_while_running(self):
        url = f"/api/committee-members/{self.bert.pk}/"
        for data in ({"role": "deputy"}, {"group": self.gb.pk}):
            resp = self.client.patch(url, data, format="json")
            self.assertEqual(resp.status_code, 400, data)
            self.assertEqual(
                resp.json()["detail"],
                "Members cannot change role or group during a running meeting.",
            )
        self.bert.refresh_from_db()
        self.assertEqual((self.bert.role, self.bert.group_id), ("voting", self.ga.pk))
        resp = self.client.patch(url, {"name": "Bert B.", "role": "voting"}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)
        services.end_meeting(self.meeting)
        resp = self.client.patch(url, {"group": self.gb.pk}, format="json")
        self.assertEqual(resp.status_code, 200, resp.content)


class AgendaOutlineTests(MeetingFixture, TestCase):
    def setUp(self):
        self.make_fixture()

    def _q(self, text, position, section=None):
        return Question.objects.create(
            question_set=self.meeting, kind=Question.Kind.RESOLUTION,
            text=text, position=position, section=section,
        )

    def _outline(self):
        # q1 (no section) | S1 "Bericht" (empty) | S2 "Haushalt": q2, q3 | S3: q4
        self.q1 = self._q("Q1", 0)
        self.s1 = Section.objects.create(
            question_set=self.meeting, title_de="Bericht", position=1,
        )
        self.s2 = Section.objects.create(
            question_set=self.meeting, title_de="Haushalt", position=2,
        )
        self.q2 = self._q("Q2", 3, self.s2)
        self.q3 = self._q("Q3", 4, self.s2)
        self.s3 = Section.objects.create(
            question_set=self.meeting, title_de="Drittes", position=5,
        )
        self.q4 = self._q("Q4", 6, self.s3)

    def test_tops_and_labels(self):
        self._outline()
        tops = agenda.tops(self.meeting)
        self.assertEqual([t.number for t in tops], [1, 2, 3, 4])
        self.assertEqual(tops[1].title, "Bericht")
        self.assertEqual(tops[1].question_ids, ())
        self.assertIsNone(tops[0].section_id)
        self.assertEqual(
            agenda.labels(self.meeting),
            {self.q1.pk: "1", self.q2.pk: "3a", self.q3.pk: "3b", self.q4.pk: "4"},
        )
        self.assertEqual(agenda.top_of(self.meeting, self.q3.pk).number, 3)
        self.assertEqual(agenda.top_by_section(self.meeting, self.s1.pk).number, 2)
        self.assertIsNone(agenda.top_of(self.meeting, 0))

    def test_reorder_relabels(self):
        self._outline()
        self.q3.section = self.s3
        self.q3.position = 6
        self.q3.save()
        self.q4.position = 7
        self.q4.save()
        self.assertEqual(
            agenda.labels(self.meeting),
            {self.q1.pk: "1", self.q2.pk: "3", self.q3.pk: "4a", self.q4.pk: "4b"},
        )

    def test_suffix(self):
        self.assertEqual(
            [agenda.suffix(i) for i in (0, 25, 26, 27)], ["a", "z", "aa", "ab"],
        )

    def test_description_is_canonical_language(self):
        s = Section.objects.create(
            question_set=self.meeting, title_de="T", position=1,
            description_de="Beschreibung", description_en="Description",
        )
        with translation.override("en"):
            top = agenda.top_by_section(self.meeting, s.pk, agenda.tops(self.meeting))
        self.assertEqual(top.description, "Beschreibung")


class ShowTopTests(BallotBase):
    """TOP labels in the payloads; showing a TOP without a vote."""

    def setUp(self):
        super().setUp()
        # Outline: S1 "Haushalt" (q1, q2), S2 "Bericht" (no vote).
        self.s1 = Section.objects.create(
            question_set=self.meeting, title_de="Haushalt", position=0,
        )
        self.s_empty = Section.objects.create(
            question_set=self.meeting, title_de="Bericht", position=3,
        )
        Question.objects.filter(pk__in=[self.q1.pk, self.q2.pk]).update(section=self.s1)
        self.q1.refresh_from_db()
        self.q2.refresh_from_db()
        self.url = f"/api/meetings/{self.meeting.pk}/show/"

    def post(self, data):
        return self.client.post(self.url, data, format="json")

    def test_item_carries_label_and_top(self):
        from . import payloads

        self.assertEqual(self.post({"question": self.q2.pk}).status_code, 200)
        data = payloads.public_payload(self.meeting)
        self.assertEqual(data["item"]["label"], "1b")
        self.assertEqual(data["item"]["bundle"], [])
        self.assertNotIn("number", data["item"])
        self.assertEqual(
            data["top"],
            {"number": 1, "section": self.s1.pk, "title": "Haushalt", "description": ""},
        )

    def test_show_top_without_vote(self):
        r = self.post({"section": self.s_empty.pk})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.json()["item"])
        self.assertEqual(r.json()["top"]["title"], "Bericht")
        self.assertEqual(r.json()["top"]["number"], 2)
        control = self.meeting.meeting_control
        control.refresh_from_db()
        self.assertIsNone(control.current_question)
        self.assertEqual(control.current_section, self.s_empty)

    def test_show_question_sets_section(self):
        self.post({"section": self.s_empty.pk})
        self.post({"question": self.q1.pk})
        control = self.meeting.meeting_control
        control.refresh_from_db()
        self.assertEqual(control.current_section, self.s1)

    def test_open_ballot_sets_section(self):
        ballots.open_ballot(self.meeting, self.q1)
        self.meeting.meeting_control.refresh_from_db()
        self.assertEqual(self.meeting.meeting_control.current_section, self.s1)

    def test_show_top_blocked_while_vote_open(self):
        ballots.open_ballot(self.meeting, self.q1)
        r = self.post({"section": self.s_empty.pk})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["code"], "vote_open")

    def test_show_needs_exactly_one_target(self):
        for data in ({}, {"question": self.q1.pk, "section": self.s1.pk}):
            r = self.post(data)
            self.assertEqual(r.status_code, 400)
            self.assertEqual(r.data["code"], "invalid")

    def test_section_of_other_meeting_404(self):
        other_set = QuestionSet.objects.create(
            room=self.room, title="Andere", type=QuestionSet.SetType.MEETING,
        )
        foreign = Section.objects.create(question_set=other_set, title_de="X", position=0)
        self.assertEqual(self.post({"section": foreign.pk}).status_code, 404)

    def test_console_tops(self):
        from . import payloads

        data = payloads.manager_payload(self.meeting)
        self.assertEqual(
            [t["items"] for t in data["tops"]], [[self.q1.pk, self.q2.pk], []],
        )
        self.assertEqual([i["label"] for i in data["items"]], ["1a", "1b"])
        self.assertEqual([i["top"] for i in data["items"]], [1, 1])


class AddResolutionTests(BallotBase):
    def setUp(self):
        super().setUp()
        # S1(1) q1(2) S2(3) q2(4)
        self.s1 = Section.objects.create(question_set=self.meeting, title_de="Eins", position=1)
        self.s2 = Section.objects.create(question_set=self.meeting, title_de="Zwei", position=3)
        Question.objects.filter(pk=self.q1.pk).update(section=self.s1, position=2)
        Question.objects.filter(pk=self.q2.pk).update(section=self.s2, position=4)

    def url(self):
        return f"/api/meetings/{self.meeting.pk}/items/"

    def test_add_into_top_becomes_next_subitem(self):
        with (mock.patch("committees.live.broadcast_meeting") as broadcast,
              self.captureOnCommitCallbacks(execute=True) as callbacks):
            q = services.add_resolution(
                self.meeting, "Änderungsantrag", self.s1, named=False,
            )
        self.assertTrue(callbacks)
        broadcast.assert_called()
        self.assertEqual(
            agenda.labels(self.meeting), {self.q1.pk: "1a", q.pk: "1b", self.q2.pk: "2"},
        )
        self.assertEqual(q.text_de, "<p>Änderungsantrag</p>")
        self.assertEqual(q.kind, Question.Kind.RESOLUTION)
        self.assertFalse(q.named_vote)
        self.assertEqual(versions.current(q).number, 1)
        self.s2.refresh_from_db()
        self.assertEqual(self.s2.position, 4)

    def test_named_flag(self):
        q = services.add_resolution(self.meeting, "X", self.s1, named=True)
        self.assertTrue(q.named_vote)

    def test_add_into_empty_top(self):
        s3 = Section.objects.create(question_set=self.meeting, title_de="Drei", position=5)
        q = services.add_resolution(self.meeting, "Neu", s3, named=False)
        self.assertEqual(
            agenda.labels(self.meeting), {self.q1.pk: "1", self.q2.pk: "2", q.pk: "3"},
        )

    def test_add_into_empty_top_shifts_following_rows(self):
        s3 = Section.objects.create(question_set=self.meeting, title_de="Drei", position=3)
        self.s2.position = 4
        self.s2.save()
        Question.objects.filter(pk=self.q2.pk).update(position=5)
        q = services.add_resolution(self.meeting, "Neu", s3, named=False)
        self.assertEqual(
            agenda.labels(self.meeting), {self.q1.pk: "1", q.pk: "2", self.q2.pk: "3"},
        )

    def test_add_without_section_is_new_top_at_end(self):
        q = services.add_resolution(self.meeting, "Ende", None, named=False)
        self.assertIsNone(q.section_id)
        self.assertEqual(
            agenda.labels(self.meeting), {self.q1.pk: "1", self.q2.pk: "2", q.pk: "3"},
        )

    def test_text_is_escaped(self):
        q = services.add_resolution(self.meeting, "  <b>x</b> ", self.s1, named=False)
        self.assertEqual(q.text_de, "<p>&lt;b&gt;x&lt;/b&gt;</p>")

    def test_text_length_is_capped(self):
        services.add_resolution(self.meeting, "x" * 1000, self.s1, named=False)
        with self.assertRaises(ValidationError) as ctx:
            services.add_resolution(self.meeting, "x" * 1001, self.s1, named=False)
        self.assertEqual(ctx.exception.code, "invalid")
        resp = self.client.post(
            self.url(), {"text": "x" * 1001, "section": self.s1.pk, "named": False}, format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "invalid")

    def test_api_creates_and_returns_console(self):
        resp = self.client.post(
            self.url(), {"text": "Antrag", "section": self.s1.pk, "named": True}, format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertIn("items", resp.data)
        self.assertTrue(Question.objects.get(text_de="<p>Antrag</p>").named_vote)

    def test_draft_and_ended_rejected(self):
        for state in ("draft", "ended"):
            QuestionSet.objects.filter(pk=self.meeting.pk).update(meeting_state=state)
            resp = self.client.post(
                self.url(), {"text": "X", "section": self.s1.pk, "named": False}, format="json",
            )
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(resp.data["code"], "not_started")

    def test_empty_text_rejected(self):
        resp = self.client.post(
            self.url(), {"text": "   ", "section": self.s1.pk, "named": False}, format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.data["code"], "invalid")

    def test_foreign_section_404(self):
        other = QuestionSet.objects.create(room=self.room, title="Andere")
        foreign = Section.objects.create(question_set=other, title_de="F", position=1)
        resp = self.client.post(
            self.url(), {"text": "X", "section": foreign.pk, "named": False}, format="json",
        )
        self.assertEqual(resp.status_code, 404)

    def test_non_owner_forbidden(self):
        resp = self.foreign.post(self.url(), {"text": "X", "named": False}, format="json")
        self.assertIn(resp.status_code, (403, 404))


class BundleTests(BallotBase):
    """En bloc ballot: one vote over several resolutions."""

    def setUp(self):
        super().setUp()
        # Outline: S1 (q1 "1a", q2 open_text "1b", r2 "1c"), r3 "2", rn named "3".
        self.s1 = Section.objects.create(question_set=self.meeting, title_de="Eins", position=0)
        Question.objects.filter(pk__in=[self.q1.pk, self.q2.pk]).update(section=self.s1)
        self.r2 = Question.objects.create(
            question_set=self.meeting, kind="resolution", text_de="Zwei", position=3,
            section=self.s1,
        )
        self.r3 = Question.objects.create(
            question_set=self.meeting, kind="resolution", text_de="Drei", position=4,
        )
        self.rn = Question.objects.create(
            question_set=self.meeting, kind="resolution", text_de="Namentlich", position=5,
            named_vote=True,
        )
        for q in (self.q1, self.q2):
            q.refresh_from_db()

    def url(self, suffix):
        return f"/api/meetings/{self.meeting.pk}/{suffix}"

    def bundle(self):
        return ballots.open_bundle(self.meeting, [self.r3, self.q1, self.r2])

    def test_bundle_vote_counts_once_for_all(self):
        b = self.bundle()
        self.assertEqual(b.question, self.q1)
        self.assertTrue(b.secret)
        self.assertEqual({i.question_id for i in b.items.all()}, {self.r2.pk, self.r3.pk})
        for item in b.items.all():
            self.assertEqual(item.version, versions.current(item.question))
        self.assertEqual(b.seats.count(), 3)
        self.vote(self.anna, b, {"choice": "yes"})
        with self.captureOnCommitCallbacks(execute=True):
            b = ballots.close_ballot(b)
        self.assertEqual(b.result["total"]["counts"], {"yes": 1, "no": 0, "abstain": 0})
        for q in (self.q1, self.r2, self.r3):
            self.assertEqual(ballots.ballots_for(q).get().status, Ballot.Status.CLOSED)

    def test_bundled_item_cannot_open_alone(self):
        b = self.bundle()
        self.assertCode("other_open", ballots.open_ballot, self.meeting, self.r2)
        ballots.close_ballot(b)
        self.assertCode("already_voted_on", ballots.open_ballot, self.meeting, self.r2)
        self.assertCode("already_voted_on", ballots.open_ballot, self.meeting, self.q1)

    def test_reset_frees_all_items(self):
        b = self.bundle()
        ballots.close_ballot(b)
        ballots.reset_ballot(b, "Fehler")
        single = ballots.open_ballot(self.meeting, self.r2)
        self.assertEqual(single.question, self.r2)
        self.assertEqual(single.round, 2)
        ballots.close_ballot(single)
        again = ballots.open_bundle(self.meeting, [self.q1, self.r3])
        self.assertEqual(again.round, 2)

    def test_bundle_errors(self):
        self.assertCode("invalid", ballots.open_bundle, self.meeting, [self.q1])
        self.assertCode("invalid", ballots.open_bundle, self.meeting, [self.q1, self.q1])
        self.assertCode("invalid", ballots.open_bundle, self.meeting, [self.q1, self.q2])
        self.assertCode("mixed_named", ballots.open_bundle, self.meeting, [self.q1, self.rn])
        other = QuestionSet.objects.create(
            room=self.room, title="Andere", type=QuestionSet.SetType.MEETING,
        )
        foreign = Question.objects.create(question_set=other, kind="resolution", text_de="F")
        self.assertCode("invalid", ballots.open_bundle, self.meeting, [self.q1, foreign])
        single = ballots.open_ballot(self.meeting, self.r3)
        self.assertCode("other_open", ballots.open_bundle, self.meeting, [self.q1, self.r2])
        ballots.close_ballot(single)
        self.assertCode(
            "already_voted_on", ballots.open_bundle, self.meeting, [self.q1, self.r3],
        )
        services.end_meeting(self.meeting)
        self.assertCode("not_started", ballots.open_bundle, self.meeting, [self.q1, self.r2])
        self.assertFalse(Ballot.objects.filter(question=self.q1).exists())

    def test_payload_bundle_texts(self):
        from . import payloads

        self.bundle()
        item = payloads.public_payload(self.meeting)["item"]
        self.assertEqual(item["id"], self.q1.pk)
        self.assertEqual(item["label"], "1a")
        self.assertEqual(item["bundle"], [
            {"id": self.r2.pk, "label": "1c", "text": "Zwei", "version": 1},
            {"id": self.r3.pk, "label": "2", "text": "Drei", "version": 1},
        ])
        self.assertEqual(payloads.preview_payload(self.r2)["item"]["bundle"], [])

    def test_console_status_for_bundled(self):
        from . import payloads

        b = self.bundle()
        items = {i["id"]: i for i in payloads.manager_payload(self.meeting)["items"]}
        self.assertEqual(items[self.r2.pk]["ballot_status"], "open")
        self.assertEqual(items[self.r2.pk]["bundle_lead"], self.q1.pk)
        self.assertEqual(items[self.r3.pk]["bundle_lead"], self.q1.pk)
        self.assertIsNone(items[self.q1.pk]["bundle_lead"])
        self.assertIsNone(items[self.q2.pk]["bundle_lead"])
        self.assertIsNone(items[self.q2.pk]["ballot_status"])
        ballots.close_ballot(b)
        ballots.reset_ballot(b, "")
        items = {i["id"]: i for i in payloads.manager_payload(self.meeting)["items"]}
        self.assertIsNone(items[self.r2.pk]["ballot_status"])
        self.assertEqual(items[self.r2.pk]["discarded"], 1)
        self.assertIsNone(items[self.r2.pk]["bundle_lead"])

    def test_bundled_item_is_locked(self):
        self.assertIsNone(versions.lock_reason(self.r2))
        b = self.bundle()
        self.assertEqual(versions.lock_reason(self.r2), "A vote on this item is open.")
        ballots.close_ballot(b)
        self.assertIn("voted on", versions.lock_reason(self.r2))

    def test_show_bundled_item_shows_lead(self):
        self.bundle()
        resp = self.client.post(self.url("show/"), {"question": self.r3.pk}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["item"]["id"], self.q1.pk)
        resp = self.client.post(self.url("show/"), {"question": self.rn.pk}, format="json")
        self.assertEqual(resp.data["code"], "vote_open")

    def test_api_bundles_endpoint(self):
        resp = self.client.post(
            self.url("bundles/"), {"questions": [self.q1.pk, self.rn.pk]}, format="json",
        )
        self.assertEqual((resp.status_code, resp.data["code"]), (400, "mixed_named"))
        for body in ({}, {"questions": "x"}, {"questions": [self.q1.pk, "x"]}):
            resp = self.client.post(self.url("bundles/"), body, format="json")
            self.assertEqual((resp.status_code, resp.data["code"]), (400, "invalid"), body)
        resp = self.client.post(
            self.url("bundles/"), {"questions": [self.r2.pk, 999999]}, format="json",
        )
        self.assertEqual(resp.status_code, 404)
        resp = self.client.post(
            self.url("bundles/"), {"questions": [self.r2.pk, self.q1.pk]}, format="json",
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data["open_ballot"], Ballot.objects.get(question=self.q1).pk)
        self.assertEqual(resp.data["item"]["id"], self.q1.pk)
        resp = self.foreign.post(
            self.url("bundles/"), {"questions": [self.r3.pk, self.rn.pk]}, format="json",
        )
        self.assertIn(resp.status_code, (403, 404))

    def test_delete_room_with_closed_bundle(self):
        b = self.bundle()
        ballots.close_ballot(b)
        services.end_meeting(self.meeting)
        resp = self.client.delete(f"/api/rooms/{self.room.pk}/")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Ballot.objects.exists())
        self.assertFalse(Question.objects.filter(pk=self.r2.pk).exists())


class SealTests(BallotBase):
    RESULT_KEYS = frozenset({
        "reference", "secret", "round", "version", "items", "groups", "total",
        "voted", "tally_sum", "voters", "named", "texts", "opened_at", "closed_at",
    })

    def closed(self, question=None, answers=None):
        ballot = ballots.open_ballot(self.meeting, question or self.q1)
        for member, answer in (answers or [(self.anna, {"choice": "yes"})]):
            self.vote(member, ballot, answer)
        with self.captureOnCommitCallbacks(execute=True):
            ballot.refresh_from_db()
            if ballot.status == Ballot.Status.OPEN:
                return ballots.close_ballot(ballot)
        return ballot

    def expected_hash(self, link, ballot):
        content = seals.content(ballot, link.kind, link.reference)
        return seals.digest({
            "v": 1, "seq": link.seq, "kind": link.kind, "reference": link.reference,
            "content_hash": seals.digest(content), "previous": link.previous,
        })

    def test_close_appends_result_link(self):
        ballot = self.closed()
        link = SealLink.objects.get()
        self.assertEqual((link.kind, link.seq, link.previous), ("result", 1, ""))
        self.assertEqual(link.room_id, self.room.pk)
        self.assertEqual(link.meeting_id, self.meeting.pk)
        self.assertEqual(link.ballot_id, ballot.pk)
        ballot = Ballot.objects.get(pk=ballot.pk)
        content = seals.content(ballot, "result", link.reference)
        self.assertEqual(link.content_hash, seals.digest(content))
        self.assertEqual(link.hash, self.expected_hash(link, ballot))
        self.assertEqual(len(link.hash), 64)
        self.assertEqual(
            seals.canonical({"b": 1, "a": "ä"}), '{"a":"ä","b":1}'.encode(),
        )

    def test_chain_links_previous(self):
        self.closed()
        self.closed(self.q2, [(self.anna, {"text": "Hallo"})])
        links = list(SealLink.objects.all())
        self.assertEqual([link.seq for link in links], [1, 2])
        self.assertEqual(links[1].previous, links[0].hash)

    def test_reference_format(self):
        import datetime
        from zoneinfo import ZoneInfo

        section = Section.objects.create(question_set=self.meeting, title_de="TOP", position=0)
        Question.objects.filter(pk__in=[self.q1.pk, self.q2.pk]).update(section=section)
        self.meeting.scheduled_at = datetime.datetime(
            2026, 11, 4, 0, 30, tzinfo=ZoneInfo("Europe/Berlin"),
        )
        self.meeting.save(update_fields=["scheduled_at"])
        ballot = self.closed()
        self.assertEqual(seals.reference(ballot), f"G{self.meeting.pk}-20261104-TOP1a")
        self.assertEqual(SealLink.objects.get().reference, f"G{self.meeting.pk}-20261104-TOP1a")
        ballots.reset_ballot(ballot, "Fehler")
        second = self.closed()
        self.assertEqual(seals.reference(second), f"G{self.meeting.pk}-20261104-TOP1a-W2")

    def test_reference_falls_back_to_start(self):
        ballot = self.closed()
        started = timezone.localtime(self.meeting.meeting_control.started_at)
        self.assertEqual(
            seals.reference(ballot),
            f"G{self.meeting.pk}-{started:%Y%m%d}-TOP1",
        )

    def test_secret_content_has_no_choices_per_person(self):
        ballot = self.closed(answers=[(self.anna, {"choice": "yes"}), (self.ben, {"choice": "no"})])
        content = seals.content(Ballot.objects.get(pk=ballot.pk), "result", "R")
        self.assertEqual(set(content), self.RESULT_KEYS)
        self.assertTrue(content["secret"])
        self.assertEqual(content["named"], [])
        self.assertEqual(content["voters"], sorted([self.anna.pk, self.ben.pk]))
        self.assertEqual(content["total"]["counts"], {"yes": 1, "no": 1, "abstain": 0})
        self.assertEqual(
            [set(g) for g in content["groups"]],
            [{"group_id", "eligible", "voted", "counts"}] * 2,
        )
        self.assertEqual(
            [g["group_id"] for g in content["groups"]], sorted([self.ga.pk, self.gb.pk]),
        )

    def test_named_content_lists_choices(self):
        self.q1.named_vote = True
        self.q1.save()
        ballot = self.closed(answers=[(self.ben, {"choice": "no"}), (self.anna, {"choice": "yes"})])
        content = seals.content(Ballot.objects.get(pk=ballot.pk), "result", "R")
        self.assertEqual(set(content), self.RESULT_KEYS)
        self.assertEqual(content["named"], sorted(
            [{"member_id": self.anna.pk, "keys": ["yes"]},
             {"member_id": self.ben.pk, "keys": ["no"]}],
            key=lambda n: n["member_id"],
        ))

    def test_secret_texts_sorted_per_group(self):
        ballot = self.closed(self.q2, [
            (self.bert, {"text": "zwei"}), (self.anna, {"text": "eins"}),
            (self.ben, {"text": "drei"}),
        ])
        content = seals.content(Ballot.objects.get(pk=ballot.pk), "result", "R")
        self.assertEqual(content["texts"], sorted([
            {"group_id": self.ga.pk, "texts": ["eins", "zwei"]},
            {"group_id": self.gb.pk, "texts": ["drei"]},
        ], key=lambda t: t["group_id"]))

    def test_finding_and_reset_append_links(self):
        ballot = self.closed()
        ballots.set_finding(ballot, "adopted")
        finding = SealLink.objects.get(kind="finding")
        self.assertEqual(
            seals.content(Ballot.objects.get(pk=ballot.pk), "finding", finding.reference),
            {"reference": finding.reference, "finding": "adopted"},
        )
        ballots.reset_ballot(ballot, "Zählfehler")
        discard = SealLink.objects.get(kind="discard")
        content = seals.content(Ballot.objects.get(pk=ballot.pk), "discard", discard.reference)
        self.assertEqual(
            content, {"reference": discard.reference, "reason": "reset", "comment": "Zählfehler"},
        )
        self.assertEqual(discard.content_hash, seals.digest(content))
        self.assertEqual(
            list(SealLink.objects.values_list("kind", flat=True)),
            ["result", "finding", "discard"],
        )

    def test_reset_open_ballot_appends_discard(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        with self.captureOnCommitCallbacks(execute=True):
            ballots.reset_ballot(ballot, "")
        self.assertEqual(list(SealLink.objects.values_list("kind", flat=True)), ["discard"])

    def test_restart_abort_appends_discard(self):
        ballot = ballots.open_ballot(self.meeting, self.q1)
        self.vote(self.anna, ballot, {"choice": "yes"})
        with mock.patch("committees.tally.EPOCH", "other"):
            ballots.abort_stale(self.meeting)
        link = SealLink.objects.get()
        self.assertEqual((link.kind, link.ballot_id), ("discard", ballot.pk))
        content = seals.content(Ballot.objects.get(pk=ballot.pk), "discard", link.reference)
        self.assertEqual(content["reason"], "restart")
        self.assertEqual(link.hash, self.expected_hash(link, Ballot.objects.get(pk=ballot.pk)))

    def test_delete_meeting_keeps_placeholders(self):
        self.closed()
        self.closed(self.q2, [(self.anna, {"text": "Hallo"})])
        before = list(SealLink.objects.values_list("hash", "previous", "content_hash"))
        services.end_meeting(self.meeting)
        self.meeting.delete()
        links = list(SealLink.objects.all())
        self.assertEqual(len(links), 2)
        self.assertTrue(all(link.deleted_at is not None for link in links))
        self.assertTrue(all(link.ballot is None for link in links))
        self.assertEqual(
            [(link.hash, link.previous, link.content_hash) for link in links], before,
        )

    def test_chain_is_per_room(self):
        self.closed()
        other = make_room(title="Other")
        fixture = MeetingFixture()
        fixture.make_fixture(room=other)
        question = Question.objects.create(
            question_set=fixture.meeting, kind="resolution", text_de="B", position=1,
        )
        fixture.member("Xena", fixture.ga)
        services.start_meeting(fixture.meeting)
        ballot = ballots.open_ballot(fixture.meeting, question)
        with self.captureOnCommitCallbacks(execute=True):
            ballots.close_ballot(ballot)
        link = SealLink.objects.get(room=other)
        self.assertEqual((link.seq, link.previous), (1, ""))

    def test_content_survives_renames_and_relabelling(self):
        ballot = self.closed(answers=[(self.anna, {"choice": "yes"}), (self.ben, {"choice": "no"})])
        link = SealLink.objects.get()
        self.assertTrue(link.reference.endswith("-TOP1"))

        def recomputed():
            fresh = Ballot.objects.get(pk=ballot.pk)
            return seals.digest(seals.content(fresh, "result", link.reference))

        self.assertEqual(recomputed(), link.content_hash)
        CommitteeMember.objects.filter(pk=self.anna.pk).update(name="Anna Neu")
        CommitteeGroup.objects.filter(pk=self.ga.pk).update(name_de="Umbenannt", name_en="Renamed")
        self.assertEqual(recomputed(), link.content_hash)
        # A second resolution in the same TOP: "1" becomes "1a".
        section = Section.objects.create(question_set=self.meeting, title_de="TOP", position=0)
        Question.objects.filter(pk=self.q1.pk).update(section=section)
        Question.objects.create(
            question_set=self.meeting, kind="resolution", text_de="Zweiter",
            position=1, section=section,
        )
        self.assertEqual(agenda.labels(self.meeting)[self.q1.pk], "1a")
        self.assertTrue(seals.reference(Ballot.objects.get(pk=ballot.pk)).endswith("TOP1a"))
        self.assertEqual(recomputed(), link.content_hash)


class VerifyTests(BallotBase):
    closed = SealTests.closed

    def verify(self, reference, fingerprint="", client=None, room=None):
        return (client or self.client).get("/api/committee-seals/verify/", {
            "room": (room or self.room).pk, "reference": reference, "fingerprint": fingerprint,
        })

    def ref(self):
        return SealLink.objects.order_by("seq").first().reference

    def test_valid_result(self):
        self.closed()
        r = self.verify(self.ref())
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data["found"])
        self.assertTrue(r.data["chain_intact"])
        self.assertEqual([link["status"] for link in r.data["links"]], ["valid"])
        self.assertEqual(r.data["links"][0]["kind"], "result")
        self.assertIsNone(r.data["fingerprint_matches"])

    def test_unknown_reference(self):
        self.closed()
        r = self.verify("nope")
        self.assertFalse(r.data["found"])
        self.assertEqual(r.data["links"], [])

    def test_altered_result_detected(self):
        ballot = self.closed()
        result = dict(Ballot.objects.get(pk=ballot.pk).result)
        result["total"] = {**result["total"], "counts": {"yes": 0, "no": 1, "abstain": 0}}
        Ballot.objects.filter(pk=ballot.pk).update(result=result)
        r = self.verify(self.ref())
        self.assertEqual(r.data["links"][0]["status"], "altered")
        self.assertTrue(r.data["chain_intact"])

    def test_reset_after_seal_is_discarded(self):
        ballot = self.closed()
        ballots.set_finding(ballot, "adopted")
        ballots.reset_ballot(ballot, "Fehler")
        r = self.verify(self.ref())
        self.assertEqual(
            [(link["kind"], link["status"]) for link in r.data["links"]],
            [("result", "discarded"), ("finding", "discarded"), ("discard", "valid")],
        )
        self.assertTrue(r.data["chain_intact"])

    def test_relabel_keeps_reference_for_later_links(self):
        s1 = Section.objects.create(question_set=self.meeting, title_de="Eins", position=0)
        Question.objects.filter(pk=self.q1.pk).update(section=s1)
        ballot = self.closed()
        result_ref = SealLink.objects.get(kind="result").reference
        self.assertTrue(result_ref.endswith("-TOP1"), result_ref)
        services.add_resolution(self.meeting, "Änderung", s1, named=False)
        self.assertEqual(agenda.labels(self.meeting)[self.q1.pk], "1a")
        ballot = Ballot.objects.get(pk=ballot.pk)
        ballots.set_finding(ballot, "adopted")
        finding = SealLink.objects.get(kind="finding")
        self.assertEqual(finding.reference, result_ref)
        ballots.reset_ballot(Ballot.objects.get(pk=ballot.pk), "Fehler")
        self.assertEqual(
            set(SealLink.objects.filter(ballot=ballot).values_list("reference", flat=True)),
            {result_ref},
        )
        r = self.verify(result_ref, finding.hash[:16])
        self.assertEqual(
            [(link["kind"], link["status"]) for link in r.data["links"]],
            [("result", "discarded"), ("finding", "discarded"), ("discard", "valid")],
        )
        self.assertTrue(r.data["fingerprint_matches"])

    def test_discarded_without_discard_link_is_altered(self):
        ballot = self.closed()
        Ballot.objects.filter(pk=ballot.pk).update(status=Ballot.Status.DISCARDED)
        r = self.verify(self.ref())
        self.assertEqual([link["status"] for link in r.data["links"]], ["altered"])

    def test_link_without_ballot_is_altered(self):
        self.closed()
        SealLink.objects.update(ballot=None)
        r = self.verify(self.ref())
        self.assertEqual([link["status"] for link in r.data["links"]], ["altered"])

    def test_tampered_link_breaks_chain(self):
        self.closed()
        SealLink.objects.update(content_hash="0" * 64)
        r = self.verify(self.ref())
        self.assertFalse(r.data["chain_intact"])

    def test_gap_breaks_chain(self):
        self.closed()
        self.closed(self.q2, [(self.anna, {"text": "Hallo"})])
        SealLink.objects.filter(seq=1).delete()
        r = self.verify(SealLink.objects.get().reference)
        self.assertFalse(r.data["chain_intact"])

    def test_deleted_meeting_placeholder(self):
        self.closed()
        a_ref = self.ref()
        services.end_meeting(self.meeting)
        self.meeting.delete()
        fixture = MeetingFixture()
        fixture.make_fixture(room=self.room)
        question = Question.objects.create(
            question_set=fixture.meeting, kind="resolution", text_de="B", position=1,
        )
        fixture.member("Xena", fixture.ga)
        services.start_meeting(fixture.meeting)
        ballot = ballots.open_ballot(fixture.meeting, question)
        with self.captureOnCommitCallbacks(execute=True):
            ballots.close_ballot(ballot)
        r = self.verify(a_ref)
        self.assertEqual([link["status"] for link in r.data["links"]], ["deleted"])
        self.assertTrue(r.data["chain_intact"])
        b = self.verify(SealLink.objects.get(seq=2).reference)
        self.assertEqual([link["status"] for link in b.data["links"]], ["valid"])

    def test_fingerprint_prefix(self):
        self.closed()
        h = SealLink.objects.get().hash
        spaced = " ".join(h[i:i + 4] for i in range(0, 16, 4)).upper()
        self.assertTrue(self.verify(self.ref(), spaced).data["fingerprint_matches"])
        self.assertFalse(self.verify(self.ref(), "0" * 16).data["fingerprint_matches"])
        r = self.verify(self.ref(), h[:8])
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data["code"], "invalid")
        self.assertEqual(self.verify(self.ref(), "xyz" * 6).status_code, 400)

    def test_not_manager_404(self):
        self.closed()
        r = self.verify(self.ref(), client=self.foreign)
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.verify(self.ref(), room=self.room).status_code, 200)
        r = self.client.get("/api/committee-seals/verify/", {"room": 99999, "reference": "x"})
        self.assertEqual(r.status_code, 404)


class ProtocolTests(BallotBase):
    closed = SealTests.closed

    def url(self):
        return f"/api/meetings/{self.meeting.pk}/protocol/"

    def end(self):
        services.end_meeting(self.meeting)

    def protocol(self):
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def items(self, data):
        return {i["label"]: i for top in data["tops"] for i in top["items"]}

    def test_requires_ended_meeting(self):
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "not_ended")
        self.assertEqual(self.foreign.get(self.url()).status_code, 404)

    def test_secret_result_and_voters(self):
        ballot = self.closed(answers=[(self.anna, {"choice": "yes"}), (self.ben, {"choice": "no"})])
        ballots.set_finding(ballot, "adopted")
        self.end()
        data = self.protocol()
        self.assertEqual(data["committee"], "R")
        self.assertEqual(data["title"], "Sitzung")
        self.assertIsNotNone(data["started_at"])
        self.assertIsNotNone(data["ended_at"])
        present = [(p["name"], p["group"]) for p in data["attendance"]["present"]]
        self.assertIn(("Anna", "Gruppe A"), present)
        self.assertNotIn("Olga", [p["name"] for p in data["attendance"]["present"]])
        self.assertEqual(data["attendance"]["observers"], ["Olga"])
        item = self.items(data)["1"]
        self.assertEqual(item["status"], "voted")
        self.assertEqual(item["kind"], "resolution")
        self.assertFalse(item["named"])
        self.assertEqual(item["text"], "Beschluss")
        self.assertEqual(item["result"]["total"]["counts"], {"yes": 1, "no": 1, "abstain": 0})
        groups = {g["name"]: g for g in item["result"]["groups"]}
        self.assertEqual(groups["Gruppe A"]["eligible"], 2)
        self.assertEqual(groups["Gruppe A"]["voted"], 1)
        self.assertTrue(item["result"]["count_check_ok"])
        self.assertEqual(item["named_votes"], [])
        self.assertEqual(item["finding"], "adopted")
        self.assertEqual(
            item["options"],
            [{"key": "yes", "text": "yes"}, {"key": "no", "text": "no"},
             {"key": "abstain", "text": "abstain"}],
        )
        self.assertIsNotNone(item["opened_at"])
        self.assertIsNotNone(item["closed_at"])
        self.assertEqual(
            item["voters"],
            [{"name": "Anna", "group": "Gruppe A"}, {"name": "Ben", "group": "Gruppe B"}],
        )

    def test_secret_voters_without_choices(self):
        self.closed(answers=[(self.anna, {"choice": "yes"})])
        self.end()
        item = self.items(self.protocol())["1"]
        self.assertEqual(item["voters"], [{"name": "Anna", "group": "Gruppe A"}])
        self.assertEqual(item["named_votes"], [])
        # Anna's name appears only in the voter list, never next to a choice.
        rest = {k: v for k, v in item.items() if k != "voters"}
        self.assertNotIn("Anna", json.dumps(rest))
        self.assertNotIn("Bert", json.dumps(item))

    def test_named_follows_voted_ballot(self):
        self.closed()  # secret ballot
        self.q1.named_vote = True
        self.q1.save(update_fields=["named_vote"])
        self.end()
        items = self.items(self.protocol())
        self.assertFalse(items["1"]["named"])
        self.assertEqual(items["1"]["voters"], [{"name": "Anna", "group": "Gruppe A"}])
        self.assertEqual(items["2"]["voters"], [])

    def test_named_votes_listed(self):
        self.q1.named_vote = True
        self.q1.save(update_fields=["named_vote"])
        self.closed(answers=[(self.anna, {"choice": "yes"}), (self.ben, {"choice": "no"})])
        self.end()
        item = self.items(self.protocol())["1"]
        self.assertTrue(item["named"])
        self.assertEqual(item["named_votes"], [
            {"member": "Anna", "group": "Gruppe A", "keys": ["yes"]},
            {"member": "Ben", "group": "Gruppe B", "keys": ["no"]},
        ])

    def test_free_texts_by_group(self):
        self.closed(self.q2, [(self.anna, {"text": "Hallo"})])
        self.end()
        item = self.items(self.protocol())["2"]
        self.assertEqual(item["texts"], [{"group": "Gruppe A", "text": "Hallo"}])
        self.assertEqual(
            item["options"], [{"key": "text", "text": "text"}, {"key": "abstain", "text": "abstain"}],
        )

    def test_choice_options_use_version_text(self):
        q = Question.objects.create(
            question_set=self.meeting, kind="single_choice", text_de="Wahl", position=3,
        )
        o1 = AnswerOption.objects.create(question=q, text_de="Rot", text_en="Red", position=1)
        versions.sync(q)
        ballot = ballots.open_ballot(self.meeting, q)
        self.vote(self.anna, ballot, {"option": o1.pk})
        ballots.close_ballot(ballot)
        self.end()
        item = self.items(self.protocol())["3"]
        self.assertEqual(
            item["options"],
            [{"key": f"opt:{o1.pk}", "text": "Rot"}, {"key": "abstain", "text": "abstain"}],
        )

    def test_reset_note_without_old_result(self):
        first = self.closed(answers=[(self.anna, {"choice": "no"})])
        ballots.reset_ballot(first, "Fehler")
        self.closed()
        self.end()
        item = self.items(self.protocol())["1"]
        self.assertEqual(
            item["rounds_discarded"], [{"round": 1, "reason": "reset", "comment": "Fehler"}],
        )
        self.assertEqual(item["result"]["total"]["counts"], {"yes": 1, "no": 0, "abstain": 0})
        self.assertTrue(item["reference"].endswith("-W2"))

    def test_version_changed_note(self):
        r = self.client.patch(
            f"/api/questions/{self.q1.pk}/", {"text": {"de": "Beschluss neu"}}, format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.q1.refresh_from_db()
        self.closed()
        self.end()
        item = self.items(self.protocol())["1"]
        self.assertEqual((item["version"], item["text"]), (2, "Beschluss neu"))
        self.assertTrue(item["version_changed"])
        self.assertFalse(self.items(self.protocol())["2"]["version_changed"])

    def test_en_bloc_items_each_show_result(self):
        r3 = Question.objects.create(
            question_set=self.meeting, kind="resolution", text_de="Drei", position=3,
        )
        versions.sync(r3)
        bundle = ballots.open_bundle(self.meeting, [self.q1, r3])
        self.vote(self.anna, bundle, {"choice": "yes"})
        ballots.close_ballot(bundle)
        ballots.set_finding(bundle, "adopted")
        self.end()
        items = self.items(self.protocol())
        self.assertEqual(items["1"]["result"], items["3"]["result"])
        self.assertEqual(items["1"]["bundle_with"], ["3"])
        self.assertEqual(items["3"]["bundle_with"], ["1"])
        self.assertEqual(items["3"]["status"], "voted")
        self.assertEqual(items["3"]["text"], "Drei")
        self.assertEqual(items["3"]["finding"], "adopted")
        self.assertEqual(items["3"]["fingerprint"], items["1"]["fingerprint"])
        self.assertEqual(items["3"]["voters"], [{"name": "Anna", "group": "Gruppe A"}])

    def test_attendance_left_after_and_substitution(self):
        services.add_substitution(self.meeting, self.anna, self.dora, from_question=self.q2)
        self.meeting.invites.filter(entered_at__isnull=True).update(entered_at=timezone.now())
        services.remove_invite(self.invite(self.bert), after_question=self.q1)
        self.end()
        attendance = self.protocol()["attendance"]
        present = {p["name"]: p for p in attendance["present"]}
        self.assertEqual(present["Bert"]["left_after"], "1")
        self.assertIsNone(present["Ben"]["left_after"])
        self.assertIn("Dora", present)
        self.assertEqual(
            attendance["substitutions"],
            [{"deputy": "Dora", "absent": "Anna", "group": "Gruppe A", "from_label": "2"}],
        )

    def test_not_voted_item(self):
        self.end()
        item = self.items(self.protocol())["1"]
        self.assertEqual(item["status"], "not_voted")
        self.assertIsNone(item["result"])
        self.assertIsNone(item["fingerprint"])
        self.assertIsNone(item["reference"])
        self.assertEqual(item["version"], 1)
        self.assertEqual(item["text"], "Beschluss")

    def test_top_without_vote(self):
        Section.objects.create(
            question_set=self.meeting, title_de="Verschiedenes", position=9,
        )
        self.end()
        tops = self.protocol()["tops"]
        self.assertEqual(
            [(t["number"], t["title"], t["items"]) for t in tops[2:]],
            [(3, "Verschiedenes", [])],
        )

    def test_fingerprint_matches_seal_link(self):
        ballot = self.closed()
        ballots.set_finding(ballot, "rejected")
        self.end()
        item = self.items(self.protocol())["1"]
        result_link = SealLink.objects.get(ballot=ballot, kind="result")
        finding_link = SealLink.objects.get(ballot=ballot, kind="finding")
        self.assertEqual(item["fingerprint"], result_link.hash)
        self.assertEqual(item["reference"], result_link.reference)
        self.assertEqual(item["finding_fingerprint"], finding_link.hash)

    def election_rounds(self, reset_first=False):
        """Round 1 (optionally reset and voted again), then a runoff over
        the first two candidates; the meeting is ended."""
        q, (a, b, c) = self.election()
        b1 = ballots.open_ballot(self.meeting, q)
        self.vote(self.anna, b1, {"option": a})
        if reset_first:
            ballots.reset_ballot(b1, "Fehler")
            b1 = ballots.open_ballot(self.meeting, q)
            self.vote(self.anna, b1, {"option": a})
        self.vote(self.ben, b1, {"option": b})
        self.result(b1)
        b1.refresh_from_db()
        b2 = ballots.open_runoff(self.meeting, b1, [a, b])
        self.vote(self.anna, b2, {"option": a})
        self.result(b2)
        self.end()
        return q, (a, b, c), b1, Ballot.objects.get(pk=b2.pk)

    def test_protocol_lists_election_rounds(self):
        _q, (a, b, c), b1, b2 = self.election_rounds()
        item = self.items(self.protocol())["3"]
        self.assertEqual(item["kind"], "election")
        self.assertTrue(item["runoff"])
        self.assertEqual((item["round"], item["ballot_no"]), (2, 2))
        self.assertEqual((item["max_votes"], item["cumulate"]), (1, False))
        self.assertEqual(
            [o["key"] for o in item["options"]], [f"opt:{a}", f"opt:{b}", "no", "abstain"],
        )
        self.assertEqual(item["result"]["total"]["counts"][f"opt:{a}"], 1)
        self.assertTrue(item["reference"].endswith("-W2"))
        self.assertEqual(
            item["fingerprint"], SealLink.objects.get(ballot=b2, kind="result").hash,
        )
        [first] = item["earlier_rounds"]
        self.assertFalse(first["runoff"])
        self.assertEqual((first["round"], first["ballot_no"]), (1, 1))
        self.assertEqual(
            [o["key"] for o in first["options"]],
            [f"opt:{a}", f"opt:{b}", f"opt:{c}", "no", "abstain"],
        )
        self.assertEqual(
            [o["text"] for o in first["options"][:3]], ["K0", "K1", "K2"],
        )
        self.assertEqual(first["result"]["total"]["counts"][f"opt:{b}"], 1)
        self.assertEqual(first["result"]["total"]["voted"], 2)
        self.assertEqual(
            first["reference"], SealLink.objects.get(ballot=b1, kind="result").reference,
        )
        self.assertFalse(first["reference"].endswith("-W1"))
        self.assertEqual(
            first["fingerprint"], SealLink.objects.get(ballot=b1, kind="result").hash,
        )
        self.assertEqual(
            [v["name"] for v in first["voters"]], ["Anna", "Ben"],
        )
        self.assertIsNotNone(first["opened_at"])
        self.assertIsNotNone(first["closed_at"])
        # Resolutions have no further rounds.
        resolution = self.items(self.protocol())["1"]
        self.assertEqual(resolution["earlier_rounds"], [])

    def test_protocol_wahlgang_number_after_reset(self):
        self.election_rounds(reset_first=True)
        item = self.items(self.protocol())["3"]
        self.assertEqual((item["round"], item["ballot_no"]), (3, 2))
        self.assertTrue(item["reference"].endswith("-W3"))
        [first] = item["earlier_rounds"]
        self.assertEqual((first["round"], first["ballot_no"]), (2, 1))
        self.assertEqual([r["round"] for r in item["rounds_discarded"]], [1])

    def test_protocol_keeps_round_candidates_after_edit(self):
        q, _ids, _b1, _b2 = self.election_rounds()
        before = self.items(self.protocol())["3"]
        AnswerOption.objects.create(question=q, text_de="Neu", position=9)
        after = self.items(self.protocol())["3"]
        self.assertEqual(after["earlier_rounds"][0]["options"], before["earlier_rounds"][0]["options"])
        self.assertEqual(after["options"], before["options"])
        self.assertNotIn("Neu", json.dumps(after))

    def test_protocol_approval_and_multi_options(self):
        single, _ids = self.election(n=1, max_votes=3)
        ballot = ballots.open_ballot(self.meeting, single)
        self.vote(self.anna, ballot, {"choice": "yes"})
        self.result(ballot)
        multi = Question.objects.create(
            question_set=self.meeting, kind="election", text_de="Mehr", position=4,
            max_votes=2, cumulate=True,
        )
        ids = [
            AnswerOption.objects.create(question=multi, text_de=f"M{i}", position=i).pk
            for i in range(3)
        ]
        ballot = ballots.open_ballot(self.meeting, multi)
        self.result(ballot)
        self.end()
        items = self.items(self.protocol())
        self.assertEqual([o["key"] for o in items["3"]["options"]], ["yes", "no", "abstain"])
        self.assertEqual(items["3"]["result"]["total"]["counts"]["yes"], 1)
        self.assertEqual((items["3"]["max_votes"], items["3"]["cumulate"]), (1, False))
        self.assertEqual(
            [o["key"] for o in items["4"]["options"]], [*(f"opt:{i}" for i in ids), "abstain"],
        )
        self.assertEqual((items["4"]["max_votes"], items["4"]["cumulate"]), (2, True))
        self.assertFalse(items["4"]["runoff"])

    def test_protocol_unvoted_election_options(self):
        single, _ids = self.election(n=1, max_votes=3)
        versions.sync(single)
        multi, ids = self.election(max_votes=2)
        multi.position = 4
        multi.save(update_fields=["position"])
        versions.sync(multi)
        self.end()
        items = self.items(self.protocol())
        self.assertEqual(items["3"]["status"], "not_voted")
        self.assertEqual([o["key"] for o in items["3"]["options"]], ["yes", "no", "abstain"])
        self.assertEqual((items["3"]["max_votes"], items["3"]["cumulate"]), (1, False))
        self.assertEqual(
            [o["key"] for o in items["4"]["options"]], [*(f"opt:{i}" for i in ids), "abstain"],
        )
        self.assertEqual(items["4"]["max_votes"], 2)

    def test_query_count_does_not_grow_with_items(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from . import protocol

        self.closed()
        self.closed(self.q2, [(self.anna, {"text": "Hallo"})])
        self.end()
        with CaptureQueriesContext(connection) as small:
            protocol.build(QuestionSet.objects.get(pk=self.meeting.pk))
        for n in range(3, 8):
            Question.objects.create(
                question_set=self.meeting, kind="resolution", text_de=f"Q{n}", position=n,
            )
        with CaptureQueriesContext(connection) as large:
            protocol.build(QuestionSet.objects.get(pk=self.meeting.pk))
        self.assertEqual(
            len(small), len(large),
            [q["sql"][:80] for q in small.captured_queries],
        )


class ProtocolPdfTests(BallotBase):
    closed = SealTests.closed

    def url(self):
        return f"/api/meetings/{self.meeting.pk}/protocol.pdf"

    def end(self):
        services.end_meeting(self.meeting)

    def text(self, response):
        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(response.content))
        return "\n".join(page.extract_text() for page in reader.pages)

    def scenario(self):
        """Secret result + finding, reset round, en bloc pair, named vote, TOP without vote,
        a legacy item without seal."""
        first = self.closed(answers=[(self.anna, {"choice": "no"})])
        ballots.reset_ballot(first, "Fehler")
        ballot = self.closed(answers=[(self.anna, {"choice": "yes"}), (self.ben, {"choice": "no"})])
        ballots.set_finding(ballot, "adopted")
        self.q2.named_vote = True
        self.q2.save(update_fields=["named_vote"])
        self.closed(self.q2, [(self.anna, {"text": "Hallo Welt"})])
        legacy = Question.objects.create(
            question_set=self.meeting, kind="resolution", text_de="Altfall", position=3,
        )
        versions.sync(legacy)
        old = ballots.open_ballot(self.meeting, legacy)
        self.vote(self.anna, old, {"choice": "yes"})
        ballots.close_ballot(old)
        SealLink.objects.filter(ballot=old).delete()
        r4 = Question.objects.create(
            question_set=self.meeting, kind="resolution", text_de="Vier", position=4,
        )
        r5 = Question.objects.create(
            question_set=self.meeting, kind="resolution", text_de="Fuenf", position=5,
        )
        for q in (r4, r5):
            versions.sync(q)
        bundle = ballots.open_bundle(self.meeting, [r4, r5])
        self.vote(self.anna, bundle, {"choice": "yes"})
        ballots.close_ballot(bundle)
        never = Question.objects.create(
            question_set=self.meeting, kind="resolution", text_de="Nie", position=6,
        )
        versions.sync(never)
        Section.objects.create(question_set=self.meeting, title_de="Verschiedenes", position=9)
        self.end()
        return ballot

    def test_download_german(self):
        ballot = self.scenario()
        r = self.client.get(self.url(), HTTP_ACCEPT_LANGUAGE="de")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertEqual(r["Cache-Control"], "no-store")
        self.assertRegex(
            r["Content-Disposition"], r'^attachment; filename="Protokoll-sitzung(-\d{4}-\d{2}-\d{2})?\.pdf"$',
        )
        text = self.text(r)
        for expected in (
            "Sitzung", "Anwesenheit", "TOP 1", "Feststellung: angenommen",
            "Abstimmung wiederholt (Durchgang 1)", "En bloc abgestimmt mit TOP",
            "Namentliche Abstimmung", "Kennung", "Kein Siegel", "Verschiedenes", "Seite 1 von",
            "Beobachtende", "Hallo Welt", "Ja:", "Nicht abgestimmt",
        ):
            self.assertIn(expected, text)
        fingerprint = SealLink.objects.get(ballot=ballot, kind="result").hash
        self.assertIn(fingerprint[:16], text)

    def test_english(self):
        self.scenario()
        r = self.client.get(self.url(), HTTP_ACCEPT_LANGUAGE="en")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Disposition"].startswith('attachment; filename="Protocol-sitzung'))
        text = self.text(r)
        self.assertIn("Attendance", text)
        self.assertIn("Page 1 of", text)

    def test_lang_param_overrides_browser_language(self):
        self.scenario()
        r = self.client.get(self.url() + "?lang=de", HTTP_ACCEPT_LANGUAGE="en")
        self.assertTrue(r["Content-Disposition"].startswith('attachment; filename="Protokoll-'))
        self.assertIn("Anwesenheit", self.text(r))
        r = self.client.get(self.url() + "?lang=en", HTTP_ACCEPT_LANGUAGE="de")
        self.assertTrue(r["Content-Disposition"].startswith('attachment; filename="Protocol-'))
        r = self.client.get(self.url() + "?lang=xx", HTTP_ACCEPT_LANGUAGE="en")
        self.assertTrue(r["Content-Disposition"].startswith('attachment; filename="Protocol-'))

    def test_filename_uses_scheduled_date(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo

        self.meeting.scheduled_at = datetime(2030, 1, 15, 11, 0, tzinfo=ZoneInfo("Europe/Berlin"))
        self.meeting.save(update_fields=["scheduled_at"])
        self.end()
        r = self.client.get(self.url(), HTTP_ACCEPT_LANGUAGE="de")
        self.assertIn("Protokoll-sitzung-2030-01-15.pdf", r["Content-Disposition"])
        self.assertIn("15. Januar 2030, 11:00", self.text(r))

    def test_protocol_pdf_election_rounds(self):
        q, (a, b, _c) = self.election(max_votes=2, cumulate=True)
        b1 = ballots.open_ballot(self.meeting, q)
        self.vote(self.anna, b1, {"options": [a, a]})
        self.result(b1)
        b1.refresh_from_db()
        b2 = ballots.open_runoff(self.meeting, b1, [a, b])
        self.vote(self.anna, b2, {"option": b})
        self.result(b2)
        self.end()
        text = self.text(self.client.get(self.url(), HTTP_ACCEPT_LANGUAGE="de"))
        self.assertIn("1. Wahlgang", text)
        self.assertIn("Stichwahl (2. Wahlgang)", text)
        self.assertIn("Bis zu 2 Stimmen pro Person, kumulieren erlaubt", text)
        self.assertIn("K0", text)
        self.assertLess(text.index("1. Wahlgang"), text.index("Stichwahl"))
        text = self.text(self.client.get(self.url(), HTTP_ACCEPT_LANGUAGE="en"))
        self.assertIn("Ballot 1", text)
        self.assertIn("Runoff (ballot 2)", text)

    def test_protocol_pdf_approval_has_no_votes_line(self):
        q, _ids = self.election(n=1, max_votes=3)
        ballot = ballots.open_ballot(self.meeting, q)
        self.vote(self.anna, ballot, {"choice": "yes"})
        self.result(ballot)
        self.end()
        text = self.text(self.client.get(self.url(), HTTP_ACCEPT_LANGUAGE="de"))
        self.assertIn("Ja: 1", text)
        self.assertNotIn("Bis zu", text)
        self.assertNotIn("Wahlgang", text)

    def test_requires_ended_meeting_and_manager(self):
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "not_ended")
        self.assertEqual(self.foreign.get(self.url()).status_code, 404)
        self.end()
        self.assertEqual(self.foreign.get(self.url()).status_code, 404)


class TrialTests(MeetingFixture, ApiBase):
    """Test run: a started meeting that leaves no trace (Decisions 8)."""

    def setUp(self):
        super().setUp()
        self.make_fixture(room=self.room)
        self.q1 = Question.objects.create(
            question_set=self.meeting, kind="resolution", text_de="Beschluss", position=1,
        )
        self.anna = self.member("Anna", self.ga)
        self.ben = self.member("Ben", self.gb)

    def url(self, action):
        return f"/api/meetings/{self.meeting.pk}/{action}/"

    def start(self, trial=True):
        r = self.client.post(self.url("start"), {"trial": trial}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return r

    def invite(self, member):
        return MeetingInvite.objects.select_related("meeting", "member").get(
            meeting=self.meeting, member=member,
        )

    def run_vote(self, voter=None):
        self.meeting.invites.update(entered_at=timezone.now())
        ballot = ballots.open_ballot(self.meeting, self.q1)
        ballots.cast_vote(self.invite(voter or self.anna), ballot.pk, {"choice": "yes"})
        with self.captureOnCommitCallbacks(execute=True):
            return ballots.close_ballot(ballot)

    def test_trial_start_and_vote_without_seal(self):
        r = self.start()
        self.assertTrue(r.json()["trial"])
        self.run_vote()
        self.assertFalse(SealLink.objects.exists())
        self.meeting.refresh_from_db()
        self.assertTrue(payloads.manager_payload(self.meeting)["trial"])
        self.assertTrue(payloads.public_payload(self.meeting)["trial"])

    def test_trial_end_resets_everything(self):
        dora = self.member("Dora", self.ga, role="deputy", rank=1)
        MeetingSubstitution.objects.create(
            meeting=self.meeting, absent=self.anna, deputy=dora,
        )
        self.start()
        ballot = self.run_vote(dora)
        MeetingInvite.objects.filter(member=self.ben).update(
            removed_at=timezone.now(), removed_after=self.q1,
        )
        ballots.secret_tally.start(987654)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(self.url("end"))
        self.assertEqual(r.status_code, 200, r.content)
        self.meeting.refresh_from_db()
        self.assertEqual(self.meeting.meeting_state, "draft")
        self.assertFalse(Ballot.objects.exists())
        self.assertFalse(BallotSeat.objects.exists())
        self.assertFalse(MotionVersion.objects.exists())
        for invite in self.meeting.invites.all():
            self.assertIsNone(invite.entered_at)
            self.assertIsNone(invite.removed_at)
            self.assertIsNone(invite.removed_after)
        control = MeetingControl.objects.get(meeting=self.meeting)
        self.assertFalse(control.trial)
        self.assertIsNone(control.started_at)
        self.assertIsNone(control.ended_at)
        self.assertEqual(MeetingSubstitution.objects.count(), 1)
        self.assertFalse(r.json()["trial"])
        self.assertFalse(ballots.secret_tally.has(ballot.pk))

    def test_trial_end_deletes_notes(self):
        self.start()
        r = self.client.put(
            self.url("notes"), {"question": self.q1.pk, "text": "Probe"}, format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(TopNote.objects.count(), 1)
        self.client.post(self.url("end"))
        self.assertFalse(TopNote.objects.exists())

    def test_real_start_after_trial(self):
        self.start()
        self.run_vote()
        self.client.post(self.url("end"))
        self.start(trial=False)
        self.assertEqual(list(self.q1.motion_versions.values_list("number", flat=True)), [1])
        ballot = self.run_vote()
        self.assertEqual(SealLink.objects.filter(ballot=ballot, kind="result").count(), 1)

    def test_trial_end_restores_agenda(self):
        s1 = Section.objects.create(question_set=self.meeting, title_de="Eins", position=0)
        Question.objects.filter(pk=self.q1.pk).update(section=s1, text_en="Motion")
        q2 = Question.objects.create(
            question_set=self.meeting, kind="single_choice", text_de="Wahl", position=2,
        )
        a = AnswerOption.objects.create(question=q2, text_de="A", text_en="A", position=0)
        b = AnswerOption.objects.create(question=q2, text_de="B", position=1)
        dora = self.member("Dora", self.ga, role="deputy", rank=1)
        self.start()
        r = self.client.patch(
            f"/api/questions/{self.q1.pk}/",
            {"text": {"de": "Geändert", "en": "Changed"}}, format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        r = self.client.patch(
            f"/api/questions/{q2.pk}/",
            {"options": [
                {"id": a.pk, "text": {"de": "A2", "en": "A2"}},
                {"text": {"de": "C"}},
            ]},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(AnswerOption.objects.filter(pk=b.pk).exists())
        sub_item = services.add_resolution(self.meeting, "Änderung", s1, named=False)
        new_top = services.add_resolution(self.meeting, "Neuer TOP", None, named=False)
        new_section = Section.objects.create(
            question_set=self.meeting, title_de="Neu", position=10,
        )
        MeetingSubstitution.objects.create(
            meeting=self.meeting, absent=self.anna, deputy=dora, from_question=sub_item,
        )
        MeetingInvite.objects.filter(member=self.ben).update(
            removed_at=timezone.now(), removed_after=new_top,
        )
        self.run_vote()
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post(self.url("end"))
        self.assertEqual(r.status_code, 200, r.content)

        self.assertEqual(
            set(self.meeting.questions.values_list("pk", flat=True)), {self.q1.pk, q2.pk},
        )
        self.assertFalse(Section.objects.filter(pk=new_section.pk).exists())
        self.assertEqual(list(self.meeting.sections.values_list("pk", flat=True)), [s1.pk])
        self.q1.refresh_from_db()
        self.assertEqual((self.q1.text_de, self.q1.text_en), ("Beschluss", "Motion"))
        self.assertEqual(
            list(q2.options.values_list("pk", "text_de", "text_en")),
            [(a.pk, "A", "A"), (b.pk, "B", "")],
        )
        self.assertEqual(
            dict(self.meeting.questions.values_list("pk", "position")),
            {self.q1.pk: 1, q2.pk: 2},
        )
        self.assertIsNone(MeetingSubstitution.objects.get().from_question_id)
        self.assertIsNone(MeetingControl.objects.get(meeting=self.meeting).trial_snapshot)
        self.assertFalse(MotionVersion.objects.exists())

        self.start(trial=False)
        self.assertIsNone(MeetingControl.objects.get(meeting=self.meeting).trial_snapshot)
        self.assertEqual(
            self.q1.motion_versions.get().text_de, "Beschluss",
        )
        ballot = self.run_vote(dora)  # Anna is substituted from the start now
        self.assertEqual(SealLink.objects.filter(ballot=ballot, kind="result").count(), 1)

    def test_trial_finding_rejected(self):
        self.start()
        ballot = self.run_vote()
        r = self.client.post(
            self.url(f"ballots/{ballot.pk}/finding"), {"finding": "adopted"}, format="json",
        )
        self.assertEqual((r.status_code, r.json()["code"]), (400, "trial"))

    def test_trial_protocol_400(self):
        self.start()
        r = self.client.get(self.url("protocol"))
        self.assertEqual((r.status_code, r.json()["code"]), (400, "not_ended"))

    def test_trial_end_with_open_vote_blocked(self):
        self.start()
        self.meeting.invites.update(entered_at=timezone.now())
        ballots.open_ballot(self.meeting, self.q1)
        r = self.client.post(self.url("end"))
        self.assertEqual((r.status_code, r.json()["code"]), (400, "vote_open"))


class TopNoteTests(BallotBase):
    closed = SealTests.closed

    def setUp(self):
        super().setUp()
        self.s1 = Section.objects.create(question_set=self.meeting, title_de="Eins", position=5)
        self.q3 = Question.objects.create(
            question_set=self.meeting, kind="resolution", text_de="Drei", position=6,
            section=self.s1,
        )
        versions.sync(self.q3)

    def url(self):
        return f"/api/meetings/{self.meeting.pk}/notes/"

    def put(self, **body):
        return self.client.put(self.url(), body, format="json")

    def test_set_update_clear_on_section(self):
        r = self.put(section=self.s1.pk, text="Erste\nZweite")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(
            r.json()["notes"],
            [{"section": self.s1.pk, "question": None, "text": "Erste\nZweite"}],
        )
        r = self.put(section=self.s1.pk, text="Neu")
        self.assertEqual(r.json()["notes"][0]["text"], "Neu")
        self.assertEqual(TopNote.objects.count(), 1)
        r = self.put(section=self.s1.pk, text="")
        self.assertEqual(r.json()["notes"], [])
        self.assertEqual(TopNote.objects.count(), 0)

    def test_standalone_question(self):
        r = self.put(question=self.q1.pk, text="Hinweis")
        self.assertEqual(
            r.json()["notes"], [{"section": None, "question": self.q1.pk, "text": "Hinweis"}],
        )
        self.put(question=self.q1.pk, text="  ")
        self.assertEqual(TopNote.objects.count(), 0)

    def test_validation(self):
        self.assertEqual(self.put(section=self.s1.pk, text="x" * 2001).json()["code"], "invalid")
        self.assertEqual(self.put(section=self.s1.pk, text="x" * 2000).status_code, 200)
        self.assertEqual(self.put(text="x").json()["code"], "invalid")
        self.assertEqual(
            self.put(section=self.s1.pk, question=self.q1.pk, text="x").json()["code"], "invalid",
        )
        self.assertEqual(self.put(section=self.s1.pk, text=5).json()["code"], "invalid")
        other = self.make_other_meeting()
        self.assertEqual(self.put(question=other.pk, text="x").status_code, 404)
        with self.assertRaises(ValidationError) as ctx:
            services.set_top_note(
                self.meeting, section=Section.objects.create(
                    question_set=QuestionSet.objects.create(room=self.room, title_de="Y"),
                    title_de="F", position=1,
                ), text="x",
            )
        self.assertEqual(ctx.exception.code, "invalid")

    def test_question_in_section_rejected(self):
        r = self.put(question=self.q3.pk, text="x")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "invalid")
        self.assertFalse(TopNote.objects.exists())

    def test_notes_only_in_manager_stream_payloads(self):
        from . import live

        self.put(section=self.s1.pk, text="Geheim")
        self.meeting.refresh_from_db()
        self.assertNotIn("Geheim", json.dumps(payloads.public_payload(self.meeting)))
        with open(live.__file__) as f:
            src = f.read()
        self.assertEqual(src.count("manager_payload"), 2)  # broadcast + manager stream only

    def make_other_meeting(self):
        other = QuestionSet.objects.create(room=self.room, title_de="Andere")
        return Question.objects.create(
            question_set=other, kind="resolution", text_de="F", position=1,
        )

    def test_editable_after_end(self):
        self.put(section=self.s1.pk, text="Notiz")
        services.end_meeting(self.meeting)
        r = self.put(section=self.s1.pk, text="X hat wegen Befangenheit nicht mit abgestimmt.")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(TopNote.objects.get().text, "X hat wegen Befangenheit nicht mit abgestimmt.")
        self.assertEqual(self.put(section=self.s1.pk, text="").status_code, 200)
        self.assertFalse(TopNote.objects.exists())
        from . import protocol

        tops = protocol.build(self.meeting)["tops"]
        top = next(t for t in tops if t["section"] == self.s1.pk)
        self.assertIsNone(top["question"])

    def test_not_in_draft(self):
        draft = QuestionSet.objects.create(
            room=self.room, title="Entwurf", type=QuestionSet.SetType.MEETING,
        )
        q = Question.objects.create(question_set=draft, kind="resolution", text_de="X")
        r = self.client.put(
            f"/api/meetings/{draft.pk}/notes/", {"question": q.pk, "text": "Vorab"}, format="json",
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["code"], "not_started")

    def test_manager_only(self):
        self.meeting.refresh_from_db()
        self.put(section=self.s1.pk, text="Geheim")
        self.assertEqual(
            self.foreign.put(self.url(), {"section": self.s1.pk, "text": "x"}, format="json")
            .status_code, 404,
        )
        self.assertIn("notes", payloads.manager_payload(self.meeting))
        self.assertNotIn("Geheim", json.dumps(payloads.public_payload(self.meeting)))
        self.assertNotIn("notes", payloads.public_payload(self.meeting))

    def test_protocol_and_pdf(self):
        self.closed(answers=[(self.anna, {"choice": "yes"})])
        self.put(section=self.s1.pk, text="Zeile eins\nZeile <b>zwei</b>")
        self.put(question=self.q1.pk, text="Einzelnotiz")
        services.end_meeting(self.meeting)
        data = self.client.get(f"/api/meetings/{self.meeting.pk}/protocol/").json()
        notes = {t["title"]: t["note"] for t in data["tops"]}
        self.assertEqual(notes["Eins"], "Zeile eins\nZeile <b>zwei</b>")
        top_q1 = next(t for t in data["tops"] if any(i["label"] == "1" for i in t["items"]))
        self.assertEqual(top_q1["note"], "Einzelnotiz")
        top_q2 = next(t for t in data["tops"] if any(i["label"] == "2" for i in t["items"]))
        self.assertEqual(top_q2["note"], "")
        r = self.client.get(f"/api/meetings/{self.meeting.pk}/protocol.pdf?lang=de")
        self.assertEqual(r.status_code, 200)
        from io import BytesIO

        from pypdf import PdfReader

        text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(r.content)).pages)
        self.assertIn("Notiz: Zeile eins", text)
        self.assertIn("Zeile <b>zwei</b>", text)
        self.assertIn("Einzelnotiz", text)

    def test_long_note_pdf(self):
        lines = [f"Z{i:02d} " + "wort " * 16 for i in range(20)]
        note = "\n".join(lines)[:1990] + "\nENDEMARKE"
        self.assertLessEqual(len(note), 2000)
        self.put(section=self.s1.pk, text=note)
        services.end_meeting(self.meeting)
        r = self.client.get(f"/api/meetings/{self.meeting.pk}/protocol.pdf")
        self.assertEqual(r.status_code, 200)
        from io import BytesIO

        from pypdf import PdfReader

        text = "\n".join(p.extract_text() for p in PdfReader(BytesIO(r.content)).pages)
        self.assertIn("Z00", text)
        self.assertIn("ENDEMARKE", text)


class ElectionConfigTests(MeetingFixture, ApiBase):
    def setUp(self):
        super().setUp()
        self.make_fixture(room=self.room)

    def post_item(self, **extra):
        body = {
            "question_set": self.meeting.pk, "kind": "election",
            "text": {"de": "Wahl"}, **extra,
        }
        return self.client.post("/api/questions/", body, format="json")

    def test_meeting_accepts_election_kind(self):
        r = self.post_item(max_votes=3)
        self.assertEqual(r.status_code, 201, r.content)
        self.assertEqual(r.json()["max_votes"], 3)
        self.assertIs(r.json()["cumulate"], False)

    def test_live_poll_rejects_election_kind(self):
        live = QuestionSet.objects.create(room=make_room(), title="L")
        live.room.owners.add(self.user)
        r = self.client.post(
            "/api/questions/",
            {"question_set": live.pk, "kind": "election", "text": {"de": "X"}},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_max_votes_bounds(self):
        for bad in (0, 21):
            r = self.post_item(max_votes=bad)
            self.assertEqual(r.status_code, 400, bad)
            self.assertEqual(r.json()["max_votes"], ["Between 1 and 20 votes."])

    def test_election_settings_locked_while_voted(self):
        q = self.post_item(max_votes=2).json()
        question = Question.objects.get(pk=q["id"])
        versions.freeze_all(self.meeting)
        Ballot.objects.create(
            question=question, version=versions.current(question), round=1,
            secret=True, status=Ballot.Status.CLOSED,
        )
        for field, value in (("max_votes", 3), ("cumulate", True)):
            r = self.client.patch(
                f"/api/questions/{q['id']}/", {field: value}, format="json",
            )
            self.assertEqual(r.status_code, 400, field)
            self.assertIn("Reset the vote", r.json()["detail"])

    def test_duplicate_and_export_keep_election_settings(self):
        self.meeting.title_de = self.meeting.title_en = "Sitzung"
        self.meeting.save()
        self.post_item(max_votes=3, cumulate=True)
        r = self.client.post(f"/api/question-sets/{self.meeting.pk}/duplicate/", {}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        copy = Question.objects.get(question_set_id=r.json()["id"])
        self.assertEqual((copy.kind, copy.max_votes, copy.cumulate), ("election", 3, True))

        data = self.client.get(f"/api/question-sets/{self.meeting.pk}/export/").json()
        self.assertEqual(data["questions"][0]["max_votes"], 3)
        # Meetings are never imported (transfer.import_set rejects them), so
        # only the sanitising of the imported settings is checked.
        from rooms.transfer import _clamped_max_votes
        self.assertEqual(
            [_clamped_max_votes(v) for v in (None, "x", 0, 3, 99)], [1, 1, 1, 3, 20],
        )

    def test_empty_candidate_text_rejected_single_candidate_ok(self):
        q = self.post_item().json()
        url = f"/api/questions/{q['id']}/"
        r = self.client.patch(
            url, {"text": {"de": "Wahl"}, "options": [{"text": {"de": "Anna"}}, {"text": {"de": ""}}]},
            format="json",
        )
        self.assertEqual(r.status_code, 400, r.content)
        self.assertIn("options", r.json())
        r = self.client.patch(
            url, {"text": {"de": "Wahl"}, "options": [{"text": {"de": "Anna"}}]}, format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)


class ElectionBallotTests(BallotBase):
    def test_approval_single_candidate(self):
        q, (a,) = self.election(n=1)
        ballot = ballots.open_ballot(self.meeting, q)
        self.assertEqual(ballots.election_mode(ballot), "approval")
        self.assertCode("invalid", self.vote, self.anna, ballot, {"options": [a]})
        self.assertCode("invalid", self.vote, self.anna, ballot, {"option": a})
        self.vote(self.anna, ballot, {"choice": "yes"})
        self.vote(self.bert, ballot, {"choice": "no"})
        self.vote(self.ben, ballot, {"choice": "abstain"})
        self.assertEqual(
            self.result(ballot)["total"]["counts"], {"yes": 1, "no": 1, "abstain": 1},
        )

    def test_single_mode_has_no(self):
        q, (a, b, c) = self.election()
        ballot = ballots.open_ballot(self.meeting, q)
        self.assertEqual(ballots.election_mode(ballot), "single")
        self.assertCode("invalid", self.vote, self.anna, ballot, {"options": [a]})
        self.assertCode("invalid", self.vote, self.anna, ballot, {"choice": "yes"})
        self.vote(self.anna, ballot, {"choice": "no"})
        self.vote(self.bert, ballot, {"option": b})
        counts = self.result(ballot)["total"]["counts"]
        self.assertEqual(
            counts,
            {f"opt:{a}": 0, f"opt:{b}": 1, f"opt:{c}": 0, "no": 1, "abstain": 0},
        )

    def test_multi_has_no_no(self):
        q, (a, b, c) = self.election(max_votes=2)
        ballot = ballots.open_ballot(self.meeting, q)
        self.assertEqual(ballots.election_mode(ballot), "multi")
        self.assertCode("invalid", self.vote, self.anna, ballot, {"choice": "no"})
        self.vote(self.anna, ballot, {"options": [a, b]})
        counts = self.result(ballot)["total"]["counts"]
        self.assertNotIn("no", counts)
        self.assertEqual(
            counts, {f"opt:{a}": 1, f"opt:{b}": 1, f"opt:{c}": 0, "abstain": 0},
        )

    def test_multi_pads_unspent_votes_as_abstain(self):
        q, (a, _b, _c) = self.election(max_votes=3)
        ballot = ballots.open_ballot(self.meeting, q)
        self.vote(self.anna, ballot, {"options": [a]})
        self.vote(self.bert, ballot, {"choice": "abstain"})
        result = self.result(ballot)
        counts = result["total"]["counts"]
        self.assertEqual(counts["abstain"], 2 + 3)
        self.assertEqual(counts[f"opt:{a}"], 1)
        self.assertEqual(sum(counts.values()), result["voted"] * 3)
        self.assertEqual(result["tally_sum"], 2)
        self.assertEqual(result["voted"], 2)

    def test_multi_rejects_too_many_and_repeats(self):
        q, (a, b, c) = self.election(max_votes=2)
        other = AnswerOption.objects.create(question=self.q2, text_de="X")
        ballot = ballots.open_ballot(self.meeting, q)
        for bad in (
            {"options": [a, b, c]}, {"options": [a, a]}, {"options": []},
            {"options": [other.pk]}, {"options": [True]}, {"options": [a], "x": 1},
            {"option": a},
        ):
            self.assertCode("invalid", self.vote, self.anna, ballot, bad)

    def test_cumulate_allows_repeats(self):
        q, (a, _b, _c) = self.election(max_votes=3, cumulate=True)
        ballot = ballots.open_ballot(self.meeting, q)
        self.vote(self.anna, ballot, {"options": [a, a, a]})
        self.assertEqual(self.result(ballot)["total"]["counts"][f"opt:{a}"], 3)

    def test_start_validates_config(self):
        q, _ = self.election(n=0)
        self.assertCode("no_candidates", ballots.open_ballot, self.meeting, q)
        q.delete()
        q, _ = self.election(n=2, max_votes=3)
        self.assertCode("too_many_votes", ballots.open_ballot, self.meeting, q)
        q.cumulate = True
        q.save()
        ballot = ballots.open_ballot(self.meeting, q)
        self.assertEqual((ballot.max_votes, ballot.cumulate), (3, True))
        self.assertIsNone(ballot.candidates)

    def test_approval_ignores_max_votes(self):
        q, _ = self.election(n=1, max_votes=3)
        ballot = ballots.open_ballot(self.meeting, q)
        self.assertEqual((ballot.max_votes, ballot.cumulate), (1, False))
        self.assertEqual(ballots.election_mode(ballot), "approval")

    def test_named_election_stores_keys(self):
        q, (a, _b, _c) = self.election(max_votes=3, named=True)
        ballot = ballots.open_ballot(self.meeting, q)
        self.assertFalse(ballot.secret)
        self.vote(self.anna, ballot, {"options": [a]})
        vote = NamedVote.objects.get(ballot=ballot, member=self.anna)
        self.assertEqual(vote.answer["keys"], [f"opt:{a}", "abstain", "abstain"])

    def test_parse_answer_needs_ballot_for_elections(self):
        q, (a, _b, _c) = self.election()
        self.assertCode("invalid", ballots.parse_answer, q, {"option": a})
        self.assertCode("invalid", ballots.parse_answer, q, {"choice": "abstain"})

    def test_election_seal_includes_settings(self):
        q, (a, _b, _c) = self.election(max_votes=2)
        ballot = ballots.open_ballot(self.meeting, q)
        self.vote(self.anna, ballot, {"options": [a]})
        self.result(ballot)
        content = seals._result_content(Ballot.objects.get(pk=ballot.pk), "R")
        self.assertEqual(
            content["election"],
            {"max_votes": 2, "cumulate": False, "candidates": None, "runoff_of": None},
        )
        res = ballots.open_ballot(self.meeting, self.q1)
        self.vote(self.anna, res, {"choice": "yes"})
        self.result(res)
        self.assertNotIn("election", seals._result_content(Ballot.objects.get(pk=res.pk), "R"))


class RunoffTests(BallotBase):
    def url(self, suffix):
        return f"/api/meetings/{self.meeting.pk}/{suffix}"

    def closed_round(self, n=3, max_votes=1, counts=None):
        """A closed first election round; ``counts`` overrides its totals."""
        q, ids = self.election(n=n, max_votes=max_votes)
        ballot = ballots.open_ballot(self.meeting, q)
        self.result(ballot)
        ballot.refresh_from_db()
        if counts is not None:
            total = ballot.result["total"]["counts"]
            total.update({f"opt:{ids[i]}": c for i, c in enumerate(counts)})
            ballot.save(update_fields=["result"])
        return q, ids, ballot

    def test_runoff_proposal_top_two(self):
        _, (a, b, _c), ballot = self.closed_round(counts=[5, 3, 1])
        self.assertEqual(ballots.runoff_proposal(ballot), [a, b])

    def test_runoff_proposal_includes_ties(self):
        _, (a, b, c, d), ballot = self.closed_round(n=4, counts=[4, 2, 2, 2])
        self.assertEqual(ballots.runoff_proposal(ballot), [a, b, c, d])

    def test_runoff_proposal_ignores_no_and_abstain(self):
        _, (a, b, _c), ballot = self.closed_round(counts=[3, 2, 0])
        ballot.result["total"]["counts"].update({"no": 9, "abstain": 7})
        self.assertEqual(ballots.runoff_proposal(ballot), [a, b])

    def test_runoff_proposal_none_for_approval_and_open(self):
        _, _, approval = self.closed_round(n=1)
        self.assertIsNone(ballots.runoff_proposal(approval))
        q, _ = self.election()
        ballot = ballots.open_ballot(self.meeting, q)
        self.assertIsNone(ballots.runoff_proposal(ballot))
        self.result(ballot)
        resolution = ballots.open_ballot(self.meeting, self.q1)
        self.result(resolution)
        resolution.refresh_from_db()
        self.assertIsNone(ballots.runoff_proposal(resolution))

    def test_open_runoff(self):
        _q, (a, b, c), b1 = self.closed_round()
        b2 = ballots.open_runoff(self.meeting, b1, [b, a])
        self.assertEqual(b2.round, 2)
        self.assertEqual(b2.max_votes, 1)
        self.assertEqual(b2.runoff_of, b1)
        self.assertEqual(b2.candidates, [a, b])  # normalized to version order
        self.assertEqual(b2.status, Ballot.Status.OPEN)
        self.assertCode("invalid", self.vote, self.anna, b2, {"option": c})
        self.vote(self.anna, b2, {"option": a})
        self.result(b2)
        b2 = Ballot.objects.get(pk=b2.pk)
        self.assertTrue(seals.reference(b2).endswith("-W2"))
        self.assertEqual(b2.result["total"]["counts"][f"opt:{a}"], 1)
        self.assertNotIn(f"opt:{c}", b2.result["total"]["counts"])
        content = seals._result_content(b2, "R")
        self.assertEqual(
            content["election"],
            {"max_votes": 1, "cumulate": False, "candidates": [a, b], "runoff_of": b1.pk},
        )

    def test_runoff_over_two_of_three_is_single(self):
        _, (a, _b, c), b1 = self.closed_round(max_votes=2)
        b2 = ballots.open_runoff(self.meeting, b1, [a, c])
        self.assertEqual([o["id"] for o in ballots.ballot_options(b2)], [a, c])
        self.assertEqual(ballots.election_mode(b2), "single")
        self.assertEqual((b2.max_votes, b2.cumulate), (1, False))

    def test_open_runoff_rejects(self):
        _q, (a, b, _c), b1 = self.closed_round()
        other = AnswerOption.objects.create(question=self.q2, text_de="X")
        for bad in (
            [a], [a, a], [a, other.pk], [], "x", None, [a, True], [[a], b], [a, "b"],
        ):
            self.assertCode("runoff_candidates", ballots.open_runoff, self.meeting, b1, bad)
        res = ballots.open_ballot(self.meeting, self.q1)
        self.assertCode("other_open", ballots.open_runoff, self.meeting, b1, [a, b])
        self.assertCode("not_an_election", ballots.open_runoff, self.meeting, res, [a, b])
        self.result(res)
        res.refresh_from_db()
        self.assertCode("not_an_election", ballots.open_runoff, self.meeting, res, [a, b])
        b2 = ballots.open_runoff(self.meeting, b1, [a, b])
        self.assertCode("not_closed", ballots.open_runoff, self.meeting, b2, [a, b])
        self.result(b2)
        self.assertCode("runoff_exists", ballots.open_runoff, self.meeting, b1, [a, b])
        _, _, approval = self.closed_round(n=1)
        self.assertCode("not_an_election", ballots.open_runoff, self.meeting, approval, [a, b])

    def test_runoff_of_a_runoff(self):
        _, (a, b, c), b1 = self.closed_round()
        b2 = ballots.open_runoff(self.meeting, b1, [a, b, c])
        self.result(b2)
        b2.refresh_from_db()
        self.assertCode("runoff_candidates", ballots.open_runoff, self.meeting, b2, [a])
        b3 = ballots.open_runoff(self.meeting, b2, [a, b])
        self.assertEqual((b3.round, b3.runoff_of_id), (3, b2.pk))

    def test_reset_first_round_blocked_by_runoff(self):
        _, (a, b, _c), b1 = self.closed_round()
        b2 = ballots.open_runoff(self.meeting, b1, [a, b])
        self.assertCode("runoff_exists", ballots.reset_ballot, b1, "")
        b1.refresh_from_db()
        self.assertEqual(b1.status, Ballot.Status.CLOSED)
        ballots.reset_ballot(b2, "")
        ballots.reset_ballot(b1, "")
        b1.refresh_from_db()
        self.assertEqual(b1.status, Ballot.Status.DISCARDED)

    def test_runoff_seats_follow_course(self):
        q, (a, b, _c), b1 = self.closed_round()
        later = Question.objects.create(
            question_set=self.meeting, kind="resolution", text_de="Später", position=4,
        )
        services.add_substitution(self.meeting, self.anna, self.dora, from_question=later)
        self.meeting.invites.update(entered_at=timezone.now())
        self.assertIn(self.dora, eligibility.eligible_voters(self.meeting, later))
        b2 = ballots.open_runoff(self.meeting, b1, [a, b])
        seats = set(b2.seats.values_list("member_id", flat=True))
        self.assertEqual(seats, set(b1.seats.values_list("member_id", flat=True)))
        self.assertEqual(seats, {self.anna.pk, self.bert.pk, self.ben.pk})
        self.assertEqual(
            seats, {m.pk for m in eligibility.eligible_voters(self.meeting, q)},
        )

    def test_public_payload_lists_runoff_candidates_only(self):
        _q, (a, b, c), b1 = self.closed_round(counts=[3, 2, 1])
        item = payloads.public_payload(self.meeting)["item"]
        self.assertEqual([o["id"] for o in item["options"]], [a, b, c])
        self.assertEqual(
            item["election"],
            {"mode": "single", "max_votes": 1, "cumulate": False, "runoff": False},
        )
        self.assertEqual(
            item["ballot"]["election"],
            {
                "mode": "single", "max_votes": 1, "cumulate": False,
                "candidates": [a, b, c], "runoff_of": None, "proposal": [a, b],
            },
        )
        b2 = ballots.open_runoff(self.meeting, b1, [a, b])
        item = payloads.public_payload(self.meeting)["item"]
        self.assertEqual([o["id"] for o in item["options"]], [a, b])
        self.assertEqual(set(item["options"][0]), {"id", "text"})
        self.assertEqual(item["election"]["runoff"], True)
        self.assertEqual(
            item["ballot"]["election"],
            {
                "mode": "single", "max_votes": 1, "cumulate": False,
                "candidates": [a, b], "runoff_of": b1.pk, "proposal": None,
            },
        )
        self.assertEqual(item["ballot"]["id"], b2.pk)

    def test_election_block_before_first_ballot_and_for_resolutions(self):
        q, _ = self.election(n=1, max_votes=3)
        MeetingControl.objects.update_or_create(
            meeting=self.meeting, defaults={"current_question": q},
        )
        item = payloads.public_payload(self.meeting)["item"]
        self.assertEqual(
            item["election"],
            {"mode": "approval", "max_votes": 1, "cumulate": False, "runoff": False},
        )
        self.assertEqual(
            payloads.preview_payload(q)["item"]["election"], item["election"],
        )
        multi, _ = self.election(max_votes=2)
        self.assertEqual(
            payloads.preview_payload(multi)["item"]["election"],
            {"mode": "multi", "max_votes": 2, "cumulate": False, "runoff": False},
        )
        ballots.open_ballot(self.meeting, self.q1)
        item = payloads.public_payload(self.meeting)["item"]
        self.assertIsNone(item["election"])
        self.assertIsNone(item["ballot"]["election"])
        self.assertIsNone(payloads.preview_payload(self.q1)["item"]["election"])

    def test_runoff_api(self):
        _, (a, b, _c), b1 = self.closed_round()
        url = self.url(f"ballots/{b1.pk}/runoff/")
        resp = self.foreign.post(url, {"candidates": [a, b]}, format="json")
        self.assertEqual(resp.status_code, 404)
        for body in ({}, {"candidates": "x"}, {"candidates": [a]}):
            resp = self.client.post(url, body, format="json")
            self.assertEqual((resp.status_code, resp.data["code"]), (400, "runoff_candidates"))
        resp = self.client.post(url, {"candidates": [a, b]}, format="json")
        self.assertEqual(resp.status_code, 200)
        b2 = Ballot.objects.get(runoff_of=b1)
        self.assertEqual(resp.data["open_ballot"], b2.pk)
        self.assertEqual(
            [o["id"] for o in resp.data["item"]["options"]], [a, b],
        )
        resp = self.client.post(
            self.url("ballots/999999/runoff/"), {"candidates": [a, b]}, format="json",
        )
        self.assertEqual(resp.status_code, 404)
