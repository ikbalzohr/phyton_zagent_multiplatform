import hashlib
import json
from pathlib import Path

def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),default=str)

def schema_hash(parameters):
    return hashlib.sha256(_canonical(parameters).encode("utf-8")).hexdigest()

def catalog_from_mcp(mcp):
    manager=getattr(mcp,"_tool_manager",None) or getattr(mcp,"tool_manager",None)
    tools=getattr(manager,"_tools",None) or getattr(manager,"tools",None)
    if not isinstance(tools,dict):
        raise RuntimeError("MCP_TOOL_REGISTRY_UNAVAILABLE")
    items=[]
    for name in sorted(tools):
        obj=tools[name]
        params=getattr(obj,"parameters",{}) or {}
        items.append({
            "name":name,
            "description":getattr(obj,"description","") or "",
            "parameters":params,
            "schema_sha256":schema_hash(params),
        })
    payload={"count":len(items),"tools":items}
    payload["catalog_sha256"]=hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()
    return payload

def load_catalog(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def compare_catalogs(baseline,candidate):
    a={x["name"]:x["schema_sha256"] for x in baseline.get("tools") or []}
    b={x["name"]:x["schema_sha256"] for x in candidate.get("tools") or []}
    return {
        "baseline_count":len(a),
        "candidate_count":len(b),
        "common":len(set(a)&set(b)),
        "added":sorted(set(b)-set(a)),
        "removed":sorted(set(a)-set(b)),
        "changed":sorted(name for name in set(a)&set(b) if a[name]!=b[name]),
        "baseline_preserved":not (set(a)-set(b)) and not any(a[name]!=b[name] for name in set(a)&set(b)),
    }
