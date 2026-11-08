"""The disk-only print workflow has its own opt-in; CURRENT writes remain locked."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ENGINE = Path(__file__).resolve().parents[2] / "agents" / "arcmap" / "engine"
sys.path.insert(0, str(ENGINE))
from mcp_server.config import AGENT
from mcp_server.safety import SafetyPolicy


class PrintReadyPolicyTests(unittest.TestCase):
    def test_explicit_opt_in_does_not_enable_current_save(self):
        with patch.dict(AGENT, {"allow_headless_print_ready": True,
                                "allow_save": False, "allow_export": True}):
            policy = SafetyPolicy()
            self.assertIsNone(policy.guard("headless_print_ready"))
            self.assertIsNone(policy.guard("export"))
            self.assertTrue(policy.guard("save")["blocked"])
            self.assertTrue(policy.guard("live_write")["blocked"])

    def test_disabled_by_default_and_explicit_false(self):
        with patch.dict(AGENT, {"allow_headless_print_ready": False}):
            self.assertTrue(SafetyPolicy().guard("headless_print_ready")["blocked"])

    def test_export_denial_still_blocks(self):
        with patch.dict(AGENT, {"allow_headless_print_ready": True, "allow_export": False}):
            self.assertIsNone(SafetyPolicy().guard("headless_print_ready"))
            self.assertTrue(SafetyPolicy().guard("export")["blocked"])


if __name__ == "__main__":
    unittest.main()
