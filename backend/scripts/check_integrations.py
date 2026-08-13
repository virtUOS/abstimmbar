# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Universität Osnabrück (virtUOS)

"""Show which optional integrations the current environment configures.

Answers "did my .env actually reach Django?" without starting the server:

    python scripts/check_integrations.py            # configuration only
    python scripts/check_integrations.py --probe    # plus live calls

Reports OIDC (incl. the endpoints derived from OIDC_OP_ISSUER by discovery),
LiteLLM and LibreTranslate. Secrets are only ever shown as set/unset — the
output is safe to paste into an issue. ``--probe`` additionally fetches the
discovery document and JWKS, translates one word and sends a minimal chat
completion, so it costs a (tiny) request against each configured provider.
"""
import argparse
import json
import os
import sys
from urllib import error, request

import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from basicbar_integrations import ai, translation_service
from django.conf import settings

OK = "  ok "
FAIL = "  !! "
INFO = "     "


def mask(value: str) -> str:
    """Never print a credential — only whether it is there."""
    return f"set ({len(value)} chars)" if value else "unset"


def fetch(url: str) -> tuple[bool, str]:
    """GET a URL, returning (success, short description of the result)."""
    try:
        with request.urlopen(request.Request(url), timeout=15) as response:
            body = response.read(400_000)
        return True, f"HTTP {response.status}, {len(body)} bytes"
    except (error.URLError, TimeoutError, ValueError) as exc:
        return False, str(exc)


def check_oidc(probe: bool) -> None:
    print("OIDC / Keycloak")
    issuer = settings.OIDC_OP_ISSUER
    endpoints = {
        name: getattr(settings, f"OIDC_OP_{name.upper()}_ENDPOINT")
        for name in ("authorization", "token", "user", "jwks", "logout")
    }
    if not any(endpoints.values()):
        print(f"{FAIL}no endpoints configured — login is unavailable")
        return
    print(f"{INFO}issuer          {issuer or '(none — endpoints set explicitly)'}")
    if issuer:
        print(f"{INFO}                endpoints below came from its discovery document")
    print(f"{INFO}client id       {settings.OIDC_RP_CLIENT_ID or '(unset!)'}")
    print(f"{INFO}client secret   {mask(settings.OIDC_RP_CLIENT_SECRET)}")
    for name, url in endpoints.items():
        print(f"{INFO}{name:<15} {url or '(unset)'}")
    print(f"{INFO}admin group     {settings.OIDC_ADMIN_GROUP or '(none — no auto-admin)'}")
    print(f"{INFO}redirect uri    register <backend base url>/oidc/callback/ in the client")
    if not probe:
        return
    if issuer:
        ok, detail = fetch(issuer.rstrip("/") + "/.well-known/openid-configuration")
        print(f"{OK if ok else FAIL}discovery       {detail}")
    if endpoints["jwks"]:
        ok, detail = fetch(endpoints["jwks"])
        print(f"{OK if ok else FAIL}jwks            {detail}")


def check_ai(probe: bool) -> None:
    print("\nLiteLLM (AI features)")
    print(f"{INFO}provider        {settings.AI_PROVIDER}")
    print(f"{INFO}base url        {settings.AI_BASE_URL or '(unset)'}")
    print(f"{INFO}model           {settings.AI_MODEL or '(unset)'}")
    print(f"{INFO}api key         {mask(settings.AI_API_KEY)}")
    enabled = ai.is_enabled()
    print(f"{OK if enabled else FAIL}is_enabled()    {enabled}")
    if not enabled:
        print(f"{INFO}                all of provider/base url/key/model are required")
        return
    if not probe:
        return
    try:
        reply = ai.chat_json(
            'Reply with JSON only.', 'Return {"pong": true}.', max_tokens=64
        )
        print(f"{OK}chat call       {json.dumps(reply)[:120]}")
    except ai.AIError as exc:
        print(f"{FAIL}chat call       {exc}")


def check_translation(probe: bool) -> None:
    print("\nLibreTranslate (content translation)")
    print(f"{INFO}provider        {settings.CONTENT_TRANSLATION_PROVIDER}")
    print(f"{INFO}url             {settings.LIBRETRANSLATE_URL or '(unset)'}")
    print(f"{INFO}api key         {mask(settings.LIBRETRANSLATE_API_KEY)}")
    print(f"{INFO}content default {settings.MODELTRANSLATION_DEFAULT_LANGUAGE}")
    enabled = translation_service.is_enabled()
    print(f"{OK if enabled else FAIL}is_enabled()    {enabled}")
    if not enabled or not probe:
        return
    try:
        result = translation_service.translate("Guten Morgen", "de", "en")
        print(f"{OK}translate call  'Guten Morgen' → {result!r}")
    except translation_service.TranslationError as exc:
        print(f"{FAIL}translate call  {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--probe",
        action="store_true",
        help="also call each configured provider once (costs a request)",
    )
    args = parser.parse_args()
    check_oidc(args.probe)
    check_ai(args.probe)
    check_translation(args.probe)
    if not args.probe:
        print("\nRe-run with --probe to actually call the configured services.")


if __name__ == "__main__":
    main()
