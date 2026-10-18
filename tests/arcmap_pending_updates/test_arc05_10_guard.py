"""ARC-08 unit tests. Written for later execution; never run automatically."""
import importlib.util
import pathlib
import unittest

BRIDGE = (pathlib.Path(__file__).resolve().parents[2] /
          "agents" / "arcmap" / "engine" / "arcmap_bridge")
spec = importlib.util.spec_from_file_location(
    "arcmap_concurrent_edit_guard", BRIDGE / "core" / "concurrent_edit_guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def command(action, session="s1", device="d1", operator="Ikbal", **options):
    payload = {"action": action,
               "correlation": {"session_id": session, "device_id": device,
                               "operator_alias": operator}}
    payload.update(options)
    return payload


class ConcurrentEditGuardTests(unittest.TestCase):
    def setUp(self):
        guard._HUMAN = None

    def tearDown(self):
        guard._HUMAN = None

    def test_identity_required(self):
        response = guard.acquire(command("edit_guard_acquire", session=""))
        self.assertFalse(response["ok"])
        self.assertEqual(response["code"], "SESSION_IDENTITY_REQUIRED")

    def test_invalid_lease(self):
        self.assertFalse(guard.acquire(command("edit_guard_acquire", seconds=0))["ok"])
        self.assertFalse(guard.acquire(command("edit_guard_acquire", seconds=7201))["ok"])

    def test_human_blocks_mutations(self):
        response = guard.acquire(command("edit_guard_acquire"))
        self.assertTrue(response["ok"])
        self.assertEqual(
            guard.reject_mutation(command("set_layer_visibility"))["code"],
            "HUMAN_EDIT_IN_PROGRESS")
        self.assertIsNone(guard.reject_mutation(command("get_layer_info")))
        self.assertIsNone(guard.reject_mutation(command("edit_guard_status")))
        self.assertTrue(guard.status(command("edit_guard_status"))["human_edit_active"])

    def test_wrong_session_cannot_release(self):
        lease = guard.acquire(command("edit_guard_acquire"))
        response = guard.release(command("edit_guard_release", session="s2",
                                         token=lease["token"]))
        self.assertEqual(response["code"], "EDIT_GUARD_OWNER_MISMATCH")
        self.assertIsNotNone(guard.reject_mutation(command("set_layer_visibility")))

    def test_token_required_to_release(self):
        lease = guard.acquire(command("edit_guard_acquire"))
        self.assertFalse(guard.release(command("edit_guard_release", token="bad"))["ok"])
        self.assertTrue(guard.release(command("edit_guard_release",
                                               token=lease["token"]))["ok"])
        self.assertIsNone(guard.reject_mutation(command("set_layer_visibility")))

    def test_expiration_unblocks_mutation(self):
        guard.acquire(command("edit_guard_acquire", seconds=2))
        guard._HUMAN["expires_at"] = 0
        self.assertIsNone(guard.reject_mutation(command("set_native_scale_bar")))
        self.assertFalse(guard.status(command("edit_guard_status"))["human_edit_active"])


if __name__ == "__main__":
    unittest.main()
