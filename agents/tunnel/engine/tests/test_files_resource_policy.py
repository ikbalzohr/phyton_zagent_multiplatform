"""Server-owned Files resource contract. Authored for Windows; NOT_RUN on VPS."""
import time
import unittest
from unittest.mock import patch

from router.access import AuthContext, AuthorizationError, ResourceAuthorizer
from router.config import validate_service
from router.execution_context import new_context, policy_resources, reject_authority, scheduler_meta, validate_context
from router.identity import Placement


def files_policy():
    return ResourceAuthorizer({
        "workspace_id": "ws", "policy_revision": "1",
        "grants": {"p": {"scopes": ["files:read"], "tools": ["files_stat"],
            "files_resource": {"resource_id": "workspace:ws:repo", "kind": "files",
                "profile_id": "approved-repo", "device_id": "device",
                "installation_id": "install", "revoked": False}}}})


class FilesResourcePolicyTests(unittest.TestCase):
    def setUp(self):
        self.auth = AuthContext("p", "ws", frozenset({"files:read"}),
                                frozenset({"files_stat"}), "1", time.time()+60)
        self.placement = Placement("device", "install")
        self.policy = files_policy()

    def context(self, policy=None):
        return new_context(self.auth, self.placement, "files:read", "files_stat",
                           resource_authorizer=policy or self.policy)

    def test_approved_profile_is_produced_and_preserved_by_scheduler(self):
        context = self.context()
        self.assertEqual(context["effective_resources"], [{"resource_id": "workspace:ws:repo",
                         "kind": "files", "profile_id": "approved-repo"}])
        self.assertEqual(context["scopes"], ["files:read"])
        meta = scheduler_meta(context, self.auth.owner)
        self.assertEqual(meta["execution_context"]["effective_resources"], context["effective_resources"])
        # Keep the conservative installation-wide lock: profile mapping is not a new lock domain.
        self.assertEqual(meta["resource_key"], "installation:install")
        validate_context(context, self.placement)

    def test_no_server_policy_fails_closed(self):
        with self.assertRaises(AuthorizationError):
            new_context(self.auth, self.placement, "files:read", "files_stat")

    def test_absent_revoked_wrong_kind_profile_or_placement_fails_closed(self):
        for changes in ({"revoked": True}, {"kind": "browser"}, {"profile_id": ""},
                        {"profile_id": None}, {"profile_id": " "},
                        {"device_id": "other"}, {"installation_id": "other"},
                        {"resource_id": ""}):
            policy = files_policy()
            policy.config["grants"]["p"]["files_resource"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(AuthorizationError):
                self.context(policy)
        for field in ("resource_id", "kind", "profile_id", "device_id", "installation_id"):
            policy = files_policy()
            del policy.config["grants"]["p"]["files_resource"][field]
            with self.subTest(field=field), self.assertRaises(AuthorizationError):
                self.context(policy)
        for mutate in (
            lambda c: c["grants"]["p"].pop("files_resource"),
            lambda c: c["grants"]["p"].update(revoked=True),
            lambda c: c["grants"].clear(),
            lambda c: c.update(workspace_id="other"),
            lambda c: c.update(policy_revision="2"),
            lambda c: c["grants"]["p"].update(expires_at=0),
        ):
            policy = files_policy(); mutate(policy.config)
            with self.assertRaises(AuthorizationError):
                self.context(policy)

    def test_mapping_change_is_detectable_without_minting_new_context(self):
        context = self.context()
        self.policy.config["grants"]["p"]["files_resource"]["profile_id"] = "other-approved"
        self.assertNotEqual(context["effective_resources"],
            policy_resources(self.auth, self.placement, "files:read", self.policy))

    def test_profile_and_resource_metadata_are_not_client_authority(self):
        for field in ("effective_resources", "files_resource", "metadata", "_meta"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                reject_authority({field: "other"})

    def test_context_rejects_files_resource_without_profile(self):
        context = self.context()
        del context["effective_resources"][0]["profile_id"]
        with self.assertRaises(AuthorizationError):
            validate_context(context, self.placement)

    def test_producer_context_crosses_actual_files_channel_consumer(self):
        import importlib.util
        from pathlib import Path
        from types import SimpleNamespace
        files_source = Path(__file__).resolve().parents[3]/"files/engine/app/core/execution_context.py"
        spec = importlib.util.spec_from_file_location("files_context_contract", files_source)
        consumer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(consumer)
        context = self.context()
        request = SimpleNamespace(request_context=SimpleNamespace(
            request=SimpleNamespace(headers={"x-zagent-internal-token": "k"*32}),
            meta={"zagent.execution_context": context}))
        with patch.dict("os.environ", {"ZAGENT_INTERNAL_TOKEN": "k"*32, "ZAGENT_DEVICE_ID": "device"}):
            verified = consumer.verify(consumer.request_meta(request), "files_stat", {})
            self.assertEqual(verified["effective_resources"][0]["profile_id"], "approved-repo")
            self.assertEqual(verified["session_id"], consumer.owner_key(context))
            self.assertNotEqual(verified["session_id"], self.auth.owner)
            with self.assertRaises(PermissionError):
                consumer.verify(request.request_context.meta, "files_stat", {})
            request.request_context.request.headers["x-zagent-internal-token"] = "wrong"
            with self.assertRaises(PermissionError):
                consumer.request_meta(request)

    def test_queued_dispatch_revalidates_mapping(self):
        # Import only on the Windows test host: server import opens existing journals.
        from router import server
        import asyncio
        context = self.context()
        with patch.object(server, "placement", self.placement), \
             patch.object(server, "authorizer", return_value=self.policy), \
             patch.object(server, "_auth_client", object()), \
             patch.object(server, "_credentials", {context["request_id"]: ("Bearer fixture-not-a-token", context["deadline"])}), \
             patch.object(server, "_policy", return_value={"scope": "files:read"}), \
             patch.object(server, "_files_catalog", new=unittest.mock.AsyncMock(return_value=None)), \
             patch.object(self.policy, "authenticate", new=unittest.mock.AsyncMock(return_value=self.auth)):
            asyncio.run(server._revalidate(context))
            self.policy.config["grants"]["p"]["files_resource"]["profile_id"] = "changed"
            with self.assertRaises(AuthorizationError):
                asyncio.run(server._revalidate(context))
            self.policy.config["grants"]["p"]["files_resource"]["revoked"] = True
            with self.assertRaises(AuthorizationError):
                asyncio.run(server._revalidate(context))


class ExactLoopbackPolicyTests(unittest.TestCase):
    def service(self, url):
        return dict(id="files", name="Files", namespace="files", url=url)

    def test_core_router_bind_alias_is_exact_not_network_wide(self):
        from router import server
        with patch.object(server, "load_tunnel_config", return_value={"router": {"host": "127.0.0.3"}}), \
             patch.object(server.uvicorn, "run") as run:
            server.run()
            self.assertEqual(run.call_args.kwargs["host"], "127.0.0.3")
        for host in ("127.0.0.2", "127.0.0.4", "0.0.0.0", "10.0.0.1"):
            with self.subTest(host=host), patch.object(server, "load_tunnel_config", return_value={
                    "router": {"host": host}}), patch.object(server.uvicorn, "run") as run:
                with self.assertRaises(ValueError):
                    server.run()
                run.assert_not_called()

    def test_core_loopback_requires_explicit_allowlist(self):
        for enabled in (True, False):
            cfg = {"security": {"allow_local_upstreams_only": enabled,
                                "allowed_hosts": ["127.0.0.3"]}}
            with patch("router.config.load_tunnel_config", return_value=cfg):
                validate_service(self.service("http://127.0.0.3:18820/mcp"))
            cfg["security"]["allowed_hosts"] = ["127.0.0.1"]
            with patch("router.config.load_tunnel_config", return_value=cfg), self.assertRaises(ValueError):
                validate_service(self.service("http://127.0.0.3:18820/mcp"))

    def test_allowlist_never_allows_other_loopback_or_network_hosts(self):
        for host in ("127.0.0.2", "127.0.0.4", "127.1.2.3", "0.0.0.0", "10.0.0.1", "example.com"):
            with self.subTest(host=host), patch("router.config.load_tunnel_config", return_value={
                    "security": {"allow_local_upstreams_only": False, "allowed_hosts": [host]}}), self.assertRaises(ValueError):
                validate_service(self.service("http://"+host+":18820/mcp"))
        for url in ("http://user:pass@127.0.0.3:18820/mcp", "http://127.0.0.3:18820/mcp?q=1", "http://127.0.0.3:18820/mcp#x"):
            with self.subTest(url=url), patch("router.config.load_tunnel_config", return_value={
                    "security": {"allowed_hosts": ["127.0.0.3"]}}), self.assertRaises(ValueError):
                validate_service(self.service(url))
