WRITE_EFFECTS={"live_write","file_write","save","export","publish"}

def reconcile_outcome(*,effect_class,receipt=None,worker_state=None,postcondition=None,artifact=None):
    receipt=receipt or {}
    worker_state=worker_state or {}
    postcondition=postcondition or {}
    artifact=artifact or {}
    outcome=receipt.get("outcome")
    if outcome=="SUCCEEDED" and postcondition.get("matches") is True:
        return {"status":"SUCCEEDED","retry_allowed":False,"reason":"verified_effect"}
    if outcome=="FAILED" and receipt.get("effect_applied") is False:
        return {"status":"FAILED","retry_allowed":effect_class not in WRITE_EFFECTS,"reason":"verified_no_effect"}
    if worker_state.get("claimed") is False and receipt.get("effect_applied") is False:
        return {"status":"SAFE_TO_RETRY","retry_allowed":True,"reason":"never_claimed"}
    if effect_class in {"export","publish"} and artifact.get("verified") is True:
        return {"status":"SUCCEEDED","retry_allowed":False,"reason":"verified_artifact"}
    if outcome in ("OUTCOME_UNKNOWN",None) or worker_state.get("lost"):
        return {"status":"RECOVERY_REQUIRED","retry_allowed":False,"reason":"ambiguous_effect"}
    return {"status":"RECOVERY_REQUIRED","retry_allowed":False,"reason":"insufficient_evidence"}

def late_result_policy(cancel_requested,result):
    if cancel_requested:
        return {"accept_for_history":True,"publish_allowed":False,"state":"CANCEL_REQUESTED",
                "reason":"late_result_quarantined"}
    return {"accept_for_history":True,"publish_allowed":True,"state":"RESULT_AVAILABLE"}
