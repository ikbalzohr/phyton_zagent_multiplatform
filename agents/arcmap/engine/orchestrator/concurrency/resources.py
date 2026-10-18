import ntpath
from dataclasses import dataclass

@dataclass(frozen=True)
class ResourceClaim:
    key: str
    mode: str = "read"
    owner_session_id: str = ""

def _norm_path(path):
    if not path:
        return ""
    return ntpath.normcase(ntpath.normpath(ntpath.abspath(str(path)))).replace("\\","/")

def arcmap_document_key(device_id,instance_id,process_start_time,document_id,document_epoch):
    parts=[device_id,instance_id,process_start_time,document_id,document_epoch]
    if any(x in (None,"") for x in parts):
        raise ValueError("INCOMPLETE_ARCMAP_IDENTITY")
    return "arcmap:%s:%s:%s:%s:%s" % tuple(str(x) for x in parts)

def path_resource_key(path,kind="path"):
    normalized=_norm_path(path)
    if not normalized:
        raise ValueError("PATH_REQUIRED")
    return "%s:%s" % (kind,normalized)

def claims_conflict(a,b):
    if a.key!=b.key:
        return False
    return not (a.mode=="read" and b.mode=="read")

def stable_claim_order(claims):
    return sorted(list(claims or []),key=lambda x:(x.key,0 if x.mode=="read" else 1,x.owner_session_id))

def conflict_matrix(claims):
    items=list(claims or [])
    out=[]
    for i,a in enumerate(items):
        for b in items[i+1:]:
            if claims_conflict(a,b):
                out.append((a,b))
    return out
