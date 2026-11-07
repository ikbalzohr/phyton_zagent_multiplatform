import hashlib, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import core_self_update as u

def h(b):return hashlib.sha256(b).hexdigest()
def sample_manifest(src):
    return json.dumps({"file_count":1,"total_bytes":len(src),"files":[
        {"Path":"Zagent.Core.exe","Size":len(src),"Sha256":h(src)}]},
        indent=2).encode()

class CoreUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.install=root/"install";self.data=root/"data"
        self.install.mkdir();self.data.mkdir()
        self.old=b"old-core-bytes"
        (self.install/"Zagent.Core.exe").write_bytes(self.old)
        (self.install/"Zagent.Launcher.exe").write_bytes(b"launcher")
        self.manifest=sample_manifest(self.old)
        (self.install/"payload-manifest.json").write_bytes(self.manifest)
        self.new=root/"candidate.exe";self.new.write_bytes(b"new-core-content")
        self.id="unit-test-20261107"
        self.plan=u.prepare(self.install,self.data,self.id,self.new)

    def test_stage_validate_and_manifest(self):
        a,b,c,plan,token=u.validate(self.install,self.data,self.id,self.plan)
        self.assertEqual(token,self.plan)
        newmanifest=u.modified_manifest(self.manifest, h(self.old),len(self.old),
                                    h(self.new.read_bytes()),self.new.stat().st_size)
        fresh=json.loads(newmanifest)
        self.assertEqual(fresh["files"][0]["Sha256"],h(self.new.read_bytes()))
        self.assertEqual(fresh["total_bytes"],len(self.new.read_bytes()))

    def test_tampered_staged_exe_fails_closed(self):
        (self.data/"core-updates/staged"/self.id/"Zagent.Core.exe").write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            u.validate(self.install,self.data,self.id,self.plan)

    def test_independent_worker_applies_and_persists_result(self):
        class Launcher:
            returncode=0
            def wait(self,timeout=0):pass
        with patch.object(u,"wait_pid_exit",return_value=True), patch.object(u,"restart_core",return_value=Launcher()), patch.object(u,"reachable",return_value=True):
            self.assertTrue(u.worker(self.install,self.data,self.id,self.plan,9999,1234))
        self.assertEqual((self.install/"Zagent.Core.exe").read_bytes(),self.new.read_bytes())
        self.assertEqual(json.loads((self.data/"core-updates/results"/(self.id+".json")).read_text())["state"],"succeeded")

    def test_failed_restart_rolls_back_and_does_not_claim_success(self):
        class Launcher:
            returncode=0
            def wait(self,timeout=0):pass
        with patch.object(u,"wait_pid_exit",return_value=True), patch.object(u,"restart_core",side_effect=[RuntimeError("first start failed"),Launcher()]):
            with self.assertRaises(RuntimeError):
                u.worker(self.install,self.data,self.id,self.plan,9999,1234)
        self.assertEqual((self.install/"Zagent.Core.exe").read_bytes(),self.old)
        self.assertEqual((self.install/"payload-manifest.json").read_bytes(),self.manifest)
        self.assertEqual(json.loads((self.data/"core-updates/results"/(self.id+".json")).read_text())["state"],"rolled_back")

    def test_core_does_not_exit_timeout_no_changes(self):
        with patch.object(u,"wait_pid_exit",return_value=False):
            self.assertFalse(u.worker(self.install,self.data,self.id,self.plan,9999,1234))
        self.assertEqual((self.install/"Zagent.Core.exe").read_bytes(),self.old)
        self.assertEqual(json.loads((self.data/"core-updates/results"/(self.id+".json")).read_text())["state"],"failed")
if __name__=="__main__":unittest.main()
