from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path
from typing import Any

from .workflow_domain import TERMINAL_RUN_STATES, WorkflowDomainJournal
from .workflow_executor import ConcreteWorkflowExecutor
from .config import load_tunnel_config
from orchestrator.compiler import validate_compiled_plan
from orchestrator.reporting import (
    build_run_report,
    build_timeline,
    evidence_view,
)


_TASK_TO_RUN = {
    "accepted": "QUEUED",
    "queued": "QUEUED",
    "waiting_capacity": "QUEUED",
    "waiting_lock": "QUEUED",
    "running": "RUNNING",
    "cancelling": "CANCEL_REQUESTED",
    "cancelled": "CANCELLED",
    "failed": "FAILED",
    "orphaned": "RECOVERY_REQUIRED",
}


class WorkflowRuntimeService:
    """Tunnel-owned durable workflow facade.

    Dry-run plans are scheduled through the real Tunnel queue using the ArcMap
    goal validator. Non-dry-run plans remain fail-closed until the concrete
    strategy runner is wired; they are never reported as successful.
    """

    def __init__(
        self,
        journal: WorkflowDomainJournal,
        orchestrator,
        *,
        service_id: str = "zagent_arcmap",
        device_id: str = "",
    ):
        self.journal = journal
        self.orchestrator = orchestrator
        self.service_id = service_id
        self.device_id = str(device_id or "")
        workspace_root = os.environ.get(
            "ZAGENT_WORKFLOW_WORKSPACE_ROOT",
            str(Path(os.environ.get(
                "ZAGENT_TUNNEL_RUNTIME_DIR",
                str(Path.cwd() / "runtime"))) / "workflow-runs"),
        )
        self.concrete = ConcreteWorkflowExecutor(
            journal,
            workspace_root,
        )

    def _assert_owner(self, owner: dict[str, Any]) -> tuple[str, str]:
        session_id = str((owner or {}).get("session_id") or "")
        device_id = str((owner or {}).get("device_id") or "").lower()
        from .access import owner_key
        context = (owner or {}).get("execution_context") or {}
        principal = str(context.get("principal_id") or "")
        workspace = str(context.get("workspace_id") or "")
        if (not principal or not workspace or context.get("context_version") != 1
                or session_id != owner_key(principal, workspace) or not device_id
                or context.get("device_id") != device_id
                or float(context.get("deadline") or 0) <= time.time()):
            raise PermissionError("ACCESS_DENIED")
        if self.device_id and device_id != self.device_id.lower():
            raise PermissionError("ACCESS_DENIED")
        return session_id, device_id

    async def submit(
        self,
        *,
        plan: dict[str, Any],
        owner: dict[str, Any],
        idempotency_key: str = "",
        priority: int = 1,
    ) -> dict[str, Any]:
        try:
            session_id, device_id = self._assert_owner(owner)
        except PermissionError:
            return {
                "ok": False,
                "status": "FAILED",
                "errors": [{"code": "ACCESS_DENIED"}],
            }

        if not isinstance(plan, dict) or not plan.get("plan_hash") or not plan.get("plan_id"):
            return {
                "ok": False,
                "status": "INVALID",
                "errors": [{"code": "PLAN_REQUIRED"}],
            }
        errors = validate_compiled_plan(plan)
        if errors:
            return {"ok": False, "status": "INVALID", "errors": errors}
        if plan.get("blockers"):
            return {
                "ok": False,
                "status": "BLOCKED",
                "errors": list(plan.get("blockers") or []),
            }

        dry_run = bool((plan.get("goal") or {}).get("dry_run"))
        if not dry_run:
            policy = load_tunnel_config().get("workflow_policy") or {}
            if str(plan.get("strategy") or "") not in policy.get("allowed_strategies", []):
                return {"ok": False, "status": "BLOCKED", "errors": [{"code": "STRATEGY_NOT_PROVISIONED"}]}
        key = str(idempotency_key or plan.get("plan_hash") or "")
        try:
            run, created = self.journal.submit_run(
                owner_session_id=session_id,
                device_id=device_id,
                operator_alias="",
                plan=plan,
                idempotency_key=key,
                request_id=str(owner.get("request_id") or ""),
                trace_id=str(owner.get("trace_id") or ""),
                document_revision=plan.get("target_revision"),
            )
        except ValueError as exc:
            return {
                "ok": False,
                "status": "FAILED",
                "errors": [{"code": str(exc)}],
            }

        if not created:
            await self._sync(run["run_id"], session_id)
            row = self.journal.get_run(run["run_id"], session_id)
            return {
                "ok": True,
                "status": row["state"],
                "run_id": row["run_id"],
                "task_id": row.get("task_id"),
                "duplicate": True,
            }

        strategy = str(plan.get("strategy") or "")
        if not dry_run and strategy not in {
            "A_EXISTING_MXD",
            "D_CURRENT_MXD_IN_PLACE_CARTOGRAPHY",
            "B_TEMPLATE_DATA",
            "C_BLANK_DATA",
        }:
            blocked = [{
                "code": "EXECUTION_ADAPTER_NOT_READY",
                "message": (
                    "Concrete non-dry-run execution is currently enabled for "
                    "Strategy B/C. Strategy A requires the live-MXD adapter."
                ),
            }]
            self.journal.transition(
                run["run_id"],
                "BLOCKED",
                owner_session_id=session_id,
                blockers=blocked,
            )
            return {
                "ok": False,
                "status": "BLOCKED",
                "run_id": run["run_id"],
                "task_id": None,
                "errors": blocked,
            }

        self.journal.transition(
            run["run_id"], "PREFLIGHT", owner_session_id=session_id
        )
        self.journal.transition(
            run["run_id"], "QUEUED", owner_session_id=session_id
        )

        meta = {
            "execution_context": dict(owner["execution_context"]),
            "task_id": "tsk_" + uuid.uuid4().hex,
            "session_id": session_id,
            "device_id": device_id,
            "target_device_id": device_id,
            "executed_on": device_id,

            "request_id": str(owner.get("request_id") or ""),
            "trace_id": str(owner.get("trace_id") or ""),
            "idempotency_key": "workflow:" + run["run_id"],
            "resource_key": owner["execution_context"]["effective_resources"][0]["resource_id"],
            "access_mode": "write",
            "priority": 2,
        }
        meta["execution_context"]["task_id"] = meta["task_id"]
        meta["execution_context"]["run_id"] = run["run_id"]
        try:
            if dry_run:
                scheduled = await self.orchestrator.submit(
                    self.service_id,
                    "arcmap_goal_validate",
                    {"plan": plan},
                    meta,
                )
            else:
                scheduled = await self.orchestrator.submit(
                    "__workflow__",
                    "arcmap_orchestrator_execute",
                    {
                        "run_id": run["run_id"],
                        "owner_session_id": session_id,
                        "plan": plan,
                    },
                    meta,
                )
        except Exception as exc:
            self.journal.transition(
                run["run_id"],
                "RECOVERY_REQUIRED",
                owner_session_id=session_id,
            )
            return {
                "ok": False,
                "status": "RECOVERY_REQUIRED",
                "run_id": run["run_id"],
                "errors": [{
                    "code": "SCHEDULER_SUBMIT_FAILED",
                    "message": str(exc),
                }],
            }

        task_id = str(scheduled.get("task_id") or "")
        if not task_id:
            self.journal.transition(
                run["run_id"],
                "RECOVERY_REQUIRED",
                owner_session_id=session_id,
            )
            return {
                "ok": False,
                "status": "RECOVERY_REQUIRED",
                "run_id": run["run_id"],
                "errors": [{"code": "SCHEDULER_TASK_ID_MISSING"}],
            }
        self.journal.bind_task(run["run_id"], task_id, session_id)
        return {
            "ok": True,
            "status": "QUEUED",
            "run_id": run["run_id"],
            "task_id": task_id,
            "duplicate": False,
        }

    async def execute_internal(self, tool_name: str, arguments: dict[str, Any], ctx) -> dict[str, Any]:
        if tool_name != "arcmap_orchestrator_execute":
            raise ValueError("UNKNOWN_INTERNAL_WORKFLOW_TOOL")
        run_id = str((arguments or {}).get("run_id") or "")
        owner_session_id = str((arguments or {}).get("owner_session_id") or "")
        if owner_session_id != str(getattr(ctx, "session_id", "")):
            raise PermissionError("ACCESS_DENIED")
        plan = (arguments or {}).get("plan") or {}
        if not run_id or not owner_session_id:
            raise ValueError("RUN_CONTEXT_REQUIRED")
        task_id = str(getattr(ctx, "task_id", "") or "")
        strategy = str(plan.get("strategy") or "")
        if strategy == "A_EXISTING_MXD":
            return await asyncio.to_thread(
                self.concrete.execute_a,
                run_id=run_id,
                owner_session_id=owner_session_id,
                plan=plan,
                task_id=task_id,
            )
        if strategy == "D_CURRENT_MXD_IN_PLACE_CARTOGRAPHY":
            return await asyncio.to_thread(
                self.concrete.execute_d,
                run_id=run_id,
                owner_session_id=owner_session_id,
                plan=plan,
                task_id=task_id,
            )
        if strategy in {"B_TEMPLATE_DATA", "C_BLANK_DATA"}:
            return await asyncio.to_thread(
                self.concrete.execute_bc,
                run_id=run_id,
                owner_session_id=owner_session_id,
                plan=plan,
                task_id=task_id,
            )
        return {
            "ok": False,
            "status": "BLOCKED",
            "errors": [{"code": "EXECUTION_ADAPTER_NOT_READY"}],
        }

    async def _sync(self, run_id: str, owner_session_id: str) -> dict[str, Any]:
        row = self.journal.get_run(run_id, owner_session_id)
        if not row:
            raise KeyError("RUN_NOT_FOUND")
        if row["state"] in TERMINAL_RUN_STATES or row["state"] in {"BLOCKED", "WAITING_FOR_REVIEW"}:
            return row
        task_id = str(row.get("task_id") or "")
        if not task_id:
            return row
        status = await self.orchestrator.status(task_id)
        task = (status or {}).get("task") or {}
        task_state = str(task.get("state") or "")
        desired = _TASK_TO_RUN.get(task_state)

        current = row["state"]
        try:
            if desired == "RUNNING" and current == "QUEUED":
                row = self.journal.transition(
                    run_id, "RUNNING", owner_session_id=owner_session_id
                )
            elif task_state == "succeeded":
                plan = self.journal.get_plan(run_id, owner_session_id)
                is_dry = bool((plan.get("goal") or {}).get("dry_run"))
                if not is_dry:
                    row = self.journal.get_run(run_id, owner_session_id)
                    if row["state"] in {"QUEUED", "RUNNING"}:
                        try:
                            row = self.journal.transition(
                                run_id,
                                "RECOVERY_REQUIRED",
                                owner_session_id=owner_session_id,
                            )
                        except ValueError:
                            row = self.journal.get_run(
                                run_id, owner_session_id
                            )
                    return row
                # Dry-run worker only validates the canonical plan. That is a
                # complete dry-run execution; no GIS/file publish phase occurs.
                # If cancel intent won the race but the short validator already
                # completed, quarantine the late result and close CANCELLED.
                # Never leave CANCEL_REQUESTED stuck and never rewrite it as
                # SUCCEEDED after an accepted cancel intent.
                if (
                    current in {"CANCEL_REQUESTED", "RECONCILING"}
                    and bool(row.get("cancel_requested"))
                ):
                    selected = set(plan.get("dry_run_nodes") or [])
                    for node in plan.get("nodes") or []:
                        step_id = str(node.get("step_id") or "")
                        if not step_id:
                            continue
                        step_state = (
                            "SUCCEEDED"
                            if step_id in selected
                            else "SKIPPED_DRY_RUN"
                        )
                        self.journal.mark_step_state(
                            run_id,
                            step_id,
                            owner_session_id=owner_session_id,
                            state=step_state,
                            task_id=task_id,
                            result={
                                "mode": "dry_run",
                                "validated_by_task": task_id,
                                "selected": step_id in selected,
                                "late_result_quarantined": True,
                            },
                        )
                    self.journal.add_validation(
                        run_id,
                        "dry_run_cancel_race",
                        "PASS",
                        {
                            "task_id": task_id,
                            "worker_state": task_state,
                            "late_result_quarantined": True,
                            "selected_steps": sorted(selected),
                        },
                    )
                    return self.journal.transition(
                        run_id,
                        "CANCELLED",
                        owner_session_id=owner_session_id,
                    )
                if current == "QUEUED":
                    self.journal.transition(
                        run_id, "RUNNING", owner_session_id=owner_session_id
                    )
                current = self.journal.get_run(run_id, owner_session_id)["state"]
                if current == "RUNNING":
                    self.journal.transition(
                        run_id, "VALIDATING", owner_session_id=owner_session_id
                    )
                selected = set(plan.get("dry_run_nodes") or [])
                for node in plan.get("nodes") or []:
                    step_id = str(node.get("step_id") or "")
                    if not step_id:
                        continue
                    step_state = (
                        "SUCCEEDED"
                        if step_id in selected
                        else "SKIPPED_DRY_RUN"
                    )
                    self.journal.mark_step_state(
                        run_id,
                        step_id,
                        owner_session_id=owner_session_id,
                        state=step_state,
                        task_id=task_id,
                        result={
                            "mode": "dry_run",
                            "validated_by_task": task_id,
                            "selected": step_id in selected,
                        },
                    )
                row = self.journal.transition(
                    run_id, "SUCCEEDED", owner_session_id=owner_session_id
                )
                self.journal.add_validation(
                    run_id,
                    "dry_run_plan_validation",
                    "PASS",
                    {
                        "task_id": task_id,
                        "worker_state": task_state,
                        "plan_hash": row.get("plan_hash"),
                        "selected_steps": sorted(selected),
                    },
                )
            elif desired == "RECOVERY_REQUIRED" and current not in TERMINAL_RUN_STATES:
                row = self.journal.transition(run_id, "RECOVERY_REQUIRED", owner_session_id=owner_session_id)
            elif desired == "FAILED" and current not in TERMINAL_RUN_STATES:
                row = self.journal.transition(
                    run_id, "FAILED", owner_session_id=owner_session_id
                )
            elif desired == "CANCELLED":
                if current != "CANCEL_REQUESTED":
                    try:
                        self.journal.request_cancel(run_id, owner_session_id)
                    except Exception:
                        pass
                row = self.journal.transition(
                    run_id, "CANCELLED", owner_session_id=owner_session_id
                )
            elif desired == "CANCEL_REQUESTED" and current not in TERMINAL_RUN_STATES:
                try:
                    row = self.journal.request_cancel(run_id, owner_session_id)
                except Exception:
                    row = self.journal.get_run(run_id, owner_session_id)
        except ValueError:
            row = self.journal.get_run(run_id, owner_session_id)
        return row

    async def summary(
        self,
        owner_session_id: str,
        limit: int = 100,
    ) -> dict[str, Any]:
        rows = self.journal.list_runs(owner_session_id, limit)
        for row in rows:
            try:
                await self._sync(row["run_id"], owner_session_id)
            except Exception:
                # Read model stays available even if one run needs recovery.
                pass
        return self.journal.workflow_summary(owner_session_id, limit)

    async def status(self, run_id: str, owner_session_id: str) -> dict[str, Any]:
        try:
            row = await self._sync(run_id, owner_session_id)
        except PermissionError:
            return {"ok": False, "status": "FAILED", "errors": [{"code": "ACCESS_DENIED"}]}
        except KeyError:
            return {"ok": False, "status": "FAILED", "errors": [{"code": "RUN_NOT_FOUND"}]}
        steps = self.journal.list_run_steps(run_id, owner_session_id)
        raw_report = self.journal.report(run_id, owner_session_id)
        plan = self.journal.get_plan(run_id, owner_session_id)
        rich_report = build_run_report(
            row,
            plan=plan,
            validations=raw_report.get("validations") or [],
            artifacts=raw_report.get("artifacts") or [],
            repairs=[],
            steps=steps,
        )
        timeline = build_timeline(
            row,
            steps=steps,
            validations=raw_report.get("validations") or [],
            artifacts=raw_report.get("artifacts") or [],
        )
        return {
            "ok": True,
            "status": row["state"],
            "run": row,
            "steps": steps,
            "timeline": timeline,
            "cartographic": rich_report.get("cartographic"),
            "freshness": {
                "observed_at_epoch": time.time(),
                "source": "tunnel_scheduler",
                "task_id": row.get("task_id"),
                "document_revision": row.get("document_revision"),
                "run_updated_at_epoch": row.get("updated_at"),
            },
        }

    async def cancel(self, run_id: str, owner_session_id: str) -> dict[str, Any]:
        try:
            row = self.journal.request_cancel(run_id, owner_session_id)
        except PermissionError:
            return {"ok": False, "status": "FAILED", "errors": [{"code": "ACCESS_DENIED"}]}
        except KeyError:
            return {"ok": False, "status": "FAILED", "errors": [{"code": "RUN_NOT_FOUND"}]}
        task_id = str(row.get("task_id") or "")
        ack = False
        if task_id:
            try:
                result = await self.orchestrator.cancel(task_id)
                ack = bool((result or {}).get("ok", True))
            except Exception:
                ack = False
        return {
            "ok": True,
            "status": row["state"],
            "run_id": run_id,
            "task_id": task_id or None,
            "scheduler_cancel_ack": ack,
        }

    async def resume(
        self,
        run_id: str,
        owner_session_id: str,
        review_decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            row = self.journal.get_run(run_id, owner_session_id)
        except PermissionError:
            return {"ok": False, "status": "FAILED", "errors": [{"code": "ACCESS_DENIED"}]}
        if not row:
            return {"ok": False, "status": "FAILED", "errors": [{"code": "RUN_NOT_FOUND"}]}
        if row["state"] == "RECONCILING":
            return {
                "ok": False,
                "status": "RECONCILING",
                "errors": [{"code": "OUTCOME_UNKNOWN"}],
            }
        if row["state"] == "RECOVERY_REQUIRED":
            return {
                "ok": False,
                "status": "RECOVERY_REQUIRED",
                "errors": [{"code": "RECOVERY_REQUIRED"}],
            }
        if row["state"] != "WAITING_FOR_REVIEW":
            return {
                "ok": False,
                "status": row["state"],
                "errors": [{"code": "RESUME_NOT_ALLOWED"}],
            }
        if not isinstance(review_decision, dict):
            return {
                "ok": False,
                "status": "WAITING_FOR_REVIEW",
                "errors": [{"code": "REVIEW_DECISION_REQUIRED"}],
            }
        row = self.journal.transition(
            run_id, "PREFLIGHT", owner_session_id=owner_session_id
        )
        return {"ok": True, "status": row["state"], "run_id": run_id}

    async def report(self, run_id: str, owner_session_id: str) -> dict[str, Any]:
        status = await self.status(run_id, owner_session_id)
        if not status.get("ok"):
            return status
        try:
            report = self.journal.report(run_id, owner_session_id)
        except PermissionError:
            return {"ok": False, "status": "FAILED", "errors": [{"code": "ACCESS_DENIED"}]}
        plan = self.journal.get_plan(run_id, owner_session_id)
        rich = build_run_report(
            report.get("run") or {},
            plan=plan,
            validations=report.get("validations") or [],
            artifacts=report.get("artifacts") or [],
            repairs=[],
            steps=report.get("steps") or [],
        )
        report["summary"] = rich
        report["cartographic"] = rich.get("cartographic")
        report["timeline"] = build_timeline(
            report.get("run") or {},
            steps=report.get("steps") or [],
            validations=report.get("validations") or [],
            artifacts=report.get("artifacts") or [],
        )
        report["evidence"] = evidence_view(report)
        return {
            "ok": True,
            "status": report["run"]["state"],
            "data": report,
        }
