# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""LTI 1.3 flow tests with a simulated platform.

The tests act as the LMS: they hold a platform RSA keypair (published to the
tool as an inline ``key_set``), run the OIDC initiation to obtain state and
nonce, then POST a properly signed ``id_token`` to the launch endpoint —
the same handshake Moodle or Stud.IP would perform.
"""
import json
import time
from typing import ClassVar
from urllib.parse import parse_qs, urlparse

import jwt
from basicbar_lti.models import LtiPlatform
from django.contrib.auth import get_user_model
from django.test import TestCase
from jwcrypto import jwk
from pylti1p3.exception import LtiException

from rooms.models import QuestionSet, Room

from .models import LtiContextLink

User = get_user_model()

CLAIM = "https://purl.imsglobal.org/spec/lti/claim/"
ISSUER = "https://lms.example.edu"
CLIENT_ID = "abstimmbar-client"
DEPLOYMENT = "deployment-1"
TOOL_LAUNCH = "http://testserver/lti/launch/"


class LtiTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.platform_jwk = jwk.JWK.generate(kty="RSA", size=2048, kid="platform-key")
        cls.platform_private_pem = cls.platform_jwk.export_to_pem(
            private_key=True, password=None
        )
        public_jwk = json.loads(cls.platform_jwk.export_public())
        public_jwk.update({"alg": "RS256", "use": "sig"})
        cls.platform = LtiPlatform.objects.create(
            name="Test-LMS",
            issuer=ISSUER,
            client_id=CLIENT_ID,
            auth_login_url=f"{ISSUER}/auth",
            auth_token_url=f"{ISSUER}/token",
            key_set={"keys": [public_jwk]},
            deployment_ids=[DEPLOYMENT],
        )

    # -- the platform side of the handshake --------------------------------

    def start_login(self, target=TOOL_LAUNCH):
        """OIDC initiation → returns (state, nonce, redirect_uri)."""
        response = self.client.post(
            "/lti/login/",
            {
                "iss": ISSUER,
                "client_id": CLIENT_ID,
                "login_hint": "user-1",
                "target_link_uri": target,
                "lti_message_hint": "hint",
            },
        )
        self.assertEqual(response.status_code, 302, response.content)
        query = parse_qs(urlparse(response["Location"]).query)
        self.assertEqual(query["client_id"][0], CLIENT_ID)
        self.assertEqual(query["redirect_uri"][0], target)
        return query["state"][0], query["nonce"][0], query["redirect_uri"][0]

    def make_id_token(self, nonce, message_type="LtiResourceLinkRequest",
                      roles=None, extra=None, sub="user-1"):
        now = int(time.time())
        payload = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": sub,
            "iat": now,
            "exp": now + 300,
            "nonce": nonce,
            "given_name": "Frank",
            "family_name": "Lehrender",
            "email": "frank@lms.example.edu",
            f"{CLAIM}message_type": message_type,
            f"{CLAIM}version": "1.3.0",
            f"{CLAIM}deployment_id": DEPLOYMENT,
            f"{CLAIM}target_link_uri": TOOL_LAUNCH,
            f"{CLAIM}roles": roles if roles is not None else [
                "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor"
            ],
            f"{CLAIM}context": {"id": "course-42", "title": "Bio 101 (LMS)"},
        }
        if message_type == "LtiResourceLinkRequest":
            payload[f"{CLAIM}resource_link"] = {"id": "link-1"}
        if extra:
            payload.update(extra)
        return jwt.encode(
            payload,
            self.platform_private_pem,
            algorithm="RS256",
            headers={"kid": "platform-key"},
        )

    def launch(self, **token_kwargs):
        state, nonce, redirect_uri = self.start_login()
        id_token = self.make_id_token(nonce, **token_kwargs)
        return self.client.post(redirect_uri, {"state": state, "id_token": id_token})


class InstructorLaunchTests(LtiTestCase):
    def test_launch_provisions_user_room_and_link(self):
        response = self.launch()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/rooms/", response["Location"])
        user = User.objects.get(subject=f"lti:{self.platform.pk}:user-1")
        self.assertEqual(user.first_name, "Frank")
        link = LtiContextLink.objects.get(platform=self.platform, context_id="course-42")
        self.assertEqual(link.room.title, "Bio 101 (LMS)")
        self.assertIn(user, link.room.owners.all())

    def test_second_launch_reuses_room_and_user(self):
        self.launch()
        self.launch()
        self.assertEqual(Room.objects.count(), 1)
        self.assertEqual(User.objects.count(), 1)

    def test_launch_with_custom_set_redirects_to_set(self):
        self.launch()  # creates room + link
        room = LtiContextLink.objects.get().room
        question_set = QuestionSet.objects.create(room=room, title="Termin 1")
        response = self.launch(
            extra={f"{CLAIM}custom": {"set": str(question_set.pk)}}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith(f"/sets/{question_set.pk}"))

    def test_tampered_token_is_rejected(self):
        state, nonce, redirect_uri = self.start_login()
        foreign_key = jwk.JWK.generate(kty="RSA", size=2048, kid="platform-key")
        evil = jwt.encode(
            {"iss": ISSUER, "aud": CLIENT_ID, "nonce": nonce,
             "iat": int(time.time()), "exp": int(time.time()) + 300,
             f"{CLAIM}message_type": "LtiResourceLinkRequest",
             f"{CLAIM}version": "1.3.0",
             f"{CLAIM}deployment_id": DEPLOYMENT},
            foreign_key.export_to_pem(private_key=True, password=None),
            algorithm="RS256",
            headers={"kid": "platform-key"},
        )
        with self.assertRaises(LtiException):
            self.client.post(redirect_uri, {"state": state, "id_token": evil})

    def test_unknown_deployment_is_rejected(self):
        with self.assertRaises(LtiException):
            self.launch(extra={f"{CLAIM}deployment_id": "other-deployment"})


class LearnerLaunchTests(LtiTestCase):
    LEARNER: ClassVar = ["http://purl.imsglobal.org/vocab/lis/v2/membership#Learner"]

    def test_learner_redirects_to_participant_page_without_account(self):
        self.launch()  # instructor creates the link first
        users_before = User.objects.count()
        response = self.launch(roles=self.LEARNER, sub="student-9")
        self.assertEqual(response.status_code, 302)
        room = LtiContextLink.objects.get().room
        self.assertEqual(response["Location"], f"/p/{room.code}/")
        # Anonymity by design: learners never get an account.
        self.assertEqual(User.objects.count(), users_before)

    def test_learner_before_instructor_gets_friendly_error(self):
        response = self.launch(roles=self.LEARNER, sub="student-9")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "noch nicht verknüpft", status_code=404)


class DeepLinkingTests(LtiTestCase):
    DL_SETTINGS: ClassVar = {
        "https://purl.imsglobal.org/spec/lti-dl/claim/deep_linking_settings": {
            "deep_link_return_url": f"{ISSUER}/deep-link-return",
            "accept_types": ["ltiResourceLink"],
            "accept_presentation_document_targets": ["iframe", "window"],
            "data": "opaque-platform-data",
        }
    }

    def deep_link_launch(self):
        return self.launch(message_type="LtiDeepLinkingRequest", extra=self.DL_SETTINGS)

    def test_deep_link_launch_renders_selection(self):
        response = self.deep_link_launch()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fragenset einbinden")
        self.assertContains(response, "launch_id")

    def test_deep_link_response_contains_signed_content_item(self):
        response = self.deep_link_launch()
        launch_id = response.context["launch_id"]
        room = LtiContextLink.objects.get().room
        question_set = QuestionSet.objects.create(room=room, title="Termin 1")
        post = self.client.post(
            "/lti/deep-link/",
            {"launch_id": launch_id, "question_set": question_set.pk},
        )
        self.assertEqual(post.status_code, 200)
        self.assertContains(post, f"{ISSUER}/deep-link-return")
        # The auto-submit form carries a JWT signed with the tool key.
        body = post.content.decode()
        token = body.split('name="JWT" value="')[1].split('"')[0]
        decoded = jwt.decode(token, options={"verify_signature": False})
        items = decoded["https://purl.imsglobal.org/spec/lti-dl/claim/content_items"]
        self.assertEqual(items[0]["custom"], {"set": str(question_set.pk)})
        self.assertEqual(items[0]["title"], "Termin 1")
        self.assertTrue(items[0]["icon"]["url"].endswith("/lti/icon.svg"))
        self.assertEqual(decoded["https://purl.imsglobal.org/spec/lti-dl/claim/data"],
                         "opaque-platform-data")

    def test_deep_link_can_create_new_set(self):
        response = self.deep_link_launch()
        launch_id = response.context["launch_id"]
        post = self.client.post(
            "/lti/deep-link/",
            {"launch_id": launch_id, "new_title": "Neues Quiz"},
        )
        self.assertEqual(post.status_code, 200)
        self.assertTrue(QuestionSet.objects.filter(title="Neues Quiz").exists())

    def test_learner_cannot_deep_link(self):
        self.launch()  # link exists
        response = self.launch(
            message_type="LtiDeepLinkingRequest",
            roles=LearnerLaunchTests.LEARNER,
            extra=self.DL_SETTINGS,
        )
        self.assertEqual(response.status_code, 403)


class LtiPlatformApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username="chef", is_staff=True)
        self.user = User.objects.create_user(username="teacher")
        self.payload = {
            "name": "Moodle Test",
            "issuer": "https://moodle.example.org",
            "client_id": "abc123",
            "auth_login_url": "https://moodle.example.org/mod/lti/auth.php",
            "auth_token_url": "https://moodle.example.org/mod/lti/token.php",
            "key_set_url": "https://moodle.example.org/mod/lti/certs.php",
            "deployment_ids": ["1", "2"],
            "link_by_email": True,
            "is_active": True,
        }

    def test_requires_admin(self):
        # anonymous
        self.assertEqual(self.client.get("/api/lti/platforms/").status_code, 403)
        # non-staff
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/api/lti/platforms/").status_code, 403)

    def test_admin_crud_and_no_key_material_in_payload(self):
        self.client.force_login(self.admin)
        resp = self.client.post("/api/lti/platforms/", self.payload,
                                content_type="application/json")
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body["deployment_ids"], ["1", "2"])
        self.assertNotIn("private_key", body)
        self.assertNotIn("key_set", body)
        pk = body["id"]
        # list (DRF pagination is global — bare list is wrapped in results)
        self.assertEqual(
            len(self.client.get("/api/lti/platforms/").json()["results"]), 1
        )
        # update
        r = self.client.patch(f"/api/lti/platforms/{pk}/", {"is_active": False},
                              content_type="application/json")
        self.assertFalse(r.json()["is_active"])
        # delete
        self.assertEqual(
            self.client.delete(f"/api/lti/platforms/{pk}/").status_code, 204)

    def test_duplicate_issuer_client_id_is_400_not_500(self):
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.post("/api/lti/platforms/", self.payload,
                             content_type="application/json").status_code, 201)
        dup = self.client.post("/api/lti/platforms/", self.payload,
                               content_type="application/json")
        self.assertEqual(dup.status_code, 400)

    def test_deployment_ids_strips_blanks(self):
        self.client.force_login(self.admin)
        p = {**self.payload, "deployment_ids": ["1", "", "  ", "2"]}
        resp = self.client.post("/api/lti/platforms/", p,
                                content_type="application/json")
        self.assertEqual(resp.json()["deployment_ids"], ["1", "2"])

    def test_tool_info_admin_only_and_urls(self):
        self.assertEqual(self.client.get("/api/lti/tool-info/").status_code, 403)
        self.client.force_login(self.admin)
        info = self.client.get("/api/lti/tool-info/").json()
        self.assertTrue(info["login_url"].endswith("/lti/login/"))
        self.assertTrue(info["launch_url"].endswith("/lti/launch/"))
        self.assertTrue(info["jwks_url"].endswith("/lti/jwks/"))

    def test_created_platform_appears_in_jwks(self):
        from basicbar_lti.tool_conf import build_tool_conf
        self.client.force_login(self.admin)
        self.client.post("/api/lti/platforms/", self.payload,
                         content_type="application/json")
        jwks = build_tool_conf().get_jwks()
        self.assertTrue(jwks.get("keys"))   # key now served for the registration


class LtiIconTests(TestCase):
    def test_icon_svg_public(self):
        resp = self.client.get("/lti/icon.svg")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/svg+xml")
        self.assertIn(b"<svg", resp.content)

    def test_tool_info_includes_icon_url(self):
        admin = get_user_model().objects.create_user(username="chef2", is_staff=True)
        self.client.force_login(admin)
        info = self.client.get("/api/lti/tool-info/").json()
        self.assertTrue(info["icon_url"].endswith("/lti/icon.svg"))


class LtiFrameAncestorsTests(TestCase):
    def setUp(self):
        from django.utils import translation

        from rooms.models import Room
        with translation.override("de"):
            self.room = Room.objects.create(title="R")

    def _participant_html(self):
        return self.client.get(f"/p/{self.room.code}/")

    def test_no_platform_only_self(self):
        resp = self._participant_html()
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("X-Frame-Options", resp)
        self.assertIn("frame-ancestors 'self'", resp["Content-Security-Policy"])
        # no external origin when no platform registered
        self.assertNotIn("http", resp["Content-Security-Policy"].split("frame-ancestors")[1])

    def test_active_platform_origin_allowed(self):
        from basicbar_lti.models import LtiPlatform
        LtiPlatform.objects.create(
            name="M", issuer="https://moodle.example.org/", client_id="c",
            auth_login_url="https://moodle.example.org/auth",
            auth_token_url="https://moodle.example.org/tok", is_active=True,
        )
        csp = self._participant_html()["Content-Security-Policy"]
        self.assertIn("frame-ancestors 'self' https://moodle.example.org", csp)
        # scheme+host only, no path/trailing slash
        self.assertNotIn("moodle.example.org/auth", csp)

    def test_inactive_platform_not_allowed(self):
        from basicbar_lti.models import LtiPlatform
        LtiPlatform.objects.create(
            name="M", issuer="https://inactive.example.org", client_id="c",
            auth_login_url="https://inactive.example.org/a",
            auth_token_url="https://inactive.example.org/t", is_active=False,
        )
        csp = self._participant_html()["Content-Security-Policy"]
        self.assertNotIn("inactive.example.org", csp)

    def test_json_response_not_touched(self):
        # an API/JSON response keeps whatever it had; middleware only acts on HTML
        resp = self.client.get("/api/whoami/")
        self.assertNotIn("frame-ancestors", resp.get("Content-Security-Policy", ""))

    def test_admin_path_keeps_deny(self):
        from basicbar_lti.middleware import LtiFrameAncestorsMiddleware
        from django.http import HttpResponse
        from django.test import RequestFactory

        request = RequestFactory().get("/admin/")

        def get_response(_request):
            resp = HttpResponse(content_type="text/html")
            resp["X-Frame-Options"] = "DENY"
            return resp

        response = LtiFrameAncestorsMiddleware(get_response)(request)
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertNotIn("Content-Security-Policy", response)

    def test_malicious_issuer_not_injected(self):
        from basicbar_lti.models import LtiPlatform

        LtiPlatform.objects.create(
            name="Evil", issuer="https://evil.example.org;style-src *", client_id="c1",
            auth_login_url="https://evil.example.org/auth",
            auth_token_url="https://evil.example.org/tok", is_active=True,
        )
        LtiPlatform.objects.create(
            name="Evil2", issuer="https://a.example.org b.example.org", client_id="c2",
            auth_login_url="https://a.example.org/auth",
            auth_token_url="https://a.example.org/tok", is_active=True,
        )
        LtiPlatform.objects.create(
            name="Good", issuer="https://good.example.org", client_id="c3",
            auth_login_url="https://good.example.org/auth",
            auth_token_url="https://good.example.org/tok", is_active=True,
        )
        csp = self._participant_html()["Content-Security-Policy"]
        self.assertNotIn("style-src", csp)
        self.assertNotIn(";", csp)
        self.assertNotIn("evil.example.org", csp)
        self.assertNotIn("a.example.org", csp)
        self.assertNotIn("b.example.org", csp)
        self.assertIn("frame-ancestors 'self' https://good.example.org", csp)
