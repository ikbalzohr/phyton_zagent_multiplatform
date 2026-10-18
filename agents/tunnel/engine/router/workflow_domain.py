from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

RUN_STATES = {
    "PLANNED","PREFLIGHT","QUEUED","RUNNING","VALIDATING","STAGING","PUBLISHING",
    "SUCCEEDED","BLOCKED","WAITING_FOR_REVIEW","REPAIRING","CANCEL_REQUESTED",
    "RECONCILING","FAILED","CANCELLED","ROLLED_BACK","RECOVERY_REQUIRED",
}
TERMINAL_RUN_STATES = {"SUCCEEDED","FAILED","CANCELLED","ROLLED_BACK","RECOVERY_REQUIRED"}
ALLOWED_TRANSITIONS = {
    "PLANNED":{"PREFLIGHT","BLOCKED","CANCEL_REQUESTED","FAILED"},
    "PREFLIGHT":{"QUEUED","BLOCKED","CANCEL_REQUESTED","FAILED"},
    "QUEUED":{"RUNNING","BLOCKED","CANCEL_REQUESTED","FAILED","RECOVERY_REQUIRED"},
    "RUNNING":{"VALIDATING","WAITING_FOR_REVIEW","REPAIRING","RECONCILING","CANCEL_REQUESTED","BLOCKED","FAILED","RECOVERY_REQUIRED"},
    "VALIDATING":{"STAGING","SUCCEEDED","WAITING_FOR_REVIEW","REPAIRING","FAILED","RECOVERY_REQUIRED"},
    "STAGING":{"PUBLISHING","FAILED","CANCEL_REQUESTED","RECOVERY_REQUIRED"},
    "PUBLISHING":{"SUCCEEDED","FAILED","RECOVERY_REQUIRED"},
    "WAITING_FOR_REVIEW":{"PREFLIGHT","CANCEL_REQUESTED","FAILED"},
    "REPAIRING":{"PREFLIGHT","VALIDATING","RECOVERY_REQUIRED","FAILED"},
    "CANCEL_REQUESTED":{"CANCELLED","RECONCILING","RECOVERY_REQUIRED"},
    "RECONCILING":{"PREFLIGHT","RUNNING","FAILED","RECOVERY_REQUIRED","CANCELLED"},
    "BLOCKED":{"PREFLIGHT","CANCELLED","FAILED"},
}


def _now() -> float:
    return time.time()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def make_run_id() -> str:
    return "run_" + uuid.uuid4().hex


def scoped_idempotency_key(device_id: str, session_id: str, key: str) -> str:
    return _hash({"device_id":device_id or "", "session_id":session_id or "", "key":key or ""})


