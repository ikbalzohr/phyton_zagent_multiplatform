"""Placement preserves no-silent-relay invariant. NOT_RUN."""
import unittest
from router.identity import Placement
from router.access import AuthorizationError

class PlacementIsolationTests(unittest.TestCase):
    def test_other_physical_device_is_never_selected(self):
        placement = Placement("device-a", "installation-a")
        placement.validate("device-a")
        with self.assertRaises(AuthorizationError) as error:
            placement.validate("device-b")
        self.assertEqual(error.exception.code, "IDENTITY_MISMATCH")

    def test_missing_installation_is_not_a_compatibility_mode(self):
        with self.assertRaises(AuthorizationError):
            Placement("device-a", "").validate()
