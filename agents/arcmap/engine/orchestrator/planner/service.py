from orchestrator.compiler import compile_plan, validate_compiled_plan
from orchestrator.context import collect_live_context

def plan_goal(services, goal):
    context = collect_live_context(services)
    result = compile_plan(goal, context=context)
    if isinstance(result, dict):
        result.setdefault("context", context)
    return result

def validate_plan(plan):
    errors = validate_compiled_plan(plan)
    return {
        "ok": not errors,
        "status": "PLANNED" if not errors else "INVALID",
        "errors": errors,
        "warnings": [],
        "data": {"plan_id": plan.get("plan_id"), "plan_hash": plan.get("plan_hash")} if isinstance(plan, dict) else None,
    }
