REQUIRED_FULL_GATES=tuple("G%d"%i for i in range(0,11))

def evaluate_release(gates,catalog_diff,files_preserved=True,unit_only_policy=False):
    gates=dict(gates or {})
    blockers=[]
    deferred=[]
    if not catalog_diff.get("baseline_preserved"):
        blockers.append({"code":"BASELINE_CONTRACT_REGRESSION","details":catalog_diff})
    if not files_preserved:
        blockers.append({"code":"FILES_PRESERVATION_VIOLATION"})
    for gate in REQUIRED_FULL_GATES:
        state=str(gates.get(gate) or "MISSING")
        if state!="PASS":
            deferred.append({"gate":gate,"state":state})
    if unit_only_policy and deferred:
        blockers.append({
            "code":"LIVE_ACCEPTANCE_DEFERRED",
            "message":"Unit-only policy intentionally prevents release promotion until live gates are explicitly permitted.",
            "gates":deferred,
        })
    elif deferred:
        blockers.append({"code":"RELEASE_GATES_INCOMPLETE","gates":deferred})
    return {
        "ok":not blockers,
        "status":"READY" if not blockers else "BLOCKED",
        "blockers":blockers,
        "deferred":deferred,
        "baseline_preserved":bool(catalog_diff.get("baseline_preserved")),
        "files_preserved":bool(files_preserved),
    }
