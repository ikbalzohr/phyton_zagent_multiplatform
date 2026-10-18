import hashlib
import json
from orchestrator.compiler import compile_plan
from orchestrator.concurrency import ResourceClaim, claims_conflict

def _hash(v):
    return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),default=str).encode("utf-8")).hexdigest()

def _output_key(goal):
    outputs=goal.get("outputs") or {}
    return str(outputs.get("output_dir") or "")+"|"+str(goal.get("title") or goal.get("raw_goal") or "")

class BatchCoordinator:
    def compile(self,goals,contexts=None,claims=None):
        goals=list(goals or [])
        contexts=list(contexts or [{} for _ in goals])
        claims=list(claims or [[] for _ in goals])
        if len(contexts)!=len(goals) or len(claims)!=len(goals):
            return {"ok":False,"status":"INVALID","errors":[{"code":"BATCH_LENGTH_MISMATCH"}]}
        output_keys=[_output_key(g) for g in goals]
        duplicates=sorted({x for x in output_keys if x and output_keys.count(x)>1})
        if duplicates:
            return {"ok":False,"status":"BLOCKED","errors":[{"code":"OUTPUT_COLLISION","keys":duplicates}]}
        items=[]
        for index,(goal,ctx,item_claims) in enumerate(zip(goals,contexts,claims)):
            compiled=compile_plan(goal,context=ctx)
            items.append({
                "item_id":"batch_"+_hash({"index":index,"goal":goal})[:16],
                "index":index,
                "compiled":compiled,
                "claims":[c if isinstance(c,ResourceClaim) else ResourceClaim(**c) for c in item_claims],
            })
        if any(x["compiled"].get("status") in {"INVALID","BLOCKED"} for x in items):
            return {"ok":False,"status":"BLOCKED","items":items,
                    "errors":[{"code":"BATCH_ITEM_BLOCKED"}]}
        waves=[]
        for item in items:
            placed=False
            for wave in waves:
                existing=[c for x in wave for c in x["claims"]]
                if not any(claims_conflict(a,b) for a in item["claims"] for b in existing):
                    wave.append(item); placed=True; break
            if not placed:
                waves.append([item])
        return {"ok":True,"status":"PLANNED","items":items,
                "waves":[[x["item_id"] for x in wave] for wave in waves]}
