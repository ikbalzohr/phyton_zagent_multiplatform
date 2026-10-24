import os
import shutil
import uuid
from pathlib import Path
from .validation import validate_pdf, validate_png

class PublishError(RuntimeError): pass

class Publisher:
    def __init__(self,journal=None,copier=None):
        self.journal=journal
        self.copier=copier or shutil.copy2

    def validate(self,artifacts):
        checked=[]
        for a in artifacts or []:
            kind=str(a.get("kind") or "").upper()
            fn=validate_pdf if kind=="PDF" else validate_png if kind=="PNG" else None
            if fn is None:
                checked.append({**a,"validation":{"ok":False,"code":"ARTIFACT_INVALID","reason":"unsupported_kind"}})
            else:
                checked.append({**a,"validation":fn(a.get("path"),a.get("metadata") or {})})
        ok=bool(checked) and all(x["validation"].get("ok") for x in checked)
        required={"PDF","PNG"}
        present={str(x.get("kind") or "").upper() for x in checked if x["validation"].get("ok")}
        if not required<=present: ok=False
        return {"ok":ok,"artifacts":checked,"missing_required":sorted(required-present)}

    def _target(self,base,name,policy):
        target=Path(base)/name
        if not target.exists(): return target,None
        if policy=="deny": raise PublishError("OUTPUT_COLLISION")
        if policy=="version":
            stem=target.stem; suffix=target.suffix
            for i in range(1,10000):
                p=target.with_name("%s_v%d%s"%(stem,i,suffix))
                if not p.exists(): return p,None
            raise PublishError("VERSION_EXHAUSTED")
        if policy=="overwrite":
            backup=target.with_name(target.name+".bak_"+uuid.uuid4().hex[:8])
            return target,backup
        raise PublishError("INVALID_OVERWRITE_POLICY")

    def publish(self,run_id,artifacts,output_dir,overwrite_policy="deny"):
        gate=self.validate(artifacts)
        if not gate["ok"]:
            return {"ok":False,"status":"ARTIFACT_INVALID","gate":gate,"published":[]}
        out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
        published=[]; attempts=[]
        try:
            for item in gate["artifacts"]:
                src=Path(item["path"]); target,backup=self._target(out,src.name,overwrite_policy)
                if backup is not None and target.exists():
                    self.copier(str(target),str(backup))
                attempt={"attempt_id":"pub_"+uuid.uuid4().hex,"run_id":run_id,"source":str(src),
                         "target":str(target),"backup":str(backup) if backup else None,"state":"STARTED"}
                attempts.append(attempt)
                if self.journal and hasattr(self.journal,"record_publish_attempt"):
                    self.journal.record_publish_attempt(attempt)
                self.copier(str(src),str(target))
                attempt["state"]="SUCCEEDED"; published.append(str(target))
                if self.journal and hasattr(self.journal,"record_publish_attempt"):
                    self.journal.record_publish_attempt(attempt)
        except Exception as exc:
            return {"ok":False,"status":"PUBLISH_PARTIAL","published":published,"attempts":attempts,
                    "error":{"code":"PUBLISH_PARTIAL","message":str(exc)}}
        manifest={"run_id":run_id,"artifacts":published,"complete":True}
        return {"ok":True,"status":"PUBLISHED","published":published,"attempts":attempts,"completion_manifest":manifest}
