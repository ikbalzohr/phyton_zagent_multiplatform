import hashlib
import json
import uuid

def _canonical(v):
    return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)

def _hash(v):
    return hashlib.sha256(_canonical(v).encode("utf-8")).hexdigest()

def _same_target(expected, actual):
    keys=("device_id","instance_id","process_start_time","document_id","document_epoch")
    return all(expected.get(k) in (None,"") or expected.get(k)==actual.get(k) for k in keys)

class StrategyAExecutor:
    """Safe existing-MXD executor. It is adapter-driven and never imports ArcPy."""

    def __init__(self,journal,live):
        self.journal=journal
        self.live=live

    def preflight(self,run_id,owner_session_id,plan,expected_context):
        if plan.get("strategy")!="A_EXISTING_MXD":
            return {"ok":False,"code":"STRATEGY_MISMATCH"}
        identity=self.live.inspect_identity()
        if not identity.get("ok"):
            return {"ok":False,"code":"CONTEXT_INCOMPLETE","details":identity}
        if not _same_target(expected_context,identity):
            return {"ok":False,"code":"TARGET_STALE","expected":expected_context,"actual":identity}
        expected_revision=expected_context.get("document_revision")
        actual_revision=identity.get("document_revision")
        if expected_revision not in (None,"") and actual_revision!=expected_revision:
            return {"ok":False,"code":"TARGET_STALE","expected_revision":expected_revision,"actual_revision":actual_revision}
        snapshot=self.live.snapshot_state(expected_context=expected_context)
        if not snapshot.get("ok"):
            return {"ok":False,"code":"CHECKPOINT_FAILED","details":snapshot}
        required=set(plan.get("required_checkpoint_coverage") or ["live_state"])
        coverage=set(snapshot.get("coverage") or [])
        if not required <= coverage:
            return {"ok":False,"code":"ROLLBACK_COVERAGE_INSUFFICIENT","required":sorted(required),"actual":sorted(coverage)}
        cp_id=self.journal.add_checkpoint(run_id,owner_session_id,
            {"coverage":sorted(coverage),"snapshot_id":snapshot.get("snapshot_id"),"limitations":snapshot.get("limitations") or []},
            snapshot.get("fingerprint"),expected_context.get("document_revision"))
        return {"ok":True,"identity":identity,"snapshot":snapshot,"checkpoint_id":cp_id}

    def execute(self,run_id,owner_session_id,plan,expected_context,recipe,fencing_epoch,cancel_requested=lambda:False):
        pre=self.preflight(run_id,owner_session_id,plan,expected_context)
        if not pre.get("ok"):
            return {"ok":False,"status":"BLOCKED","errors":[{"code":pre["code"],"details":pre}]}
        if cancel_requested():
            return {"ok":False,"status":"CANCEL_REQUESTED","errors":[{"code":"CANCEL_REQUESTED"}]}
        valid=self.live.validate_recipe(recipe)
        if not valid.get("ok"):
            return {"ok":False,"status":"FAILED","errors":[{"code":"DATA_INVALID","details":valid}]}
        step_id=str(plan.get("execution_step_id") or "s100")
        request_id="req_"+uuid.uuid4().hex
        input_payload={"recipe":recipe,"target":expected_context,"fencing_epoch":fencing_epoch}
        try:
            self.journal.step_intent(run_id,step_id,request_id,input_payload,owner_session_id)
        except Exception as exc:
            return {"ok":False,"status":"FAILED","errors":[{"code":"INTENT_JOURNAL_FAILED","message":str(exc)}]}
        result=self.live.apply_recipe(recipe,expected_context=expected_context,fencing_epoch=fencing_epoch)
        unknown=(result.get("outcome")=="UNKNOWN" or result.get("action_may_have_completed") is True or
                 result.get("code") in {"OUTCOME_UNKNOWN","BRIDGE_TIMEOUT_AFTER_CLAIM"})
        if unknown:
            self.journal.step_result(run_id,step_id,owner_session_id=owner_session_id,outcome="OUTCOME_UNKNOWN",
                                     result=result,request_id=request_id)
            self.journal.record_receipt(run_id=run_id,step_id=step_id,request_id=request_id,
                                        effect_class="live_write",outcome="OUTCOME_UNKNOWN",result=result)
            try: self.journal.transition(run_id,"RECONCILING",owner_session_id=owner_session_id)
            except Exception: pass
            return {"ok":False,"status":"RECONCILING","errors":[{"code":"OUTCOME_UNKNOWN"}],"replay_allowed":False}
        if not result.get("ok"):
            self.journal.step_result(run_id,step_id,owner_session_id=owner_session_id,outcome="FAILED",
                                     error=result,request_id=request_id)
            return {"ok":False,"status":"FAILED","errors":[{"code":result.get("code") or "EXECUTION_FAILED","details":result}]}
        self.journal.step_result(run_id,step_id,owner_session_id=owner_session_id,outcome="SUCCEEDED",
                                 result=result,request_id=request_id)
        receipt=self.journal.record_receipt(run_id=run_id,step_id=step_id,request_id=request_id,
            effect_class="live_write",outcome="SUCCEEDED",result=result,effect_hash=_hash(result))
        if cancel_requested():
            return {"ok":False,"status":"CANCEL_REQUESTED","errors":[{"code":"LATE_RESULT_QUARANTINED"}],
                    "receipt_id":receipt,"publish_allowed":False}
        verify=self.live.verify_postconditions(plan.get("postconditions") or [],expected_context=expected_context)
        if not verify.get("ok"):
            return {"ok":False,"status":"FAILED","errors":[{"code":"POSTCONDITION_FAILED","details":verify}],
                    "checkpoint_id":pre["checkpoint_id"],"receipt_id":receipt}
        self.journal.acknowledge_receipt(receipt)
        return {"ok":True,"status":"VALIDATING","checkpoint_id":pre["checkpoint_id"],
                "receipt_id":receipt,"verification":verify,
                "snapshot":pre.get("snapshot"),"identity":pre.get("identity")}
