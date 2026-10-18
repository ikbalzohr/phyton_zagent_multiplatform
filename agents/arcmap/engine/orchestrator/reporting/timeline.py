from orchestrator.executor.state import progress_fraction

_WAITING={"BLOCKED","WAITING_FOR_REVIEW","RECONCILING","RECOVERY_REQUIRED"}

def _artifact_summary(artifacts):
    items=list(artifacts or [])
    valid=[x for x in items if bool(x.get("valid") or (x.get("validation") or {}).get("ok"))]
    return {"total":len(items),"valid":len(valid),"all_valid":bool(items) and len(valid)==len(items)}

def build_timeline(run,steps=None,validations=None,artifacts=None,now=None,history_eta=None):
    steps=list(steps or [])
    completed=sum(1 for x in steps if x.get("state")=="SUCCEEDED")
    total=len(steps)
    state=str(run.get("state") or "PLANNED")
    active=next((x for x in steps if x.get("state") in {"INTENT_RECORDED","RUNNING","OUTCOME_UNKNOWN"}),None)
    waiting_reason=None
    if state in _WAITING:
        blockers=run.get("blockers") or run.get("blockers_json") or []
        waiting_reason=(blockers[0].get("code") if blockers and isinstance(blockers[0],dict) else state)
    eta=None
    if isinstance(history_eta,(int,float)) and history_eta>=0:
        eta=float(history_eta)
    return {
        "run_id":run.get("run_id"),
        "state":state,
        "phase":state,
        "completed_steps":completed,
        "total_steps":total,
        "progress":(completed/float(total)) if total else progress_fraction(state),
        "active_step":active.get("step_id") if active else None,
        "waiting_reason":waiting_reason,
        "cancel_requested":bool(run.get("cancel_requested")),
        "eta_seconds":eta,
        "eta_is_evidence_based":eta is not None,
        "artifact_summary":_artifact_summary(artifacts),
        "validation_statuses":[x.get("status") for x in (validations or [])],
        "task_id":run.get("task_id"),
        "request_id":run.get("request_id"),
        "trace_id":run.get("trace_id"),
    }

def evidence_view(report):
    return {
        "run_id":(report.get("run") or {}).get("run_id"),
        "validations":list(report.get("validations") or []),
        "artifacts":list(report.get("artifacts") or []),
        "receipts":list(report.get("receipts") or []),
        "publish_attempts":list(report.get("publish_attempts") or []),
    }
