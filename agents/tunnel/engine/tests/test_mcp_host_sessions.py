"""Sessionless owner/context regression; client brands are not authority. NOT_RUN."""
import time
import unittest
from router.access import AuthContext, owner_key
from router.identity import Placement
from router.execution_context import new_context, reject_authority, validate_context

class NeutralContextTests(unittest.TestCase):
    def auth(self):
        return AuthContext("p", "ws", frozenset({"files:read"}), frozenset({"files_stat"}), "1", time.time()+60)

    def test_reconnect_mints_request_but_preserves_owner(self):
        a = new_context(self.auth(), Placement("device", "install"), "files:read", "files_stat")
        b = new_context(self.auth(), Placement("device", "install"), "files:read", "files_stat")
        self.assertNotEqual(a["request_id"], b["request_id"])
        self.assertNotEqual(a["task_id"], b["task_id"])
        self.assertEqual(owner_key(a["principal_id"], a["workspace_id"]), self.auth().owner)
        self.assertEqual(a["effective_resources"], b["effective_resources"])

    def test_client_authority_fields_cannot_weaken_lock(self):
        for key in ("session_id", "operator_alias", "principal_id", "resource_key", "access_mode", "priority", "target_device_id", "metadata", "_meta"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                reject_authority({key:"untrusted"})

    def test_stale_or_wrong_device_context_rejected(self):
        context = new_context(self.auth(), Placement("device", "install"), "files:read", "files_stat")
        validate_context(context, Placement("device", "install"))
        for key, value in (("device_id","other"),("context_version",99),("deadline",0),("effective_resources",["bypass"])):
            broken = dict(context); broken[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_context(broken, Placement("device", "install"))