class WorkflowDomainJournal:
    """Tunnel-owned durable domain journal for ArcMap workflows.

    The class deliberately does not schedule GIS work. Existing Tunnel task scheduling
    remains authoritative; this store only tracks workflow-domain intent/evidence.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        self._migrate()

    def close(self):
        with self._lock:
            self.conn.close()

    def _migrate(self):
        ddl = [
            """CREATE TABLE IF NOT EXISTS workflow_runs(
                run_id TEXT PRIMARY KEY,
                owner_session_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                operator_alias TEXT,
                plan_id TEXT NOT NULL,
                plan_hash TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                idempotency_scope TEXT NOT NULL UNIQUE,
                strategy TEXT,
                state TEXT NOT NULL,
                task_id TEXT,
                request_id TEXT,
                trace_id TEXT,
                document_revision TEXT,
                resource_set_json TEXT NOT NULL DEFAULT '[]',
                blockers_json TEXT NOT NULL DEFAULT '[]',
                budget_json TEXT NOT NULL DEFAULT '{}',
                repair_count INTEGER NOT NULL DEFAULT 0,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                finished_at REAL
            )""",
            """CREATE TABLE IF NOT EXISTS workflow_plans(
                run_id TEXT PRIMARY KEY REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
                plan_json TEXT NOT NULL,
                plan_hash TEXT NOT NULL,
                created_at REAL NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS workflow_steps(
                run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
                step_id TEXT NOT NULL,
                action TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                state TEXT NOT NULL,
                request_id TEXT,
                task_id TEXT,
                result_json TEXT,
                error_json TEXT,
                claimed_at REAL,
                started_at REAL,
                finished_at REAL,
                updated_at REAL NOT NULL,
                PRIMARY KEY(run_id,step_id)
            )""",
            """CREATE TABLE IF NOT EXISTS operation_receipts(
                receipt_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
                step_id TEXT,
                request_id TEXT NOT NULL,
                effect_class TEXT NOT NULL,
                outcome TEXT NOT NULL,
                effect_hash TEXT,
                result_json TEXT,
                acknowledged INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                acknowledged_at REAL
            )""",
            """CREATE TABLE IF NOT EXISTS checkpoints(
                checkpoint_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
                coverage_json TEXT NOT NULL,
                fingerprint TEXT,
                owner_session_id TEXT NOT NULL,
                document_revision TEXT,
                created_at REAL NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS validations(
                validation_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
                phase TEXT NOT NULL,
                status TEXT NOT NULL,
                summary_json TEXT NOT NULL,
                created_at REAL NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS artifacts(
                artifact_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
                kind TEXT NOT NULL,
                stage TEXT NOT NULL,
                path TEXT,
                content_hash TEXT,
                valid INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS publish_attempts(
                attempt_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
                artifact_id TEXT,
                target_path TEXT NOT NULL,
                state TEXT NOT NULL,
                backup_path TEXT,
                error_json TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS workflow_fences(
                resource_key TEXT PRIMARY KEY,
                epoch INTEGER NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS workflow_leases(
                resource_key TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                owner_session_id TEXT NOT NULL,
                fencing_epoch INTEGER NOT NULL,
                expires_at REAL NOT NULL,
                isolated INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )""",
        ]
        with self._lock:
            for sql in ddl:
                self.conn.execute(sql)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_runs_owner ON workflow_runs(owner_session_id, created_at)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_workflow_steps_state ON workflow_steps(run_id,state)")
            self.conn.commit()

    def submit_run(self, *, owner_session_id: str, device_id: str, operator_alias: str,
                   plan: dict[str, Any], idempotency_key: str, request_id: str = "",
                   trace_id: str = "", document_revision: Any = None) -> tuple[dict[str, Any], bool]:
        if not owner_session_id or not device_id:
            raise ValueError("OWNER_REQUIRED")
        plan_hash = str(plan.get("plan_hash") or "")
        plan_id = str(plan.get("plan_id") or "")
        if not plan_hash or not plan_id:
            raise ValueError("PLAN_ID_HASH_REQUIRED")
        input_hash = _hash({"plan_hash":plan_hash,"goal":plan.get("goal"),"context_fingerprint":plan.get("context_fingerprint")})
        scope = scoped_idempotency_key(device_id, owner_session_id, idempotency_key or plan_hash)
        stamp = _now()
        with self._lock:
            existing = self.conn.execute("SELECT * FROM workflow_runs WHERE idempotency_scope=?", (scope,)).fetchone()
            if existing:
                row = dict(existing)
                if row["input_hash"] != input_hash or row["plan_hash"] != plan_hash:
                    raise ValueError("IDEMPOTENCY_CONFLICT")
                return row, False
            run_id = make_run_id()
            self.conn.execute("""INSERT INTO workflow_runs(
                run_id,owner_session_id,device_id,operator_alias,plan_id,plan_hash,input_hash,
                idempotency_scope,strategy,state,request_id,trace_id,document_revision,
                resource_set_json,budget_json,created_at,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                run_id,owner_session_id,device_id,operator_alias,plan_id,plan_hash,input_hash,
                scope,str(plan.get("strategy") or ""),"PLANNED",request_id,trace_id,
                _canonical(document_revision) if document_revision is not None else None,
                _canonical(plan.get("resource_set") or []),_canonical((plan.get("goal") or {}).get("budget") or {}),
                stamp,stamp,
            ))
            self.conn.execute("INSERT INTO workflow_plans(run_id,plan_json,plan_hash,created_at) VALUES(?,?,?,?)",
                              (run_id,_canonical(plan),plan_hash,stamp))
            for node in plan.get("nodes") or []:
                self.conn.execute("""INSERT INTO workflow_steps(run_id,step_id,action,input_hash,state,updated_at)
                    VALUES(?,?,?,?,?,?)""", (
                    run_id,str(node.get("step_id")),str(node.get("action")),
                    _hash(node.get("arguments") or {}),"PENDING",stamp,
                ))
            self.conn.commit()
            return self.get_run(run_id, owner_session_id=owner_session_id), True

    def get_run(self, run_id: str, owner_session_id: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM workflow_runs WHERE run_id=?", (run_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            if owner_session_id is not None and data["owner_session_id"] != owner_session_id:
                raise PermissionError("WRONG_OWNER")
            for key in ("resource_set_json","blockers_json","budget_json"):
                data[key[:-5]] = json.loads(data.get(key) or "[]" if key != "budget_json" else data.get(key) or "{}")
            return data

    def get_plan(self, run_id: str, owner_session_id: str | None = None) -> dict[str, Any]:
        self.get_run(run_id, owner_session_id=owner_session_id)
        with self._lock:
            row = self.conn.execute("SELECT plan_json FROM workflow_plans WHERE run_id=?", (run_id,)).fetchone()
            if not row:
                raise KeyError("PLAN_NOT_FOUND")
            return json.loads(row["plan_json"])

    def transition(self, run_id: str, to_state: str, *, owner_session_id: str | None = None,
                   expected: set[str] | None = None, blockers: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        if to_state not in RUN_STATES:
            raise ValueError("INVALID_RUN_STATE")
        row = self.get_run(run_id, owner_session_id)
        if not row:
            raise KeyError("RUN_NOT_FOUND")
        current = row["state"]
        allowed = ALLOWED_TRANSITIONS.get(current, set())
        if expected is not None and current not in expected:
            raise ValueError("STATE_CONFLICT")
        if current != to_state and to_state not in allowed:
            raise ValueError("INVALID_STATE_TRANSITION")
        stamp = _now()
        finished = stamp if to_state in TERMINAL_RUN_STATES else None
        with self._lock:
            self.conn.execute("UPDATE workflow_runs SET state=?,blockers_json=COALESCE(?,blockers_json),updated_at=?,finished_at=COALESCE(?,finished_at) WHERE run_id=?",
                              (to_state,_canonical(blockers) if blockers is not None else None,stamp,finished,run_id))
            self.conn.commit()
        return self.get_run(run_id, owner_session_id)

    def bind_task(self, run_id: str, task_id: str, owner_session_id: str):
        self.get_run(run_id, owner_session_id)
        with self._lock:
            self.conn.execute("UPDATE workflow_runs SET task_id=?,updated_at=? WHERE run_id=?", (task_id,_now(),run_id))
            self.conn.commit()

    def step_intent(self, run_id: str, step_id: str, request_id: str, input_payload: Any, owner_session_id: str):
        self.get_run(run_id, owner_session_id)
        input_hash = _hash(input_payload)
        with self._lock:
            row = self.conn.execute("SELECT input_hash,state FROM workflow_steps WHERE run_id=? AND step_id=?",(run_id,step_id)).fetchone()
            if not row:
                raise KeyError("STEP_NOT_FOUND")
            existing = str(row["input_hash"])
            if existing and existing != input_hash and row["state"] not in ("PENDING","INVALIDATED"):
                raise ValueError("STEP_INPUT_CONFLICT")
            self.conn.execute("UPDATE workflow_steps SET input_hash=?,request_id=?,state='INTENT_RECORDED',updated_at=? WHERE run_id=? AND step_id=?",
                              (input_hash,request_id,_now(),run_id,step_id))
            self.conn.commit()
        return input_hash

    def step_result(self, run_id: str, step_id: str, *, owner_session_id: str, outcome: str,
                    result: Any = None, error: Any = None, request_id: str = ""):
        self.get_run(run_id, owner_session_id)
        state = "SUCCEEDED" if outcome == "SUCCEEDED" else ("OUTCOME_UNKNOWN" if outcome == "OUTCOME_UNKNOWN" else "FAILED")
        stamp = _now()
        with self._lock:
            self.conn.execute("""UPDATE workflow_steps SET state=?,request_id=COALESCE(NULLIF(?,''),request_id),
                result_json=?,error_json=?,finished_at=?,updated_at=? WHERE run_id=? AND step_id=?""",
                (state,request_id,_canonical(result) if result is not None else None,_canonical(error) if error is not None else None,
                 stamp,stamp,run_id,step_id))
            self.conn.commit()

    def mark_step_state(self, run_id: str, step_id: str, *, owner_session_id: str,
                        state: str, result: Any = None, task_id: str = ""):
        self.get_run(run_id, owner_session_id)
        stamp = _now()
        with self._lock:
            cur = self.conn.execute(
                """UPDATE workflow_steps
                   SET state=?,task_id=COALESCE(NULLIF(?,''),task_id),
                       result_json=?,finished_at=?,updated_at=?
                   WHERE run_id=? AND step_id=?""",
                (
                    str(state),
                    str(task_id or ""),
                    _canonical(result) if result is not None else None,
                    stamp if state in {"SUCCEEDED","FAILED","SKIPPED_DRY_RUN"} else None,
                    stamp,
                    run_id,
                    step_id,
                ),
            )
            if cur.rowcount != 1:
                raise KeyError("STEP_NOT_FOUND")
            self.conn.commit()

    def record_receipt(self, *, run_id: str, step_id: str, request_id: str, effect_class: str,
                       outcome: str, result: Any = None, effect_hash: str | None = None) -> str:
        receipt_id = "rcpt_" + uuid.uuid4().hex
        with self._lock:
            self.conn.execute("""INSERT INTO operation_receipts(
                receipt_id,run_id,step_id,request_id,effect_class,outcome,effect_hash,result_json,created_at
            ) VALUES(?,?,?,?,?,?,?,?,?)""", (
                receipt_id,run_id,step_id,request_id,effect_class,outcome,effect_hash,
                _canonical(result) if result is not None else None,_now()
            ))
            self.conn.commit()
        return receipt_id

    def acknowledge_receipt(self, receipt_id: str):
        with self._lock:
            cur = self.conn.execute("UPDATE operation_receipts SET acknowledged=1,acknowledged_at=? WHERE receipt_id=?",
                                    (_now(),receipt_id))
            if cur.rowcount != 1:
                raise KeyError("RECEIPT_NOT_FOUND")
            self.conn.commit()

    def request_cancel(self, run_id: str, owner_session_id: str) -> dict[str, Any]:
        row = self.get_run(run_id, owner_session_id)
        if row["state"] in TERMINAL_RUN_STATES:
            return row
        stamp = _now()
        with self._lock:
            self.conn.execute("UPDATE workflow_runs SET cancel_requested=1,updated_at=? WHERE run_id=?",(stamp,run_id))
            self.conn.commit()
        if row["state"] != "CANCEL_REQUESTED":
            try:
                return self.transition(run_id,"CANCEL_REQUESTED",owner_session_id=owner_session_id)
            except ValueError:
                return self.get_run(run_id,owner_session_id)
        return self.get_run(run_id,owner_session_id)

    def add_checkpoint(self, run_id: str, owner_session_id: str, coverage: dict[str, Any],
                       fingerprint: str | None, document_revision: Any = None) -> str:
        self.get_run(run_id, owner_session_id)
        checkpoint_id = "cp_" + uuid.uuid4().hex
        with self._lock:
            self.conn.execute("INSERT INTO checkpoints VALUES(?,?,?,?,?,?,?)",(
                checkpoint_id,run_id,_canonical(coverage),fingerprint,owner_session_id,
                _canonical(document_revision) if document_revision is not None else None,_now()
            ))
            self.conn.commit()
        return checkpoint_id

    def add_validation(self, run_id: str, phase: str, status: str, summary: Any) -> str:
        vid="val_"+uuid.uuid4().hex
        with self._lock:
            self.conn.execute("INSERT INTO validations VALUES(?,?,?,?,?,?)",(vid,run_id,phase,status,_canonical(summary),_now()))
            self.conn.commit()
        return vid

    def add_artifact(self, run_id: str, kind: str, stage: str, path: str | None,
                     content_hash: str | None, valid: bool, metadata: Any = None) -> str:
        aid="art_"+uuid.uuid4().hex
        with self._lock:
            self.conn.execute("INSERT INTO artifacts VALUES(?,?,?,?,?,?,?,?,?)",(
                aid,run_id,kind,stage,path,content_hash,1 if valid else 0,_canonical(metadata or {}),_now()
            ))
            self.conn.commit()
        return aid

    def acquire_lease(self, resource_key: str, run_id: str, owner_session_id: str, ttl_seconds: float = 30.0) -> dict[str, Any]:
        stamp=_now()
        with self._lock:
            existing=self.conn.execute("SELECT * FROM workflow_leases WHERE resource_key=?",(resource_key,)).fetchone()
            if existing:
                row=dict(existing)
                if row["run_id"] == run_id and row["owner_session_id"] == owner_session_id:
                    self.conn.execute("UPDATE workflow_leases SET expires_at=?,updated_at=? WHERE resource_key=?",
                                      (stamp+ttl_seconds,stamp,resource_key))
                    self.conn.commit()
                    row["expires_at"]=stamp+ttl_seconds
                    return row
                # Expiry alone never authorizes takeover. Explicit release/isolation is required.
                raise RuntimeError("LOCK_CONFLICT")
            fence=self.conn.execute("SELECT epoch FROM workflow_fences WHERE resource_key=?",(resource_key,)).fetchone()
            epoch=(int(fence["epoch"]) if fence else 0)+1
            self.conn.execute("INSERT INTO workflow_fences(resource_key,epoch) VALUES(?,?) ON CONFLICT(resource_key) DO UPDATE SET epoch=excluded.epoch",
                              (resource_key,epoch))
            self.conn.execute("INSERT INTO workflow_leases VALUES(?,?,?,?,?,?,?,?)",(
                resource_key,run_id,owner_session_id,epoch,stamp+ttl_seconds,0,stamp,stamp
            ))
            self.conn.commit()
            return {"resource_key":resource_key,"run_id":run_id,"owner_session_id":owner_session_id,
                    "fencing_epoch":epoch,"expires_at":stamp+ttl_seconds,"isolated":0}

    def release_lease(self, resource_key: str, run_id: str, owner_session_id: str):
        with self._lock:
            row=self.conn.execute("SELECT * FROM workflow_leases WHERE resource_key=?",(resource_key,)).fetchone()
            if not row:
                return
            if row["run_id"] != run_id or row["owner_session_id"] != owner_session_id:
                raise PermissionError("WRONG_LEASE_OWNER")
            self.conn.execute("DELETE FROM workflow_leases WHERE resource_key=?",(resource_key,))
            self.conn.commit()

    def list_run_steps(self, run_id: str, owner_session_id: str) -> list[dict[str, Any]]:
        self.get_run(run_id, owner_session_id)
        with self._lock:
            rows=self.conn.execute("SELECT * FROM workflow_steps WHERE run_id=? ORDER BY rowid",(run_id,)).fetchall()
            return [dict(r) for r in rows]

    def record_publish_attempt(self, attempt: dict[str, Any]) -> None:
        stamp=_now()
        with self._lock:
            existing=self.conn.execute("SELECT attempt_id FROM publish_attempts WHERE attempt_id=?",
                                       (attempt["attempt_id"],)).fetchone()
            if existing:
                self.conn.execute("""UPDATE publish_attempts SET state=?,backup_path=?,error_json=?,updated_at=?
                    WHERE attempt_id=?""", (
                    str(attempt.get("state") or ""),
                    attempt.get("backup"),
                    _canonical(attempt.get("error")) if attempt.get("error") is not None else None,
                    stamp,attempt["attempt_id"]
                ))
            else:
                self.conn.execute("""INSERT INTO publish_attempts(
                    attempt_id,run_id,artifact_id,target_path,state,backup_path,error_json,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?)""", (
                    attempt["attempt_id"],attempt["run_id"],attempt.get("artifact_id"),
                    str(attempt.get("target") or ""),str(attempt.get("state") or ""),
                    attempt.get("backup"),
                    _canonical(attempt.get("error")) if attempt.get("error") is not None else None,
                    stamp,stamp
                ))
            self.conn.commit()

    def recover_incomplete_runs(self) -> list[str]:
        """Recover after control-plane restart without replaying effects.

        Runs that may have crossed an effect boundary are moved to RECONCILING.
        Purely queued/planned runs remain durable and may be rescheduled by an
        explicit owner-aware recovery controller.
        """
        ambiguous={"RUNNING","VALIDATING","STAGING","PUBLISHING","CANCEL_REQUESTED","REPAIRING"}
        recovered=[]
        stamp=_now()
        with self._lock:
            rows=self.conn.execute("SELECT run_id,state FROM workflow_runs").fetchall()
            for row in rows:
                if row["state"] in ambiguous:
                    self.conn.execute("UPDATE workflow_runs SET state='RECONCILING',updated_at=? WHERE run_id=?",
                                      (stamp,row["run_id"]))
                    recovered.append(str(row["run_id"]))
            self.conn.commit()
        return recovered

    def list_runs(self, owner_session_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows=self.conn.execute("""SELECT * FROM workflow_runs
                WHERE owner_session_id=? ORDER BY created_at DESC LIMIT ?""",
                (owner_session_id,max(1,int(limit)))).fetchall()
            return [dict(r) for r in rows]

    def workflow_summary(self, owner_session_id: str, limit: int = 100) -> dict[str, Any]:
        rows=self.list_runs(owner_session_id,limit)
        return {
            "ok":True,
            "session_id":owner_session_id,
            "count":len(rows),
            "runs":[{
                "run_id":r["run_id"],
                "plan_id":r["plan_id"],
                "state":r["state"],
                "strategy":r.get("strategy"),
                "task_id":r.get("task_id"),
                "request_id":r.get("request_id"),
                "trace_id":r.get("trace_id"),
                "repair_count":r.get("repair_count",0),
                "cancel_requested":bool(r.get("cancel_requested")),
                "created_at":r.get("created_at"),
                "updated_at":r.get("updated_at"),
                "finished_at":r.get("finished_at"),
            } for r in rows],
        }

    def report(self, run_id: str, owner_session_id: str) -> dict[str, Any]:
        run=self.get_run(run_id,owner_session_id)
        with self._lock:
            steps=[dict(r) for r in self.conn.execute("SELECT * FROM workflow_steps WHERE run_id=? ORDER BY rowid",(run_id,)).fetchall()]
            validations=[dict(r) for r in self.conn.execute("SELECT * FROM validations WHERE run_id=? ORDER BY created_at",(run_id,)).fetchall()]
            artifacts=[dict(r) for r in self.conn.execute("SELECT * FROM artifacts WHERE run_id=? ORDER BY created_at",(run_id,)).fetchall()]
            receipts=[dict(r) for r in self.conn.execute("SELECT * FROM operation_receipts WHERE run_id=? ORDER BY created_at",(run_id,)).fetchall()]
            publishes=[dict(r) for r in self.conn.execute("SELECT * FROM publish_attempts WHERE run_id=? ORDER BY created_at",(run_id,)).fetchall()]
        return {"run":run,"steps":steps,"validations":validations,"artifacts":artifacts,
                "receipts":receipts,"publish_attempts":publishes}
