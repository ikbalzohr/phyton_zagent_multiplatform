"""Principal grants replace per-chat approvals. NOT_RUN."""
import time
import unittest
from router.access import AuthContext, ResourceAuthorizer, AuthorizationError

class PrincipalGrantTests(unittest.TestCase):
    def auth(self):
        return AuthContext("p", "ws", frozenset({"files:read"}), frozenset({"files_stat"}), "1", time.time()+60)

    def test_tool_allowlist_enforced_even_with_scope(self):
        with self.assertRaises(AuthorizationError):
            self.auth().require("files:read", "files_read_secret")

    def test_expired_authority_cannot_read_results(self):
        auth = AuthContext("p", "ws", frozenset({"files:read"}), frozenset({"files_stat"}), "1", 0)
        with self.assertRaises(AuthorizationError):
            auth.require("files:read", "files_stat")

    def test_revocation_and_policy_revision_are_checked(self):
        for grant, revision in [({"revoked":True}, "1"), ({}, "2")]:
            authorizer = ResourceAuthorizer({"grants":{"p":grant}, "workspace_id":"ws", "policy_revision":revision})
            with self.assertRaises(AuthorizationError):
                authorizer.current_grant(self.auth())
