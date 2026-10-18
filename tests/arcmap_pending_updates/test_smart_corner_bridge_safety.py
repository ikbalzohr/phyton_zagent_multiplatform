"""ArcMap Smart Corner bridge unit isolation. No ArcMap, SHP mutation or COM needed.

Tests are created for future execution; DO NOT RUN without user authorization.
"""
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch, MagicMock


_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_ENGINE = os.path.join(_ROOT, "agents", "arcmap", "engine")
_BRIDGE = os.path.join(_ENGINE, "arcmap_bridge")
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

from core.smart_corner_geometry import classify_vertices, canonical_hash


def _load_bridge():
    fake_arcpy = types.ModuleType("arcpy")
    fake_arcpy.TestSchemaLock = MagicMock(return_value=False)
    fake_arcpy.da = MagicMock()
    fake_arcpy.GetCount_management = MagicMock()
    fake_config = types.ModuleType("core.config")
    fake_config.DATA_ROOT = os.path.join(tempfile.gettempdir(), "zagent-unit-only")
    fake_safety = types.ModuleType("core.safety")
    fake_safety.require_live_write = lambda: None
    fake_safety.require_destructive = lambda: None
    fake_current_map = types.ModuleType("core.current_map")
    fake_current_map.get_mxd = MagicMock()
    fake_current_map.find_layer = MagicMock()
    fake_current_map.safe_layer_source = MagicMock()
    with patch.dict(sys.modules, {
        "arcpy": fake_arcpy, "core.config": fake_config,
        "core.safety": fake_safety, "core.current_map": fake_current_map
    }):
        spec = importlib.util.spec_from_file_location(
            "smart_corner_bridge_unit", os.path.join(
                _BRIDGE, "features", "smart_corner.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module, fake_arcpy


class SmartCornerBridgeSafety(unittest.TestCase):
    def setUp(self):
        self.feature, self.arcpy = _load_bridge()
        self.owner = {"session_id": "unit-chat", "device_id": "unit-device",
                      "operator_alias": "Ikbal"}
        self.owner_patch = patch.object(self.feature, "_identity", return_value=self.owner)
        self.owner_patch.start()
        self.addCleanup(self.owner_patch.stop)
        self.ctx = {
            "mxd_path": "D:/tests/example.mxd",
            "data_frame": "Layers",
            "source_path": "D:/tests/source.shp",
            "target_path": "D:/tests/points.shp",
            "source_fingerprint": "a" * 64,
            "target_fingerprint": "b" * 64,
            "target_count": 109,
        }
        self.geometry = {
            "feature_oid": 3, "metric_crs": "EPSG:32651",
            "source_sr_wkid": 32651, "coordinate_system": "WGS_1984_UTM_Zone_51N",
            "vertices": [(0, 0), (20, 0), (20, 10), (0, 10), (0, 0)]
        }
        self.context_patch = patch.object(self.feature, "_context", return_value=self.ctx)
        self.geometry_patch = patch.object(self.feature, "_geometry", return_value=self.geometry)
        self.context_patch.start()
        self.geometry_patch.start()
        self.addCleanup(self.context_patch.stop)
        self.addCleanup(self.geometry_patch.stop)
        self.preview = self.feature.smart_corner_preview({
            "source_layer": "PT WAHANA CIPTA LESTARI", "target_layer": "PT_WCL_PT",
        })

    def test_preview_does_not_mutate_shapefile_or_mxd(self):
        self.assertTrue(self.preview["ok"])
        self.assertTrue(self.preview["dry_run"])
        self.assertFalse(self.preview["saved"])
        self.assertEqual(4, self.preview["counts"]["CORNER"])
        self.assertEqual(4, self.preview["recommended_count"])
        self.arcpy.da.InsertCursor.assert_not_called()
        self.arcpy.da.UpdateCursor.assert_not_called()

    def test_preview_returns_target_count_and_fingerprint(self):
        self.assertEqual(109, self.preview["target_count"])
        self.assertEqual("b" * 64, self.preview["target_fingerprint"])

    def test_review_changes_revision_without_writing_data(self):
        old_rev = self.preview["review_revision"]
        first = self.preview["reviewed_points"][0]["vertex_index"]
        reviewed = self.feature.smart_corner_review({
            "preview_id": self.preview["preview_id"],
            "expected_revision": old_rev,
            "exclude_vertex_indices": [first],
        })
        self.assertEqual(3, reviewed["recommended_count"])
        self.assertNotEqual(old_rev, reviewed["review_revision"])
        self.arcpy.da.UpdateCursor.assert_not_called()

    def test_stale_review_revision_is_rejected(self):
        with self.assertRaises(self.feature.SmartCornerError):
            self.feature.smart_corner_review({
                "preview_id": self.preview["preview_id"],
                "expected_revision": "invalid",
            })

    def test_default_commit_is_nonmutating(self):
        result = self.feature.smart_corner_commit({
            "preview_id": self.preview["preview_id"], "dry_run": True
        })
        self.assertFalse(result["ok"])
        self.assertEqual("DRY_RUN_ONLY", result["code"])
        self.arcpy.da.Editor.assert_not_called()

    def test_explicit_commit_requires_prior_manual_review(self):
        with self.assertRaises(self.feature.SmartCornerError) as error:
            self.feature.smart_corner_commit({
                "preview_id": self.preview["preview_id"],
                "expected_revision": self.preview["review_revision"],
                "confirm_commit": True, "dry_run": False,
                "idempotency_key": "unique-request-001",
                "confirm_replace_nonempty": True,
                "expected_target_count": 109
            })
        self.assertEqual("REVIEW_REQUIRED", error.exception.code)
        self.arcpy.da.Editor.assert_not_called()

    def test_wrong_revision_blocks_commit(self):
        with self.assertRaises(self.feature.SmartCornerError) as error:
            self.feature.smart_corner_commit({
                "preview_id": self.preview["preview_id"],
                "expected_revision": "stale", "confirm_commit": True,
                "dry_run": False, "idempotency_key": "unique-request-002",
            })
        self.assertEqual("STALE_PREVIEW", error.exception.code)

    def test_nonempty_target_requires_explicit_confirmation_and_exact_count(self):
        reviewed = self.feature.smart_corner_review({
            "preview_id": self.preview["preview_id"],
            "expected_revision": self.preview["review_revision"],
        })
        args = {
            "preview_id": self.preview["preview_id"],
            "expected_revision": reviewed["review_revision"], "confirm_commit": True,
            "dry_run": False, "idempotency_key": "unique-request-003"
        }
        with patch.object(self.feature, "_reconcile_preview", return_value=self.ctx):
            with self.assertRaises(self.feature.SmartCornerError) as e:
                self.feature.smart_corner_commit(dict(args))
            self.assertEqual("NONEMPTY_TARGET_CONFIRMATION_REQUIRED", e.exception.code)
            with self.assertRaises(self.feature.SmartCornerError) as e:
                self.feature.smart_corner_commit(dict(
                    args, confirm_replace_nonempty=True, expected_target_count=100))
            self.assertEqual("TARGET_STALE", e.exception.code)
        self.arcpy.da.Editor.assert_not_called()

    def test_schema_lock_blocks_commit_before_journal(self):
        reviewed = self.feature.smart_corner_review({
            "preview_id": self.preview["preview_id"],
            "expected_revision": self.preview["review_revision"]
        })
        args = {
            "preview_id": self.preview["preview_id"],
            "expected_revision": reviewed["review_revision"],
            "idempotency_key": "unique-request-004",
            "dry_run": False, "confirm_commit": True,
            "confirm_replace_nonempty": True, "expected_target_count": 109,
        }
        with patch.object(self.feature, "_reconcile_preview", return_value=self.ctx):
            with self.assertRaises(self.feature.SmartCornerError) as e:
                self.feature.smart_corner_commit(args)
        self.assertEqual("TARGET_LOCKED", e.exception.code)
        self.arcpy.da.Editor.assert_not_called()

    def test_destructive_guard_blocks_even_confirmed_commit(self):
        with patch.object(self.feature, "require_destructive",
                          return_value={"ok": False, "blocked": True}):
            result = self.feature.smart_corner_commit({
                "dry_run": False, "confirm_commit": True,
                "preview_id": self.preview["preview_id"]})
        self.assertTrue(result["blocked"])
        self.arcpy.da.Editor.assert_not_called()

    def test_identity_requires_authoritative_correlation(self):
        feature, _ = _load_bridge()
        with self.assertRaises(feature.SmartCornerError) as error:
            feature._identity({})
        self.assertEqual("SESSION_IDENTITY_REQUIRED", error.exception.code)
        self.assertEqual(self.owner, feature._identity({
            "correlation": dict(self.owner)
        }))

    def test_cross_session_review_is_rejected(self):
        with patch.object(self.feature, "_identity", return_value={
            "session_id": "another-chat", "device_id": "unit-device",
            "operator_alias": "Ikbal",
        }):
            with self.assertRaises(self.feature.SmartCornerError) as error:
                self.feature.smart_corner_review({
                    "preview_id": self.preview["preview_id"],
                    "expected_revision": self.preview["review_revision"],
                })
        self.assertEqual("SESSION_IDENTITY_MISMATCH", error.exception.code)

    def test_session_preview_expiry_blocks_review(self):
        self.feature._PREVIEWS[self.preview["preview_id"]]["created_at"] = 0
        with self.assertRaises(self.feature.SmartCornerError) as error:
            self.feature.smart_corner_review({
                "preview_id": self.preview["preview_id"],
                "expected_revision": self.preview["review_revision"]})
        self.assertEqual("STALE_PREVIEW", error.exception.code)

    def test_persistent_journal_rejects_duplicate_immutable_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(self.feature, "_JOURNAL_ROOT", os.path.join(tmp, "journal")):
                commit_id = "a" * 32
                self.feature._journal_write(commit_id, "00_PREPARING", {"count": 1})
                record = self.feature._journal_stage(commit_id)
                self.assertEqual("00_PREPARING", record["stage"])
                with self.assertRaises(FileExistsError):
                    self.feature._journal_write(commit_id, "00_PREPARING", {"count": 2})


if __name__ == "__main__":
    unittest.main()
