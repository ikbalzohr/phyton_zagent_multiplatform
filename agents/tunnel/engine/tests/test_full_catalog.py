"""Offline regression for opt-in dynamic exposure of discovered MCP tools.

No network, owner grants, production files, or live service configuration.
"""
import time
import unittest
from types import SimpleNamespace

from router.access import AuthContext, AuthorizationError
from router.full_catalog import inferred_policy
from router.profile_admin import PROFILE_ADMIN_SCOPES


class FullCatalogUnitTests(unittest.TestCase):
    def setUp(self):
        self.services = {
            "zagent_files": {"namespace": "files", "enabled": True},
            "zagent_web": {"namespace": "web", "enabled": True},
            "zagent_arcmap": {"namespace": "arcmap", "enabled": True},
            "zagent_qgis": {"namespace": "qgis", "enabled": True, "internal_auth": False},
        }
        self.registry = SimpleNamespace(
            states={key: SimpleNamespace(service=dict(value)) for key, value in self.services.items()},
            tool_index={},
        )

    def register(self, name, service_id, upstream=None):
        self.registry.tool_index[name] = (service_id, upstream or name)

    def test_known_discovered_files_use_canonical_scope(self):
        expected = {"files_list": "files:read", "files_write": "files:write",
                    "files_powershell_run": "files:execute",
                    "files_profile_admin_list": "files:read",
                    "files_profile_admin_create": "files:write"}
        for name, scope in expected.items():
            with self.subTest(name=name):
                self.register(name, "zagent_files")
                self.assertEqual(inferred_policy(name, self.registry), {"scope":scope, "enabled":True})

    def test_all_current_supported_agent_namespaces(self):
        for name, service, scope in (
            ("web_snapshot", "zagent_web", "web:control"),
            ("arcmap_status", "zagent_arcmap", "arcmap:execute"),
            ("qgis_get_project", "zagent_qgis", "files:execute"),
        ):
            with self.subTest(name=name):
                self.register(name, service)
                self.assertEqual(inferred_policy(name, self.registry)["scope"], scope)

    def test_never_invent_a_tool_or_expose_internal_only_files(self):
        self.assertIsNone(inferred_policy("files_delete", self.registry))
        self.register("files_update_apply", "zagent_files")
        self.assertIsNone(inferred_policy("files_update_apply", self.registry))
        self.register("files_profile_catalog_snapshot", "zagent_files")
        self.assertIsNone(inferred_policy("files_profile_catalog_snapshot", self.registry))
        self.register("files_fake_future_api", "zagent_files")
        self.assertIsNone(inferred_policy("files_fake_future_api", self.registry))

    def test_wrong_service_namespace_and_disabled_peer_are_denied(self):
        self.register("files_read", "zagent_web")
        self.assertIsNone(inferred_policy("files_read", self.registry))
        self.register("web_snapshot", "zagent_web")
        self.registry.states["zagent_web"].service["enabled"] = False
        self.assertIsNone(inferred_policy("web_snapshot", self.registry))

    def test_qgis_must_have_exact_registered_adapter(self):
        self.register("qgis_get_project", "zagent_qgis")
        self.registry.states["zagent_qgis"].service["internal_auth"] = True
        self.assertIsNone(inferred_policy("qgis_get_project", self.registry))

    def test_agent_name_must_match_discovered_upstream(self):
        self.register("files_read", "zagent_files", upstream="files_write")
        self.assertIsNone(inferred_policy("files_read", self.registry))

    def test_explicit_known_management_controls(self):
        self.assertEqual(inferred_policy("zagent_task_submit", self.registry)["scope"], "files:write")
        self.assertEqual(inferred_policy("zagent_artifact_read", self.registry)["scope"], "files:read")
        self.assertEqual(inferred_policy("zagent_workflow_cancel", self.registry)["scope"], "arcmap:execute")
        self.assertEqual(inferred_policy("zagent_workflow_status", self.registry)["scope"], "arcmap:inspect")
        self.assertIsNone(inferred_policy("zagent_unknown_control", self.registry))

    def test_wildcard_is_explicit_and_scope_is_still_required(self):
        auth = AuthContext("owner", "ws",
            frozenset({"files:read", "files:write"}),
            frozenset({"*"}), "rev", time.time()+120)
        auth.require("files:write", "files_write")
        with self.assertRaises(AuthorizationError):
            auth.require("files:execute", "files_exec_command")
        auth_without_wildcard = AuthContext("owner", "ws",
            frozenset({"files:read", "files:write"}),
            frozenset({"files_stat"}), "rev", time.time()+120)
        with self.assertRaises(AuthorizationError):
            auth_without_wildcard.require("files:write", "files_write")

    def test_all_profile_admin_requires_owner_capability_separately(self):
        self.assertEqual(len(PROFILE_ADMIN_SCOPES), 6)
        self.assertEqual(inferred_policy("files_profile_admin_list", self.registry), None)


if __name__ == "__main__":
    unittest.main()