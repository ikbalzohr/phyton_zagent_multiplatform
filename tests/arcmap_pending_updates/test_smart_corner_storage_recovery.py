"""Disposable-fixture tests for Smart Corner SHP backup/journal/rollback.

These tests are CREATED ONLY; never run against real PT_WCL_PT or ArcMap.
"""
import os
import tempfile
import unittest
from unittest.mock import patch

from test_smart_corner_bridge_safety import _load_bridge


class SmartCornerStorageRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.feature, self.arcpy = _load_bridge()
        self.owner = {"session_id": "unit-chat", "device_id": "unit-device",
                      "operator_alias": "Ikbal"}
        self.owner_patch = patch.object(self.feature, "_identity", return_value=self.owner)
        self.owner_patch.start()
        self.addCleanup(self.owner_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = self.temp.name
        self.shape = os.path.join(root, "fixtures", "synthetic_points.shp")
        os.makedirs(os.path.dirname(self.shape))
        self.base = os.path.splitext(self.shape)[0]
        self.initial = {
            ".shp": b"geometric-vertices-fixture",
            ".shx": b"shapefile-index-fixture",
            ".dbf": b"Id,Label\n1,Pt1\n",
            ".prj": b"WGS84 UTM zone 51N",
            ".cpg": b"UTF-8",
            ".shp.xml": b"<metadata><owner>unit-test</owner></metadata>",
        }
        for ext, content in self.initial.items():
            with open(self.base + ext, "wb") as handle:
                handle.write(content)
        self.p1 = patch.object(self.feature, "_JOURNAL_ROOT", os.path.join(root, "journal"))
        self.p2 = patch.object(self.feature, "_BACKUP_ROOT", os.path.join(root, "backups"))
        self.p1.start()
        self.p2.start()
        self.addCleanup(self.p1.stop)
        self.addCleanup(self.p2.stop)
        self.arcpy.TestSchemaLock.return_value = True

    def test_signature_changes_after_fixture_shapefile_mutation(self):
        before = self.feature._signature(self.shape)
        with open(self.base + ".dbf", "wb") as stream:
            stream.write(b"Id,Label\n1,Pt1\n2,Pt2\n")
        self.assertNotEqual(before, self.feature._signature(self.shape))

    def test_backup_copies_all_core_and_auxiliary_sidecars(self):
        initial_hash = self.feature._signature(self.shape)
        backup = self.feature._shp_backup(self.shape, "1" * 32)
        self.assertEqual(6, len(backup["files"]))
        self.assertIn("synthetic_points.shp.xml", backup["files"])
        for name, digest in backup["files"].items():
            self.assertEqual(digest, self.feature._digest_file(
                os.path.join(backup["root"], name)))
        self.assertEqual(initial_hash, self.feature._signature(self.shape))

    def test_stale_target_blocks_rollback_before_copy(self):
        commit_id = "2" * 32
        original = self.feature._signature(self.shape)
        backup = self.feature._shp_backup(self.shape, commit_id)
        with open(self.base + ".dbf", "wb") as stream:
            stream.write(b"Id,Label\n1,Pt1\n2,Pt2\n")
        current = self.feature._signature(self.shape)
        self.feature._journal_write(commit_id, "40_COMMITTED", {
            "target_path": self.shape, "target_fingerprint_before": original,
            "target_fingerprint_after": "f" * 64, "backup": backup,
            "identity": self.owner,
        })
        with self.assertRaises(self.feature.SmartCornerError) as error:
            self.feature.smart_corner_rollback(
                {"commit_id": commit_id, "confirm_rollback": True})
        self.assertEqual("TARGET_STALE", error.exception.code)
        self.assertEqual(current, self.feature._signature(self.shape))

    def test_explicit_rollback_restores_byte_exact_fixture_sidecars(self):
        commit_id = "3" * 32
        original = self.feature._signature(self.shape)
        backup = self.feature._shp_backup(self.shape, commit_id)
        with open(self.base + ".shp", "wb") as stream:
            stream.write(b"revised synthetic vertices")
        with open(self.base + ".dbf", "wb") as stream:
            stream.write(b"Id,Label\n10,Pt10\n")
        after = self.feature._signature(self.shape)
        self.feature._journal_write(commit_id, "40_COMMITTED", {
            "target_path": self.shape, "target_fingerprint_before": original,
            "target_fingerprint_after": after, "backup": backup,
            "identity": self.owner,
        })
        result = self.feature.smart_corner_rollback(
            {"commit_id": commit_id, "confirm_rollback": True})
        self.assertTrue(result["ok"])
        self.assertEqual(original, self.feature._signature(self.shape))
        for ext, content in self.initial.items():
            with open(self.base + ext, "rb") as stream:
                self.assertEqual(content, stream.read())
        self.assertEqual("60_ROLLED_BACK",
                         self.feature._journal_stage(commit_id)["stage"])

    def test_rollback_is_not_automatically_repeated(self):
        commit_id = "4" * 32
        original = self.feature._signature(self.shape)
        backup = self.feature._shp_backup(self.shape, commit_id)
        self.feature._journal_write(commit_id, "60_ROLLED_BACK", {
            "target_path": self.shape, "target_fingerprint_before": original,
            "target_fingerprint_after": original, "backup": backup,
            "identity": self.owner,
        })
        with self.assertRaises(self.feature.SmartCornerError):
            self.feature.smart_corner_rollback(
                {"commit_id": commit_id, "confirm_rollback": True})

    def test_cross_session_commit_status_is_denied(self):
        commit_id = "6" * 32
        self.feature._journal_write(commit_id, "40_COMMITTED", {
            "identity": self.owner, "target_path": self.shape,
        })
        with patch.object(self.feature, "_identity", return_value={
            "session_id": "other-chat", "device_id": "unit-device",
            "operator_alias": "Ikbal",
        }):
            with self.assertRaises(self.feature.SmartCornerError) as error:
                self.feature.smart_corner_status({"commit_id": commit_id})
        self.assertEqual("SESSION_IDENTITY_MISMATCH", error.exception.code)

    def test_locked_shapefile_cannot_be_restored(self):
        commit_id = "5" * 32
        original = self.feature._signature(self.shape)
        backup = self.feature._shp_backup(self.shape, commit_id)
        self.feature._journal_write(commit_id, "40_COMMITTED", {
            "target_path": self.shape, "target_fingerprint_before": original,
            "target_fingerprint_after": original, "backup": backup,
            "identity": self.owner,
        })
        self.arcpy.TestSchemaLock.return_value = False
        with self.assertRaises(self.feature.SmartCornerError) as error:
            self.feature.smart_corner_rollback(
                {"commit_id": commit_id, "confirm_rollback": True})
        self.assertEqual("TARGET_LOCKED", error.exception.code)


if __name__ == "__main__":
    unittest.main()
