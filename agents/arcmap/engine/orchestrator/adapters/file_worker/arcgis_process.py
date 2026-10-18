import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

class ArcGISProcessFileWorker:
    def __init__(self, engine_root, python_exe=None, timeout_seconds=300):
        self.engine_root=Path(engine_root).resolve()
        self.python_exe=str(
            python_exe or os.environ.get(
                "ZAGENT_ARCGIS_PYTHON",
                r"C:\Python27\ArcGIS10.6\python.exe"))
        self.timeout_seconds=max(10,int(timeout_seconds))
        self.entry=Path(__file__).with_name("worker27.py")

    def _call(self, operation, arguments=None, timeout=None):
        started=time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="zagent_arc_worker_") as td:
            req=Path(td)/"request.json"
            res=Path(td)/"response.json"
            req.write_text(json.dumps({
                "operation":operation,
                "engine_root":str(self.engine_root),
                "arguments":arguments or {},
            },ensure_ascii=False),encoding="utf-8")
            try:
                cp=subprocess.run(
                    [self.python_exe,str(self.entry),str(req),str(res)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=int(timeout or self.timeout_seconds),
                    creationflags=0x08000000 if os.name=="nt" else 0,
                )
            except subprocess.TimeoutExpired as exc:
                return {
                    "ok":False,
                    "code":"DEADLINE_EXCEEDED",
                    "message":str(exc),
                    "duration_ms":round((time.perf_counter()-started)*1000,3),
                }
            payload=None
            if res.exists():
                try:
                    payload=json.loads(res.read_text(encoding="utf-8"))
                except Exception:
                    payload=None
            if payload is None:
                payload={
                    "ok":False,
                    "code":"FILE_WORKER_NO_RESULT",
                    "exit_code":cp.returncode,
                    "stdout":cp.stdout.decode("utf-8","replace")[-4000:],
                    "stderr":cp.stderr.decode("utf-8","replace")[-4000:],
                }
            payload.setdefault("exit_code",cp.returncode)
            payload["duration_ms"]=round((time.perf_counter()-started)*1000,3)
            if cp.returncode!=0 and payload.get("ok"):
                payload["ok"]=False
                payload["code"]="FILE_WORKER_EXIT_FAILED"
            return payload

    def probe(self):
        return self._call("probe",timeout=60)

    def discover_data(self, *, data_root, max_items=10000):
        return self._call("discover_data",{
            "data_root":data_root,
            "max_items":int(max_items),
        },timeout=180)

    def preview_match(self, *, data_root, recipe, max_items=10000, min_score=0.62):
        return self._call("preview_match",{
            "data_root":data_root,
            "recipe":recipe or {},
            "max_items":int(max_items),
            "min_score":float(min_score),
        },timeout=180)

    def validate_template(self, *, template_mxd, profile=None):
        return self._call("validate_template",{
            "template_mxd":template_mxd,
            "profile":profile or {},
        },timeout=180)

    def prepare_template(self, *, template_mxd, data_root, workspace, goal):
        return self._call("prepare_template",{
            "template_mxd":template_mxd,
            "data_root":data_root,
            "workspace":workspace,
            "goal":goal,
        })

    def prepare_blank(self, *, data_root, workspace, goal, disposable):
        return self._call("prepare_blank",{
            "data_root":data_root,
            "workspace":workspace,
            "goal":goal,
            "disposable":bool(disposable),
        })

    def render_staging(self, *, working_mxd, staging_dir, outputs, base_name=""):
        return self._call("render_staging",{
            "working_mxd":working_mxd,
            "staging_dir":staging_dir,
            "outputs":outputs,
            "base_name":base_name,
        })
