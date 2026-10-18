def normalize_probe(raw):
    raw=dict(raw or {})
    bitness=int(raw.get("bitness") or 0)
    return {
        "ok":bool(raw.get("ok")),
        "python_version":raw.get("python_version"),
        "bitness":bitness,
        "licenses":sorted(set(raw.get("licenses") or [])),
        "extensions":sorted(set(raw.get("extensions") or [])),
        "supported_tools":sorted(set(raw.get("supported_tools") or [])),
        "parallel_processing_supported":bool(raw.get("parallel_processing_supported")),
    }

def choose_worker(probes,requirements):
    req_licenses=set(requirements.get("licenses") or [])
    req_ext=set(requirements.get("extensions") or [])
    req_tools=set(requirements.get("tools") or [])
    candidates=[]
    for p in map(normalize_probe,probes or []):
        if not p["ok"]: continue
        if not req_licenses<=set(p["licenses"]): continue
        if not req_ext<=set(p["extensions"]): continue
        if not req_tools<=set(p["supported_tools"]): continue
        candidates.append(p)
    if not candidates:
        return {"ok":False,"code":"CAPABILITY_UNAVAILABLE"}
    candidates.sort(key=lambda x:(x["bitness"]!=64,-x["bitness"],x["python_version"] or ""))
    return {"ok":True,"worker":candidates[0]}
