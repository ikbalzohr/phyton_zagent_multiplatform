import os
import re
from pathlib import Path

_RUN_RE=re.compile(r"^[A-Za-z0-9_.-]+$")

class WorkspacePolicyError(ValueError): pass

class RunWorkspace:
    def __init__(self,root):
        self.root=Path(root).resolve()
    def create(self,run_id):
        if not _RUN_RE.match(str(run_id)):
            raise WorkspacePolicyError("INVALID_RUN_ID")
        base=(self.root/str(run_id)).resolve()
        if self.root not in base.parents and base!=self.root:
            raise WorkspacePolicyError("PATH_ESCAPE")
        paths={name:base/name for name in ("context","checkpoints","scratch","staging","evidence")}
        for p in [base,*paths.values()]: p.mkdir(parents=True,exist_ok=True)
        return {"root":str(base),**{k:str(v) for k,v in paths.items()},
                "plan":str(base/"plan.json"),"report_json":str(base/"report.json"),"report_md":str(base/"report.md")}
    def assert_source_read_only(self,source_path,workspace):
        src=Path(source_path).resolve()
        root=Path(workspace["root"]).resolve()
        if src==root or root in src.parents:
            raise WorkspacePolicyError("SOURCE_INSIDE_WORKSPACE")
        return True
