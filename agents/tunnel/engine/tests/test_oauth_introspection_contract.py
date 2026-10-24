"""RFC7662/Keycloak contract test SOURCE. NOT_RUN: owner Windows gate."""
import os
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs

import httpx
from router.access import AuthorizationError, ResourceAuthorizer, principal_id


class IntrospectionContractTests(unittest.IsolatedAsyncioTestCase):
    def config(self):
        issuer = "https://as.example/realms/zagent"
        return {"issuer": issuer, "resource_uri": "https://resource.example/mcp",
                "authorization_servers": [issuer], "workspace_id": "ws", "policy_revision": "1",
                "introspection_endpoint": issuer + "/protocol/openid-connect/token/introspect",
                "introspection_client_id": "zagent-rs", "introspection_secret_env": "TEST_AS_SECRET",
                "grants": {principal_id(issuer, "subject"): {
                    "scopes": ["files:read"], "tools": ["files_stat"], "revoked": False}}}

    def claims(self):
        return {"active": True, "iss": self.config()["issuer"], "sub": "subject",
                "aud": ["account", "https://resource.example/mcp"],
                "exp": time.time() + 300, "scope": "files:read files:write"}

    async def authenticate(self, claims, status=200, config=None):
        async def handler(request):
            self.assertEqual(request.method, "POST")
            self.assertEqual(str(request.url), self.config()["introspection_endpoint"])
            self.assertEqual(request.headers["accept"], "application/json")
            self.assertTrue(request.headers["authorization"].startswith("Basic "))
            self.assertEqual(parse_qs(request.content.decode()),
                             {"token": ["contract-test"], "token_type_hint": ["access_token"]})
            return httpx.Response(status, json=claims)
        with patch.dict(os.environ, {"TEST_AS_SECRET": "unit-test-not-a-real-secret"}):
            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                return await ResourceAuthorizer(config or self.config()).authenticate(
                    "Bearer contract-test", client)

    async def test_keycloak_audience_list_and_string_intersect_local_grant(self):
        for aud in (["account", "https://resource.example/mcp"], "https://resource.example/mcp"):
            claims = self.claims(); claims["aud"] = aud
            auth = await self.authenticate(claims)
            self.assertEqual(auth.scopes, frozenset({"files:read"}))
            auth.require("files:read", "files_stat")
            with self.assertRaises(AuthorizationError):
                auth.require("files:write", "files_stat")

    async def test_malformed_or_missing_standard_claims_denied(self):
        for key, value in [("active", "true"), ("active", 1), ("nbf", True),
                           ("exp", True), ("exp", float("inf")), ("exp", 0),
                           ("aud", ["https://resource.example/mcp", {}]),
                           ("scope", ["files:read"]), ("sub", ""),
                           ("iss", "https://as.example/realms/other")]:
            claims = self.claims(); claims[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(AuthorizationError) as error:
                await self.authenticate(claims)
            self.assertEqual(error.exception.status, 401)
        for key in ("active", "iss", "sub", "aud", "exp"):
            claims = self.claims(); del claims[key]
            with self.subTest(missing=key), self.assertRaises(AuthorizationError):
                await self.authenticate(claims)

    async def test_inactive_or_unavailable_as_never_authorizes(self):
        for status, claims, expected in [(200, {"active": False}, 401),
                                         (401, {}, 503), (302, {}, 503), (500, {}, 503)]:
            with self.subTest(status=status), self.assertRaises(AuthorizationError) as error:
                await self.authenticate(claims, status)
            self.assertEqual(error.exception.status, expected)

    async def test_subject_not_username_or_client_id_controls_grant(self):
        claims = self.claims(); claims.update(sub="unapproved", username="subject", client_id="subject")
        with self.assertRaises(AuthorizationError) as error:
            await self.authenticate(claims)
        self.assertEqual(error.exception.code, "grant_revoked")

    async def test_revoked_expired_and_missing_local_grants_deny(self):
        for mutation in ({"revoked": True}, {"expires_at": 0}, None):
            config = self.config()
            if mutation is None:
                config["grants"] = {}
            else:
                next(iter(config["grants"].values())).update(mutation)
            with self.subTest(mutation=mutation), self.assertRaises(AuthorizationError):
                await self.authenticate(self.claims(), config=config)
