"""Tunnel1 regression source. NOT_RUN: Windows validation deferred by user."""
import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from router.access import ResourceAuthorizer, AuthorizationError, principal_id, owner_key
from router.identity import Placement
from router.orchestration import TaskJournal, upstream_error_summary


class ResourceSecurityTests(unittest.IsolatedAsyncioTestCase):
    def config(self):
        return {"resource_uri": "https://resource.example/mcp", "issuer": "https://issuer.example",
                "authorization_servers": ["https://issuer.example"],
                "introspection_endpoint": "https://issuer.example/introspect",
                "introspection_client_id": "resource", "introspection_secret_env": "TEST_AS_SECRET",
                "workspace_id": "ws-demo", "policy_revision": "1", "grants": {
                    principal_id("https://issuer.example", "subject"): {
                        "scopes": ["files:read"], "tools": ["files_stat"]}}}

    async def authorize(self, claims, config=None):
        async def respond(request):
            self.assertEqual(request.url.host, "issuer.example")
            return httpx.Response(200, json=claims)
        with patch.dict(os.environ, {"TEST_AS_SECRET": "test-only-value"}):
            async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
                return await ResourceAuthorizer(config or self.config()).authenticate("Bearer opaque", client)

    def claims(self):
        return {"active": True, "iss": "https://issuer.example", "sub": "subject",
                "aud": "https://resource.example/mcp", "exp": time.time()+300,
                "scope": "files:read files:write"}

    async def test_credential_scopes_intersect_provisioned_grant(self):
        auth = await self.authorize(self.claims())
        self.assertEqual(auth.scopes, frozenset({"files:read"}))
        auth.require("files:read", "files_stat")
        with self.assertRaises(AuthorizationError):
            auth.require("files:write", "files_write")

    async def test_invalid_claims_fail_closed(self):
        for field, value in [("active", False), ("iss", "other"), ("aud", "other"),
                             ("exp", 0), ("sub", ""), ("nbf", time.time()+1000)]:
            claims = self.claims(); claims[field] = value
            with self.subTest(field=field), self.assertRaises(AuthorizationError):
                await self.authorize(claims)

    async def test_unprovisioned_and_revoked_principal_denied(self):
        cfg = self.config(); cfg["grants"] = {}
        with self.assertRaises(AuthorizationError):
            await self.authorize(self.claims(), cfg)

    async def test_missing_configuration_is_not_anonymous_access(self):
        async with httpx.AsyncClient() as client:
            with self.assertRaises(AuthorizationError) as error:
                await ResourceAuthorizer({}).authenticate("Bearer any", client)
            self.assertEqual(error.exception.code, "NOT_CONFIGURED")

    def test_owner_namespace_not_transport_session(self):
        self.assertNotEqual(owner_key("a", "ws"), owner_key("b", "ws"))
        self.assertNotEqual(owner_key("a", "ws"), owner_key("a", "ws2"))
        self.assertTrue(owner_key("a", "ws").startswith("owner_v1_"))

    def test_placement_does_not_accept_client_device(self):
        with self.assertRaises(AuthorizationError):
            Placement("", "install").validate()


class JournalSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def test_idempotency_conflict_checks_body(self):
        with tempfile.TemporaryDirectory() as root:
            journal = TaskJournal(Path(root)/"tasks.db")
            base = {"task_id":"t1", "session_id":"owner_v1_a", "request_id":"r1", "trace_id":"tr1",
                    "idempotency_key":"scoped-key", "service_id":"files", "tool_name":"stat",
                    "arguments_json":"{}", "resource_key":"installation", "access_mode":"write",
                    "priority":2, "state":"queued", "created_at":1, "updated_at":1}
            await journal.create(base)
            same = dict(base, task_id="t2")
            self.assertEqual(await journal.create(same), ("t1", False))
            with self.assertRaisesRegex(ValueError, "IDEMPOTENCY_CONFLICT"):
                await journal.create(dict(same, arguments_json='{"path":"different"}'))
            journal.conn.close()

    def test_domain_failure_is_not_success(self):
        self.assertTrue(upstream_error_summary({"ok":False,"errors":[{"code":"BLOCKED"}]}))
        self.assertTrue(upstream_error_summary({"content":[{"type":"text","text":'{"ok":false}'}]}))
        self.assertFalse(upstream_error_summary({"ok":True}))
