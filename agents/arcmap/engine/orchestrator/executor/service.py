import hashlib
import json

def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

def _hash(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()

class DurableRunService:
    def __init__(self, journal, scheduler):
        self.journal = journal
        self.scheduler = scheduler

    def submit(self, plan, owner, idempotency_key=None, priority=1):
        if not isinstance(plan, dict) or not plan.get("plan_hash"):
            return {"ok":False,"status":"INVALID","errors":[{"code":"PLAN_REQUIRED"}]}
        if plan.get("blockers"):
            return {"ok":False,"status":"BLOCKED","errors":list(plan.get("blockers") or [])}
        session_id=str(owner.get("session_id") or "")
        device_id=str(owner.get("device_id") or "")
        operator_alias=str(owner.get("operator_alias") or "")
        if not session_id or not device_id:
            return {"ok":False,"status":"FAILED","errors":[{"code":"ACCESS_DENIED","message":"Authoritative owner metadata is required."}]}
        key=idempotency_key or _hash({"session_id":session_id,"device_id":device_id,"plan_hash":plan["plan_hash"]})
        try:
            run,created=self.journal.submit_run(
                owner_session_id=session_id,
                device_id=device_id,
                operator_alias=operator_alias,
                plan=plan,
                idempotency_key=key,
                request_id=str(owner.get("request_id") or ""),
                trace_id=str(owner.get("trace_id") or ""),
                document_revision=plan.get("target_revision"),
            )
        except ValueError as exc:
            code=str(exc)
            return {"ok":False,"status":"FAILED","errors":[{"code":code}]}
        if not created:
            return {"ok":True,"status":run["state"],"run_id":run["run_id"],"task_id":run.get("task_id"),"duplicate":True}
        try:
            self.journal.transition(run["run_id"],"PREFLIGHT",owner_session_id=session_id)
            self.journal.transition(run["run_id"],"QUEUED",owner_session_id=session_id)
            task_id=self.scheduler.submit(run_id=run["run_id"],owner_session_id=session_id,plan=plan,priority=priority)
            self.journal.bind_task(run["run_id"],task_id,session_id)
            row=self.journal.get_run(run["run_id"],session_id)
            return {"ok":True,"status":row["state"],"run_id":row["run_id"],"task_id":task_id,"duplicate":False}
        except Exception as exc:
            try:
                self.journal.transition(run["run_id"],"RECOVERY_REQUIRED",owner_session_id=session_id)
            except Exception:
                pass
            return {"ok":False,"status":"RECOVERY_REQUIRED","run_id":run["run_id"],"errors":[{"code":"SCHEDULER_SUBMIT_FAILED","message":str(exc)}]}

    def status(self, run_id, owner_session_id):
        try:
            row=self.journal.get_run(run_id,owner_session_id)
        except PermissionError:
            return {"ok":False,"status":"FAILED","errors":[{"code":"ACCESS_DENIED"}]}
        if not row:
            return {"ok":False,"status":"FAILED","errors":[{"code":"RUN_NOT_FOUND"}]}
        return {"ok":True,"status":row["state"],"run":row,"steps":self.journal.list_run_steps(run_id,owner_session_id)}

    def cancel(self, run_id, owner_session_id):
        try:
            row=self.journal.request_cancel(run_id,owner_session_id)
        except PermissionError:
            return {"ok":False,"status":"FAILED","errors":[{"code":"ACCESS_DENIED"}]}
        except KeyError:
            return {"ok":False,"status":"FAILED","errors":[{"code":"RUN_NOT_FOUND"}]}
        task_id=row.get("task_id")
        scheduler_ack=False
        if task_id:
            try:
                scheduler_ack=bool(self.scheduler.cancel(task_id,owner_session_id))
            except Exception:
                scheduler_ack=False
        return {"ok":True,"status":row["state"],"run_id":run_id,"task_id":task_id,"scheduler_cancel_ack":scheduler_ack}

    def resume(self, run_id, owner_session_id, review_decision=None):
        try:
            row=self.journal.get_run(run_id,owner_session_id)
        except PermissionError:
            return {"ok":False,"status":"FAILED","errors":[{"code":"ACCESS_DENIED"}]}
        if not row:
            return {"ok":False,"status":"FAILED","errors":[{"code":"RUN_NOT_FOUND"}]}
        if row["state"] == "RECONCILING":
            return {"ok":False,"status":"RECONCILING","errors":[{"code":"OUTCOME_UNKNOWN","message":"Reconciliation must resolve before resume."}]}
        if row["state"] == "RECOVERY_REQUIRED":
            return {"ok":False,"status":"RECOVERY_REQUIRED","errors":[{"code":"RECOVERY_REQUIRED"}]}
        if row["state"] not in ("WAITING_FOR_REVIEW","BLOCKED"):
            return {"ok":False,"status":row["state"],"errors":[{"code":"RESUME_NOT_ALLOWED"}]}
        if row["state"] == "WAITING_FOR_REVIEW" and not isinstance(review_decision,dict):
            return {"ok":False,"status":"WAITING_FOR_REVIEW","errors":[{"code":"REVIEW_DECISION_REQUIRED"}]}
        try:
            row=self.journal.transition(run_id,"PREFLIGHT",owner_session_id=owner_session_id)
        except ValueError as exc:
            return {"ok":False,"status":row["state"],"errors":[{"code":str(exc)}]}
        return {"ok":True,"status":row["state"],"run_id":run_id}

    def report(self, run_id, owner_session_id):
        try:
            report=self.journal.report(run_id,owner_session_id)
        except PermissionError:
            return {"ok":False,"status":"FAILED","errors":[{"code":"ACCESS_DENIED"}]}
        except Exception as exc:
            return {"ok":False,"status":"FAILED","errors":[{"code":"RUN_NOT_FOUND","message":str(exc)}]}
        return {"ok":True,"status":report["run"]["state"],"data":report}
