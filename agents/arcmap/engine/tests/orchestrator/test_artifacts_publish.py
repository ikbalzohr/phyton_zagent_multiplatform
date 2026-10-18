import os
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from orchestrator.artifacts import validate_pdf, validate_png, Publisher
from orchestrator.reporting import build_run_report, to_markdown

def write_pdf(path):
    Path(path).write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")

def write_png(path,w=100,h=50):
    data=b"\x89PNG\r\n\x1a\n"+struct.pack(">I",13)+b"IHDR"+struct.pack(">II",w,h)+b"\x08\x06\x00\x00\x00"
    Path(path).write_bytes(data)

class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.pdf=self.root/"map.pdf"; self.png=self.root/"map.png"; write_pdf(self.pdf); write_png(self.png)
    def tearDown(self): self.tmp.cleanup()

    def artifacts(self):
        return [
            {"kind":"PDF","path":str(self.pdf),"metadata":{"dpi":400}},
            {"kind":"PNG","path":str(self.png),"metadata":{"dpi":400}},
        ]

    def test_pdf_png_gate_accepts_signatures_and_400dpi_metadata(self):
        self.assertTrue(validate_pdf(self.pdf,{"dpi":400})["ok"])
        p=validate_png(self.png,{"dpi":400})
        self.assertTrue(p["ok"]); self.assertEqual((p["width"],p["height"]),(100,50))

    def test_below_policy_dpi_fails(self):
        self.assertFalse(validate_pdf(self.pdf,{"dpi":300})["ok"])
        self.assertFalse(validate_png(self.png,{"dpi":300})["ok"])

    def test_missing_one_required_artifact_prevents_publish(self):
        r=Publisher().publish("run1",[self.artifacts()[0]],self.root/"out")
        self.assertEqual(r["status"],"ARTIFACT_INVALID")

    def test_successful_publish_writes_completion_manifest_last(self):
        r=Publisher().publish("run1",self.artifacts(),self.root/"out")
        self.assertTrue(r["ok"]); self.assertTrue(r["completion_manifest"]["complete"])
        self.assertEqual(len(r["published"]),2)

    def test_collision_deny_does_not_overwrite(self):
        out=self.root/"out"; out.mkdir(); old=out/"map.pdf"; old.write_bytes(b"old")
        r=Publisher().publish("run1",self.artifacts(),out,"deny")
        self.assertEqual(r["status"],"PUBLISH_PARTIAL"); self.assertEqual(old.read_bytes(),b"old")

    def test_version_policy_preserves_existing(self):
        out=self.root/"out"; out.mkdir(); old=out/"map.pdf"; old.write_bytes(b"old")
        r=Publisher().publish("run1",self.artifacts(),out,"version")
        self.assertTrue(r["ok"]); self.assertEqual(old.read_bytes(),b"old")
        self.assertTrue(any("_v1" in x for x in r["published"]))

    def test_partial_copy_failure_is_not_success(self):
        calls=[]
        def copier(src,dst):
            calls.append((src,dst))
            if src.endswith(".png"): raise OSError("disk full")
            return shutil.copy2(src,dst)
        r=Publisher(copier=copier).publish("run1",self.artifacts(),self.root/"out")
        self.assertFalse(r["ok"]); self.assertEqual(r["status"],"PUBLISH_PARTIAL")
        self.assertEqual(len(r["published"]),1)

    def test_report_answers_core_run_questions(self):
        report=build_run_report(
            {"run_id":"r","state":"FAILED","repair_count":1},
            {"strategy":"A_EXISTING_MXD","goal":{"raw_goal":"map","data_root":"D:/data","required_layer_roles":["jalan"],"save_policy":"none","source_edit_policy":"read_only"}},
            validations=[{"status":"FAIL"}],repairs=[{"action":"move"}],artifacts=[],timings={"dominant":"validation"}
        )
        self.assertEqual(report["strategy"],"A_EXISTING_MXD")
        self.assertEqual(report["bottleneck"],"validation")
        md=to_markdown(report); self.assertIn("Status: FAILED",md)

if __name__=="__main__": unittest.main()
