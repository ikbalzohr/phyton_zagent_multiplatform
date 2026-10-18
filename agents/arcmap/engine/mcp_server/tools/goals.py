from mcp_server.request_context import current as current_request_context
from orchestrator.planner import plan_goal, validate_plan


def _runtime(s):
    return getattr(s, "goal_runtime", None)


def _owner():
    ctx = current_request_context()
    return {
        "execution_context": {k: v for k, v in ctx.items() if k not in ("session_id", "expires_at", "mcp_receive_epoch", "mcp_tool_name")},
        "session_id": str(ctx.get("session_id") or ""),
        "device_id": str(ctx.get("device_id") or ""),
        "principal_id": str(ctx.get("principal_id") or ""),
        "workspace_id": str(ctx.get("workspace_id") or ""),
        "resource_id": str(ctx.get("resource_id") or ""),
        "operation_id": str(ctx.get("operation_id") or ""),
        "request_id": str(ctx.get("request_id") or ""),
        "trace_id": str(ctx.get("trace_id") or ""),
        "task_id": str(ctx.get("task_id") or ""),
    }


def _runtime_unavailable():
    return {
        "ok": False,
        "status": "BLOCKED",
        "errors": [{
            "code": "DURABLE_RUNTIME_UNAVAILABLE",
            "message": "The durable workflow runtime is not configured for this ArcMap MCP process."
        }],
        "warnings": [],
        "data": None,
    }


def _access_denied():
    return {
        "ok": False,
        "status": "FAILED",
        "errors": [{
            "code": "ACCESS_DENIED",
            "message": "Authenticated principal/workspace/resource metadata is required."
        }],
        "warnings": [],
        "data": None,
    }


def _normalize_goal_intent(goal):
    goal = dict(goal or {})
    persistence = dict(goal.get("persistence") or {})
    in_place_intent = (
        bool(goal.get("work_on_active_mxd"))
        or str(goal.get("source_edit_policy") or "").lower() == "in_place"
        or str(persistence.get("mode") or "").upper() == "CURRENT_MXD_IN_PLACE"
    )
    if in_place_intent:
        goal["target_mode"] = "CURRENT_IN_PLACE"
        goal["source_edit_policy"] = "in_place"
        goal["save_policy"] = "overwrite"
        persistence.setdefault("mode", "CURRENT_MXD_IN_PLACE")
        persistence.setdefault("require_active_document", True)
        persistence.setdefault("require_document_in_project_root", True)
        persistence.setdefault("create_recovery_checkpoint", True)
        persistence.setdefault("save_current_mxd", True)
        persistence.setdefault("create_final_mxd_copy", False)
        goal["persistence"] = persistence
        outputs = dict(goal.get("outputs") or {})
        outputs.setdefault("save_mxd", True)
        outputs.setdefault("output_subdir", "Hasil Peta")
        goal["outputs"] = outputs
    return goal


def register(mcp, s):
    @mcp.tool()
    def arcmap_goal_plan(goal: dict):
        """Build a deterministic ArcMap plan from a structured goal. Read-only against GIS."""
        return plan_goal(s, _normalize_goal_intent(goal))

    @mcp.tool()
    def arcmap_goal_validate(plan: dict):
        """Validate an ArcMap goal plan, capability mapping and canonical plan hash. Read only."""
        return validate_plan(plan)

    @mcp.tool()
    def arcmap_goal_execute(plan: dict, idempotency_key: str = "", priority: int = 1):
        """Submit an already compiled plan to the durable workflow runtime."""
        checked = validate_plan(plan)
        if not checked.get("ok"):
            return checked
        runtime = _runtime(s)
        if runtime is None:
            return _runtime_unavailable()
        owner = _owner()
        if not owner["session_id"] or not owner["device_id"]:
            return _access_denied()
        return runtime.submit(
            plan,
            owner,
            idempotency_key=idempotency_key or None,
            priority=max(0, int(priority)),
        )

    @mcp.tool()
    def arcmap_goal_status(run_id: str):
        """Return one durable workflow run visible to the current owning session."""
        runtime = _runtime(s)
        if runtime is None:
            return _runtime_unavailable()
        owner = _owner()
        if not owner["session_id"]:
            return _access_denied()
        return runtime.status(run_id, owner["session_id"])

    @mcp.tool()
    def arcmap_goal_resume(run_id: str, review_decision: dict | None = None):
        """Resume a blocked/review workflow after durable reconciliation rules allow it."""
        runtime = _runtime(s)
        if runtime is None:
            return _runtime_unavailable()
        owner = _owner()
        if not owner["session_id"]:
            return _access_denied()
        return runtime.resume(run_id, owner["session_id"], review_decision)

    @mcp.tool()
    def arcmap_goal_cancel(run_id: str):
        """Request cooperative cancellation for a durable ArcMap workflow."""
        runtime = _runtime(s)
        if runtime is None:
            return _runtime_unavailable()
        owner = _owner()
        if not owner["session_id"]:
            return _access_denied()
        return runtime.cancel(run_id, owner["session_id"])

    @mcp.tool()
    def arcmap_goal_report(run_id: str):
        """Return durable run evidence, validation, receipts, artifacts and publish attempts."""
        runtime = _runtime(s)
        if runtime is None:
            return _runtime_unavailable()
        owner = _owner()
        if not owner["session_id"]:
            return _access_denied()
        return runtime.report(run_id, owner["session_id"])

    @mcp.tool()
    def arcmap_goal_build_map(goal: dict, dry_run: bool = True,
                              idempotency_key: str = "", priority: int = 1):
        """Plan a map goal; when dry_run is false, submit only through configured durable runtime."""
        goal = _normalize_goal_intent(goal)
        goal["dry_run"] = bool(dry_run)
        planned = plan_goal(s, goal)
        if dry_run or not planned.get("ok"):
            return planned
        runtime = _runtime(s)
        if runtime is None:
            return _runtime_unavailable()
        owner = _owner()
        if not owner["session_id"] or not owner["device_id"]:
            return _access_denied()
        return runtime.submit(
            planned["data"],
            owner,
            idempotency_key=idempotency_key or None,
            priority=max(0, int(priority)),
        )
