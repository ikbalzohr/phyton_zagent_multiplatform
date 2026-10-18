import json


def _decode(value, default=None):
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list, int, float, bool)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default if default is not None else value


def _validation_phase(row):
    return str((row or {}).get("phase") or (row or {}).get("name") or "")


def _step_result(steps, step_id):
    for row in steps or []:
        if str((row or {}).get("step_id") or "") == step_id:
            return _decode((row or {}).get("result_json"), {}) or {}
    return {}


def cartographic_evidence(plan=None, validations=None, artifacts=None, steps=None):
    plan=plan or {}
    validations=list(validations or [])
    artifacts=list(artifacts or [])
    steps=list(steps or [])
    strategy=str(plan.get("strategy") or "")
    if strategy!="D_CURRENT_MXD_IN_PLACE_CARTOGRAPHY":
        return None

    visual_cycles=[]
    acceptance=None
    published_acceptance=None
    artifact_gate=None
    for row in validations:
        phase=_validation_phase(row)
        summary=_decode((row or {}).get("summary_json"), {}) or {}
        item={
            "phase":phase,
            "status":(row or {}).get("status"),
            "summary":summary,
            "created_at":(row or {}).get("created_at"),
        }
        if phase.startswith("cartographic_visual_qa_cycle_"):
            visual_cycles.append(item)
        elif phase in ("cartographic_acceptance_pre_save", "cartographic_acceptance"):
            acceptance=item
        elif phase=="cartographic_acceptance_post_publish":
            published_acceptance=item
        elif phase=="artifact_gate":
            artifact_gate=item

    checkpoint=_step_result(steps,"s070")
    compose=_step_result(steps,"s100")
    repair=_step_result(steps,"s160")
    save=_step_result(steps,"s250") or _step_result(steps,"s170")
    final_artifacts=[
        {
            "kind":row.get("kind"),
            "path":row.get("path"),
            "content_hash":row.get("content_hash"),
            "valid":bool(row.get("valid")),
            "metadata":_decode(row.get("metadata_json"), {}) or {},
        }
        for row in artifacts
        if str(row.get("stage") or "").upper()=="FINAL"
    ]
    visual_cycles.sort(key=lambda x: x.get("created_at") or 0)
    return {
        "strategy_mode":"CURRENT_MXD_IN_PLACE",
        "profile":((plan.get("goal") or {}).get("cartographic_profile") or "administration_a4_landscape"),
        "persistent_checkpoint":checkpoint,
        "compose":compose,
        "visual_qa_cycles":visual_cycles,
        "repair":repair,
        "save_in_place":save,
        "artifact_gate":artifact_gate,
        "acceptance":acceptance,
        "published_acceptance":published_acceptance,
        "final_artifacts":final_artifacts,
    }


def build_run_report(run,plan=None,validations=None,repairs=None,artifacts=None,timings=None,steps=None):
    plan=plan or {}
    goal=plan.get("goal") or {}
    vals=list(validations or [])
    arts=list(artifacts or [])
    reps=list(repairs or [])
    step_rows=list(steps or [])
    cartography=cartographic_evidence(plan,vals,arts,step_rows)
    return {
        "schema_version":"2.1",
        "run_id":run.get("run_id"),
        "status":run.get("state") or run.get("status"),
        "goal":{"raw_goal":goal.get("raw_goal"),"interpreted_goal":goal.get("interpreted_goal")},
        "strategy":plan.get("strategy"),
        "data":{"data_root":goal.get("data_root"),"required_layer_roles":goal.get("required_layer_roles") or [],
                "assumptions":plan.get("assumptions") or []},
        "changes":{"save_policy":goal.get("save_policy"),"source_edit_policy":goal.get("source_edit_policy"),
                   "repair_count":run.get("repair_count",len(reps))},
        "validations":vals,
        "repairs":reps,
        "artifacts":arts,
        "cartographic":cartography,
        "rollback":{"status":run.get("rollback_status"),"coverage":run.get("checkpoint_coverage")},
        "timings":timings or {},
        "bottleneck":(timings or {}).get("dominant"),
    }


def to_markdown(report):
    carto=report.get("cartographic") or {}
    acceptance=(carto.get("acceptance") or {}).get("status")
    visual=carto.get("visual_qa_cycles") or []
    lines=[
        "# Zagent ArcMap Run Report",
        "",
        "Run: %s" % (report.get("run_id") or ""),
        "Status: %s" % (report.get("status") or ""),
        "Strategy: %s" % (report.get("strategy") or ""),
        "Goal: %s" % ((report.get("goal") or {}).get("raw_goal") or ""),
        "Artifacts: %d" % len(report.get("artifacts") or []),
        "Validations: %d" % len(report.get("validations") or []),
        "Repairs: %d" % len(report.get("repairs") or []),
    ]
    if carto:
        lines += [
            "Cartographic profile: %s" % (carto.get("profile") or ""),
            "Visual QA cycles: %d" % len(visual),
            "Cartographic acceptance: %s" % (acceptance or "UNKNOWN"),
        ]
    return "\n".join(lines)+"\n"
