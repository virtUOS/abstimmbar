# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APIClient

from rooms.models import QuestionSet, Room

from .models import CommitteeGroup, CommitteeMember, GroupTemplate, MeetingInvite
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
