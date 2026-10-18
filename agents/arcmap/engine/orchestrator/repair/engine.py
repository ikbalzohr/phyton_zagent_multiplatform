from .registry import RepairRegistry, fingerprint_issue

class RepairEngine:
    def __init__(self,registry=None):
        self.registry=registry or RepairRegistry()
    def run_cycle(self,state,issue,action,adapter,checkpoint_factory,score_before=None):
        cycles=int(state.get("repair_count",0))
        if cycles>=self.registry.max_cycles:
            return {"ok":False,"status":"FAILED","code":"REPAIR_BUDGET_EXHAUSTED","state":state}
        policy=self.registry.validate_action(action)
        if not policy.get("ok"):
            return {"ok":False,"status":"FAILED","code":policy["code"],"state":state}
        fp=fingerprint_issue(issue,action)
        seen=set(state.get("repair_fingerprints") or [])
        if fp in seen:
            return {"ok":False,"status":"FAILED","code":"REPAIR_LOOP_DETECTED","state":state}
        checkpoint=checkpoint_factory(action,issue)
        if not checkpoint or not checkpoint.get("ok"):
            return {"ok":False,"status":"RECOVERY_REQUIRED","code":"CHECKPOINT_FAILED","state":state}
        applied=adapter.apply_repair(action,issue,checkpoint=checkpoint)
        new_state=dict(state); new_state["repair_count"]=cycles+1
        new_state["repair_fingerprints"]=list(seen|{fp})
        if not applied.get("ok"):
            return {"ok":False,"status":"FAILED","code":applied.get("code") or "REPAIR_FAILED","state":new_state}
        verify=adapter.verify_repair(action,issue)
        if not verify.get("ok"):
            return {"ok":False,"status":"FAILED","code":"REPAIR_VERIFICATION_FAILED","state":new_state}
        score_after=verify.get("score")
        if score_before is not None and score_after is not None and score_after<score_before:
            return {"ok":False,"status":"FAILED","code":"REPAIR_WORSENED","state":new_state}
        return {"ok":True,"status":"VALIDATING","state":new_state,"verification":verify,"checkpoint":checkpoint}
