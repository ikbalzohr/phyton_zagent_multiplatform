import tempfile
import unittest
from pathlib import Path

from orchestrator.staging import RunWorkspace, WorkspacePolicyError, StrategyBCStager, allowed_for_orchestrated_final

class FakeWorker:
    def __init__(self): self.calls=[]; self.probe_result={"ok":True}
    def probe(self): self.calls.append(("probe",{})); return dict(self.probe_result)
    def prepare_template(self,**kwargs):
        self.calls.append(("template",kwargs)); return {"ok":True,"working_mxd":str(Path(kwargs["workspace"])/"working.mxd")}
    def prepare_blank(self,**kwargs):
        self.calls.append(("blank",kwargs)); return {"ok":True,"working_mxd":str(Path(kwargs["workspace"])/"blank.mxd")}
    def render_staging(self,**kwargs):
        self.calls.append(("render",kwargs)); return {"ok":True,"artifacts":[str(Path(kwargs["staging_dir"])/"map.pdf")]}

class StagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)/"runs"; self.data=Path(self.tmp.name)/"source"; self.data.mkdir()
        self.template=Path(self.tmp.name)/"template.mxd"; self.template.write_text("fixture")
        self.worker=FakeWorker(); self.stager=StrategyBCStager(self.worker,self.root)
    def tearDown(self): self.tmp.cleanup()

    def test_workspace_rejects_path_escape_run_id(self):
        with self.assertRaisesRegex(WorkspacePolicyError,"INVALID_RUN_ID"):
            RunWorkspace(self.root).create("../escape")

    def test_template_prepare_stays_in_run_workspace_and_never_publishes(self):
        plan={"strategy":"B_TEMPLATE_DATA","goal":{"data_root":str(self.data),"template_mxd":str(self.template)}}
        r=self.stager.prepare("run_1",plan)
        self.assertTrue(r["ok"]); self.assertFalse(r["publish_allowed"])
        self.assertTrue(r["working_mxd"].startswith(r["workspace"]["root"]))

    def test_blank_requires_explicit_disposable_target(self):
        plan={"strategy":"C_BLANK_DATA","goal":{"data_root":str(self.data)}}
        r=self.stager.prepare("run_2",plan)
        self.assertEqual(r["errors"][0]["code"],"DISPOSABLE_TARGET_REQUIRED")
        self.assertFalse(any(c[0]=="blank" for c in self.worker.calls))

    def test_blank_disposable_prepares_working_copy(self):
        plan={"strategy":"C_BLANK_DATA","goal":{"data_root":str(self.data),"target_disposable":True}}
        r=self.stager.prepare("run_3",plan)
        self.assertTrue(r["ok"]); self.assertTrue(any(c[0]=="blank" for c in self.worker.calls))

    def test_worker_unavailable_blocks_before_prepare(self):
        self.worker.probe_result={"ok":False,"reason":"license"}
        plan={"strategy":"B_TEMPLATE_DATA","goal":{"data_root":str(self.data),"template_mxd":str(self.template)}}
        r=self.stager.prepare("run_4",plan)
        self.assertEqual(r["errors"][0]["code"],"CAPABILITY_UNAVAILABLE")

    def test_preprobed_worker_is_not_probed_twice(self):
        plan={"strategy":"B_TEMPLATE_DATA","goal":{"data_root":str(self.data),"template_mxd":str(self.template)}}
        r=self.stager.prepare("run_preprobed",plan,probe={"ok":True,"arcgis_version":"10.6.1"})
        self.assertTrue(r["ok"])
        self.assertFalse(any(c[0]=="probe" for c in self.worker.calls))

    def test_staging_render_is_not_final_publish(self):
        plan={"strategy":"B_TEMPLATE_DATA","goal":{"data_root":str(self.data),"template_mxd":str(self.template)}}
        prepared=self.stager.prepare("run_5",plan)
        r=self.stager.render_staging(prepared,{"formats":["PDF","PNG"],"dpi":400})
        self.assertTrue(r["ok"]); self.assertEqual(r["status"],"STAGED"); self.assertFalse(r["publish_allowed"])

    def test_known_composites_are_forbidden_for_direct_final(self):
        self.assertFalse(allowed_for_orchestrated_final("arcmap_stage2_batch_build"))
        self.assertFalse(allowed_for_orchestrated_final("arcmap_stage3_build_blank_a4"))

if __name__=="__main__": unittest.main()
