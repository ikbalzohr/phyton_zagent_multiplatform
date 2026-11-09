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
            if not isinstance(payload, dict):
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

    def inspect_mxd(self, *, mxd_path):
        """Inspect an explicit disk document in the trusted file-worker lane."""
        return self._call('inspect_mxd', {'mxd_path': mxd_path}, timeout=60)

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

    def print_ready_template(self, *, template_mxd, data_root, output_root,
                             scale=0, dpi=400, main_frame='Layers',
                             expected_crs='WGS_1984_UTM_Zone_51N', resolved_rules=None):
        """Isolated Python2/ArcPy disk-only print job, never CURRENT."""
        if resolved_rules is None:
            from orchestrator.cartographic_rules import resolve_rules
            resolved_rules = resolve_rules(self.engine_root, data_root,
                                           scale_override=scale)
        result = self._call('print_ready_template', {
            'template_mxd': template_mxd, 'data_root': data_root,
            'output_root': output_root, 'scale': float(scale),
            'dpi': int(dpi), 'main_frame': main_frame,
            'expected_crs': expected_crs, 'resolved_rules': resolved_rules,
        }, timeout=300)
        if not result.get('ok'):
            return result
        from orchestrator.validators.pdf_export import validate_pdf_png
        exports = result.get('exports') or {}
        pdf = (exports.get('PDF') or {}).get('path')
        png = (exports.get('PNG') or {}).get('path')
        if not pdf or not png:
            return dict(result, ok=False, code='EXPORT_PATH_MISSING')
        verification = validate_pdf_png(pdf, png, int(dpi))
        result['structural_qa'] = verification
        result['print_ready_accepted'] = False
        if not verification['ok']:
            result['ok'] = False
            result['code'] = 'STRUCTURAL_QA_FAILED'
        report = result.get('working_mxd')
        if report and Path(report).is_file():
            (Path(report).parent / 'structural_qa.json').write_text(
                json.dumps(verification, ensure_ascii=False, indent=2),
                encoding='utf-8')
        return result

    def render_staging(self, *, working_mxd, staging_dir, outputs, base_name=""):
        return self._call("render_staging",{
            "working_mxd":working_mxd,
            "staging_dir":staging_dir,
            "outputs":outputs,
            "base_name":base_name,
        })
