# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

import json
import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone, translation
from rest_framework.test import APIClient

from rooms.models import AnswerOption, Question, QuestionSet, Room, Section

from . import agenda, ballots, eligibility, services, versions
from .models import (
    Ballot,
    BallotSeat,
    BallotText,
    CommitteeGroup,
    CommitteeMember,
    GroupTemplate,
    MeetingInvite,
    MeetingSubstitution,
    NamedVote,
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


class MeetingServiceTests(MeetingFixture, TestCase):
    def setUp(self):
        self.make_fixture()

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
        self.assertEqual(item["number"], 1)
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
        self.assertEqual(eligibility.number_of(self.meeting, self.q3), 3)

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
        self.vote(self.bert, ballot, {"choice": "abstain"})
        with self.captureOnCommitCallbacks(execute=True):
            result = ballots.close_ballot(ballot).result
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
        self.vote(self.bert, ballot, {"choice": "abstain"})
        self.assertEqual(BallotText.objects.count(), 0)
        ballot = ballots.close_ballot(ballot)
        self.assertEqual(
            sorted(BallotText.objects.values_list("text", flat=True)), ["Erstens", "Zweitens"],
        )
        self.assertEqual(ballot.result["total"]["counts"], {"text": 2, "abstain": 1})
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
        self.assertEqual(public["item"]["number"], 1)
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
        from common.views import render_prometheus

        text = render_prometheus()
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
