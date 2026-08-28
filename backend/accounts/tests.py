# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

import importlib

from django.apps import apps as django_apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from rooms.models import Question, Room

User = get_user_model()


# Force the translation provider off explicitly (#33 MR2) — the dev
# container's real .env configures LibreTranslate, so without this override
# these tests would depend on out-of-band environment state.
LT_OFF = {"CONTENT_TRANSLATION_PROVIDER": "none", "LIBRETRANSLATE_URL": ""}


class WhoamiTests(TestCase):
    @override_settings(**LT_OFF)
    def test_anonymous(self):
        response = self.client.get("/api/whoami/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["authenticated"])
        # An authoritative CSRF token is returned so the SPA can send unsafe
        # requests reliably (esp. cross-origin in dev).
        self.assertTrue(payload["csrf_token"])
        # Content-i18n config (#33 MR2): the canonical authoring language and
        # whether machine-translation drafts are available.
        self.assertEqual(
            payload["content_default_language"], settings.MODELTRANSLATION_DEFAULT_LANGUAGE
        )
        self.assertFalse(payload["content_translation_enabled"])

    @override_settings(**LT_OFF)
    def test_authenticated(self):
        user = User.objects.create_user(
            username="frank", email="frank@uni-osnabrueck.de", subject="abc-123"
        )
        self.client.force_login(user)
        payload = self.client.get("/api/whoami/").json()
        self.assertTrue(payload["authenticated"])
        self.assertEqual(payload["username"], "frank")
        self.assertEqual(payload["subject"], "abc-123")
        self.assertFalse(payload["is_staff"])
        self.assertEqual(
            payload["content_default_language"], settings.MODELTRANSLATION_DEFAULT_LANGUAGE
        )
        self.assertFalse(payload["content_translation_enabled"])

    @override_settings(
        CONTENT_TRANSLATION_PROVIDER="libretranslate", LIBRETRANSLATE_URL="http://lt"
    )
    def test_content_translation_enabled_reflects_provider_config(self):
        payload = self.client.get("/api/whoami/").json()
        self.assertTrue(payload["content_translation_enabled"])


class OnboardingSeedOnWhoamiTests(TestCase):
    """First-login example room seeding (#78), guarded by User.onboarded."""

    @override_settings(**LT_OFF)
    def test_fresh_user_gets_seeded_exactly_once(self):
        user = User.objects.create_user(username="fresh")
        self.assertFalse(user.onboarded)
        self.client.force_login(user)

        self.client.get("/api/whoami/")

        user.refresh_from_db()
        self.assertTrue(user.onboarded)
        rooms = Room.objects.filter(owners=user)
        self.assertEqual(rooms.count(), 1)
        room = rooms.get()
        question_set = room.question_sets.get()
        kinds = set(question_set.questions.values_list("kind", flat=True))
        self.assertEqual(kinds, set(Question.Kind.values))

    @override_settings(**LT_OFF)
    def test_second_whoami_does_not_duplicate_the_room(self):
        user = User.objects.create_user(username="fresh2")
        self.client.force_login(user)

        self.client.get("/api/whoami/")
        self.client.get("/api/whoami/")

        self.assertEqual(Room.objects.filter(owners=user).count(), 1)

    @override_settings(**LT_OFF)
    def test_existing_user_with_onboarded_false_is_seeded_too(self):
        # Simulates an account created before #78: onboarded defaults to
        # False, so it is seeded on its next whoami just like a new user.
        existing = User.objects.create_user(username="veteran")
        self.assertFalse(existing.onboarded)
        self.client.force_login(existing)

        self.client.get("/api/whoami/")

        existing.refresh_from_db()
        self.assertTrue(existing.onboarded)
        self.assertEqual(Room.objects.filter(owners=existing).count(), 1)

    @override_settings(**LT_OFF)
    def test_already_onboarded_user_is_not_seeded_again(self):
        user = User.objects.create_user(username="done", onboarded=True)
        self.client.force_login(user)

        self.client.get("/api/whoami/")

        self.assertEqual(Room.objects.filter(owners=user).count(), 0)

    @override_settings(**LT_OFF)
    def test_anonymous_whoami_seeds_nothing(self):
        before = Room.objects.count()
        response = self.client.get("/api/whoami/")
        self.assertFalse(response.json()["authenticated"])
        self.assertEqual(Room.objects.count(), before)


class SetLanguageTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="lena", password="x"
        )

    def test_sets_supported_language(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            "/api/whoami/language/",
            data={"language": "en"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.language, "en")

    def test_rejects_unknown_language(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            "/api/whoami/language/",
            data={"language": "fr"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_requires_authentication(self):
        resp = self.client.post(
            "/api/whoami/language/",
            data={"language": "de"},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_rejects_non_dict_body(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            "/api/whoami/language/",
            data="[]",
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_rejects_non_string_language_without_error(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            "/api/whoami/language/",
            data={"language": 123},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 400)


class EasyModeTests(TestCase):
    """Per-user Easy/Pro mode preference.

    ``easy_mode`` is tri-state (None = not chosen yet). The *effective*
    value falls back to a role default when unset: non-staff start simple,
    staff start pro — but staff may explicitly opt into simple mode too
    (admins' default stays Pro, it is no longer a hard mask)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="lena", password="x"
        )
        self.staff = get_user_model().objects.create_user(
            username="chef", password="x", is_staff=True
        )

    def test_effective_easy_mode_property(self):
        u = User(is_staff=False)
        u.easy_mode = None
        self.assertTrue(u.effective_easy_mode)  # non-staff default = simple
        u.is_staff = True
        self.assertFalse(u.effective_easy_mode)  # staff default = pro
        u.easy_mode = True
        self.assertTrue(u.effective_easy_mode)  # explicit wins (staff simple)
        u.easy_mode = False
        self.assertFalse(u.effective_easy_mode)
        u = User(is_staff=False)
        u.easy_mode = True
        self.assertTrue(u.effective_easy_mode)  # explicit non-staff simple
        u.easy_mode = False
        self.assertFalse(u.effective_easy_mode)  # explicit non-staff pro

    def test_whoami_reflects_effective_easy_mode_for_regular_user(self):
        self.client.force_login(self.user)
        payload = self.client.get("/api/whoami/").json()
        # The underlying field defaults to None (not chosen); non-staff
        # fall back to the simple role default, so effective easy_mode is
        # True.
        self.assertTrue(payload["easy_mode"])

    def test_whoami_effective_easy_mode_is_false_for_staff(self):
        self.client.force_login(self.staff)
        payload = self.client.get("/api/whoami/").json()
        # Staff default to Pro when they haven't made an explicit choice
        # (easy_mode is None) — this is the role default, not a hard mask:
        # staff can still opt into simple mode explicitly (see below).
        self.assertFalse(payload["easy_mode"])

    def test_whoami_non_staff_defaults_simple(self):
        u = User.objects.create_user(username="novize3")  # easy_mode default None
        self.client.force_login(u)
        self.assertTrue(self.client.get("/api/whoami/").json()["easy_mode"])

    def test_whoami_admin_defaults_pro_but_can_enable_simple(self):
        admin = User.objects.create_user(username="chef2", is_staff=True)  # easy_mode default None
        self.client.force_login(admin)
        self.assertFalse(self.client.get("/api/whoami/").json()["easy_mode"])  # default pro
        r = self.client.post(
            "/api/whoami/mode/",
            data='{"easy_mode": true}',
            content_type="application/json",
        )
        self.assertTrue(r.json()["easy_mode"])  # admin may enable simple
        admin.refresh_from_db()
        self.assertTrue(admin.easy_mode)  # stored explicitly
        self.assertTrue(self.client.get("/api/whoami/").json()["easy_mode"])

    def test_set_mode_toggles_easy_mode(self):
        self.client.force_login(self.user)
        resp = self.client.post(
            "/api/whoami/mode/",
            data={"easy_mode": False},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["easy_mode"])
        self.user.refresh_from_db()
        self.assertFalse(self.user.easy_mode)

    def test_set_mode_staff_can_enable_simple_mode(self):
        # Reversed from the old behavior (formerly
        # test_set_mode_effective_value_stays_false_for_staff, which
        # asserted the effective value stayed False for staff regardless of
        # the posted value — the old "admins can't enable simple" rule).
        # The whole point of this change is that admins MAY opt into simple
        # mode explicitly.
        self.client.force_login(self.staff)
        resp = self.client.post(
            "/api/whoami/mode/",
            data={"easy_mode": True},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["easy_mode"])
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.easy_mode)
        payload = self.client.get("/api/whoami/").json()
        self.assertTrue(payload["easy_mode"])

    def test_set_mode_requires_authentication(self):
        resp = self.client.post(
            "/api/whoami/mode/",
            data={"easy_mode": False},
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)


class EasyModeMigrationTests(TestCase):
    """Covers accounts.migrations.0003_easy_mode_nullable's data migration,
    which resets the old, for-them-unswitchable easy_mode=True default back
    to None for staff (so the role default applies again), while leaving
    non-staff choices and explicit staff opt-outs untouched."""

    def _run(self):
        mod = importlib.import_module("accounts.migrations.0003_easy_mode_nullable")
        mod.clear_stale_admin_default(django_apps, None)

    def test_stale_admin_default_reset_to_none(self):
        admin = User.objects.create_user(username="stale_admin", is_staff=True)
        # force the pre-migration stale default explicitly
        User.objects.filter(pk=admin.pk).update(easy_mode=True)
        self._run()
        admin.refresh_from_db()
        self.assertIsNone(admin.easy_mode)  # reset to role default (pro)

    def test_non_staff_choice_untouched(self):
        u = User.objects.create_user(username="ns_true")
        User.objects.filter(pk=u.pk).update(easy_mode=True)
        self._run()
        u.refresh_from_db()
        self.assertTrue(u.easy_mode)  # non-staff simple choice preserved

    def test_staff_explicit_false_untouched(self):
        a = User.objects.create_user(username="admin_pro", is_staff=True)
        User.objects.filter(pk=a.pk).update(easy_mode=False)
        self._run()
        a.refresh_from_db()
        self.assertFalse(a.easy_mode)  # staff explicit pro preserved
