# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from rooms.models import QuestionSet, Room

from .models import CommitteeGroup, CommitteeMember, GroupTemplate, MeetingInvite


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
