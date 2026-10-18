import hashlib
import json
import uuid

from orchestrator.capabilities import load_manifest, manifest_hash, validate_plan_capabilities
from orchestrator.cartography.presets import apply_cartographic_preset
from orchestrator.cartography.intent import infer_goal_defaults

SCHEMA_VERSION = "2.0"

def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)

def _hash(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()

def normalize_goal(goal):
    g = apply_cartographic_preset(infer_goal_defaults(goal))
    if "goal" in g and "raw_goal" not in g:
        g["raw_goal"] = g.pop("goal")
    g.setdefault("schema_version", SCHEMA_VERSION)
    g.setdefault("goal_type", "build_map")
    g.setdefault("language", "id")
    g.setdefault("interpreted_goal", g.get("raw_goal", ""))
    g.setdefault("required_layer_roles", [])
    g.setdefault("layout", {})
    g["layout"].setdefault("paper", "A4")
    g["layout"].setdefault("orientation", "landscape")
    g.setdefault("outputs", {})
    g["outputs"].setdefault("formats", ["PDF", "PNG"])
    g["outputs"].setdefault("dpi", 400)
    g["outputs"].setdefault("save_mxd", False)
    g["outputs"].setdefault("overwrite_policy", "deny")
    g.setdefault("save_policy", "none")
    g.setdefault("dry_run", True)
    g.setdefault("max_repair_cycles", 3)
    g.setdefault("accepted_warnings", [])
    g.setdefault("source_edit_policy", "read_only")
    if g.get("target_mode") == "CURRENT_IN_PLACE":
        g["source_edit_policy"] = "in_place"
        g["save_policy"] = "overwrite"
        g["outputs"]["save_mxd"] = True
    g.setdefault("cartographic_profile", "auto")
    g.setdefault("reference_analysis", {})
    g.setdefault("datasets", [])
    g.setdefault("administrative_location", {})
    g.setdefault("persistence", {})
    g.setdefault("visual_feedback", {})
    g.setdefault("ignore_roles", [])
    g.setdefault("ignore_datasets", [])
    g.setdefault("cartographic_notes", [])
    return g

def validate_goal(goal):
    errors = []
    if not isinstance(goal, dict):
        return [{"code":"INVALID_GOAL","field":"goal","message":"Goal must be an object."}]
    if goal.get("schema_version") != SCHEMA_VERSION:
        errors.append({"code":"SCHEMA_VERSION_UNSUPPORTED","field":"schema_version"})
    if goal.get("goal_type") not in ("build_map", "layout_only"):
        errors.append({"code":"INVALID_GOAL_TYPE","field":"goal_type"})
    if not str(goal.get("raw_goal") or "").strip():
        errors.append({"code":"REQUIRED","field":"raw_goal"})
    if goal.get("target_mode") not in ("CURRENT", "CURRENT_IN_PLACE", "TEMPLATE", "NEW_DOCUMENT"):
        errors.append({"code":"INVALID_TARGET_MODE","field":"target_mode"})
    outputs = goal.get("outputs") or {}
    if outputs.get("dpi", 400) < 72:
        errors.append({"code":"INVALID_DPI","field":"outputs.dpi"})
    repair_cycles = goal.get("max_repair_cycles", 3)
    if repair_cycles < 0 or repair_cycles > 3:
        errors.append({"code":"INVALID_REPAIR_BUDGET","field":"max_repair_cycles"})
    return errors

def _strategy(goal):
    if goal.get("goal_type") == "layout_only":
        return "D_LAYOUT_ONLY"
    return {
        "CURRENT": "A_EXISTING_MXD",
        "CURRENT_IN_PLACE": "D_CURRENT_MXD_IN_PLACE_CARTOGRAPHY",
        "TEMPLATE": "B_TEMPLATE_DATA",
        "NEW_DOCUMENT": "C_BLANK_DATA",
    }[goal["target_mode"]]

def _blockers(goal, context):
    blockers = []
    strategy = _strategy(goal)
    if strategy in ("A_EXISTING_MXD", "D_CURRENT_MXD_IN_PLACE_CARTOGRAPHY") and not bool((context or {}).get("available")):
        blockers.append({"code":"CONTEXT_INCOMPLETE","message":"CURRENT target is unavailable for authoritative inspection."})
    if strategy == "D_CURRENT_MXD_IN_PLACE_CARTOGRAPHY":
        revision = (context or {}).get("document_revision") or {}
        document_path = revision.get("document_path") if isinstance(revision, dict) else None
        if not document_path:
            blockers.append({"code":"CURRENT_MXD_PATH_REQUIRED","field":"target_context.document_path"})
        reference_image = str(goal.get("reference_image") or "").strip()
        reference_policy = goal.get("reference_policy") or {}
        require_analysis = bool(reference_policy.get("require_analysis", True))
        if reference_image and require_analysis and not (goal.get("reference_analysis") or {}):
            blockers.append({
                "code":"REFERENCE_ANALYSIS_REQUIRED",
                "field":"reference_analysis",
                "message":"A supplied reference image must be converted to normalized cartographic reference_analysis before execution."
            })
    if strategy == "B_TEMPLATE_DATA":
        if not goal.get("template_mxd"):
            blockers.append({"code":"TEMPLATE_REQUIRED","field":"template_mxd"})
        if goal.get("goal_type") == "build_map" and not goal.get("data_root"):
            blockers.append({"code":"DATA_ROOT_REQUIRED","field":"data_root"})
    if strategy == "C_BLANK_DATA" and goal.get("goal_type") == "build_map" and not goal.get("data_root"):
        blockers.append({"code":"DATA_ROOT_REQUIRED","field":"data_root"})
    if (not goal.get("dry_run", True) and strategy != "D_CURRENT_MXD_IN_PLACE_CARTOGRAPHY" and not ((goal.get("outputs") or {}).get("output_dir"))):
        blockers.append({"code":"OUTPUT_DIR_REQUIRED","field":"outputs.output_dir"})
    if goal.get("goal_type") == "build_map" and not goal.get("crs"):
        map_info = (context or {}).get("map") or {}
        dataframe = (context or {}).get("dataframe") or {}
        map_sr = map_info.get("crs") or map_info.get("spatial_reference") if isinstance(map_info, dict) else None
        df_sr = dataframe.get("spatial_reference") if isinstance(dataframe, dict) else None
        if not (map_sr or df_sr):
            blockers.append({"code":"CRS_REQUIRED_BEFORE_EXECUTE","field":"crs","message":"CRS may be resolved from authoritative context, but may not be guessed."})
    return blockers

def _node(step_id, action, deps, lane, effect, dry, timeout=30, args=None, evidence=None):
    return {
        "step_id": step_id,
        "action": action,
        "arguments": args or {},
        "dependencies": deps,
        "lane": lane,
        "effect_class": effect,
        "dry_run_eligible": dry,
        "selected_for_dry_run": dry,
        "preconditions": [],
        "postconditions": [],
        "resource_set": [],
        "timeout_seconds": timeout,
        "retry_class": "read_revalidate" if effect == "read" else "reconcile_required",
        "evidence": evidence or [],
    }

def _mark_dry_run_selection(nodes):
    selected = set()
    for node in nodes:
        deps = node.get("dependencies") or []
        allowed = bool(node.get("dry_run_eligible")) and all(dep in selected for dep in deps)
        node["selected_for_dry_run"] = allowed
        if allowed:
            selected.add(node["step_id"])
    return nodes

def _nodes_for(strategy):
    base = [
        _node("s001","orchestrator.validate_goal",[],"pure","read",True,5),
    ]
    if strategy == "A_EXISTING_MXD":
        base += [
            _node("s010","arcmap_ping",["s001"],"live","read",True,5,evidence=["runtime_fingerprint"]),
            _node("s020","arcmap_get_status",["s010"],"live","read",True,10,evidence=["document_context"]),
            _node("s030","arcmap_inspect_current_map",["s020"],"live","read",True,20,evidence=["map_snapshot"]),
            _node("s040","arcmap_list_layers",["s030"],"live","read",True,20,evidence=["layer_manifest"]),
            _node("s050","arcmap_list_layout_elements",["s030"],"live","read",True,20,evidence=["layout_manifest"]),
            _node("s055","arcmap_get_dataframe_state",["s030"],"live","read",True,20,evidence=["spatial_reference","scale","extent"]),
            _node("s060","orchestrator.prepare_strategy_a",["s040","s050","s055"],"pure","read",True,10,evidence=["recipe_candidate"]),
            _node("s100","orchestrator.execute_strategy_a",["s060"],"live","live_write",False,120,evidence=["mutation_receipt"]),
        ]
    elif strategy == "D_CURRENT_MXD_IN_PLACE_CARTOGRAPHY":
        base += [
            _node("s010","arcmap_ping",["s001"],"live","read",True,5,evidence=["runtime_fingerprint"]),
            _node("s020","arcmap_get_status",["s010"],"live","read",True,10,evidence=["document_context"]),
            _node("s030","arcmap_inspect_current_map",["s020"],"live","read",True,20,evidence=["map_snapshot"]),
            _node("s040","arcmap_list_layers",["s030"],"live","read",True,20,evidence=["layer_manifest"]),
            _node("s050","arcmap_list_layout_elements",["s030"],"live","read",True,20,evidence=["layout_manifest"]),
            _node("s055","arcmap_get_dataframe_state",["s030"],"live","read",True,20,evidence=["spatial_reference","scale","extent"]),
            _node("s060","orchestrator.compile_cartographic_spec",["s040","s050","s055"],"pure","read",True,20,evidence=["cartographic_spec","semantic_roles"]),
            _node("s070","orchestrator.create_persistent_mxd_checkpoint",["s060"],"live","live_write",False,60,evidence=["persistent_mxd_checkpoint"]),
            _node("s100","orchestrator.execute_strategy_d",["s070"],"live","live_write",False,180,evidence=["cartographic_program_receipt"]),
            _node("s150","orchestrator.cartographic_visual_qa",["s100"],"pure","read",False,60,evidence=["visual_qa_report"]),
            _node("s160","orchestrator.cartographic_bounded_repair",["s150"],"live","live_write",False,180,evidence=["repair_receipts"]),
        ]
    elif strategy == "B_TEMPLATE_DATA":
        base += [
            _node("s010","orchestrator.file_worker_probe",["s001"],"file_worker","read",True,60,evidence=["worker_capability"]),
            _node("s060","orchestrator.prepare_strategy_b",["s010"],"file_worker","file_write",False,120,evidence=["working_copy"]),
        ]
    elif strategy == "C_BLANK_DATA":
        base += [
            _node("s010","orchestrator.file_worker_probe",["s001"],"file_worker","read",True,60,evidence=["worker_capability"]),
            _node("s060","orchestrator.prepare_strategy_c",["s010"],"file_worker","file_write",False,120,evidence=["working_copy"]),
        ]
    else:
        base += [
            _node("s010","arcmap_ping",["s001"],"live","read",True,5,evidence=["runtime_fingerprint"]),
            _node("s060","orchestrator.prepare_layout_only",["s010"],"pure","read",True,10,evidence=["layout_candidate"]),
        ]
    if strategy == "D_CURRENT_MXD_IN_PLACE_CARTOGRAPHY":
        base += [
            _node("s200","orchestrator.final_validate",["s160"],"pure","read",False,90,evidence=["artifact_gate","visual_acceptance"]),
            _node("s250","orchestrator.save_current_mxd_in_place",["s200"],"live","live_write",False,60,evidence=["saved_current_mxd"]),
            _node("s300","orchestrator.publish",["s250"],"file_worker","publish",False,120,evidence=["publish_manifest"]),
        ]
    else:
        base += [
            _node("s200","orchestrator.final_validate",[base[-1]["step_id"]],"pure","read",True,30,evidence=["validation_report"]),
            _node("s300","orchestrator.publish",["s200"],"file_worker","publish",False,120,evidence=["publish_manifest"]),
        ]
    return _mark_dry_run_selection(base)

def compile_plan(goal, context=None, tool_manifest=None):
    g = normalize_goal(goal)
    errors = validate_goal(g)
    if errors:
        return {"ok":False,"status":"INVALID","errors":errors,"warnings":[],"data":None}
    manifest = tool_manifest or load_manifest()
    strategy = _strategy(g)
    blockers = _blockers(g, context or {})
    assumptions = []
    if not g.get("title"):
        assumptions.append("Title may be derived from raw_goal; this is non-critical and must be recorded.")
    nodes = _nodes_for(strategy)
    dry_nodes = [n for n in nodes if n.get("selected_for_dry_run")]
    revision=(context or {}).get("document_revision") or {}
    if not isinstance(revision,dict):
        revision={}
    target_context={
        "instance_id":revision.get("bridge_instance_id") or revision.get("instance_id"),
        "document_id":revision.get("document_id"),
        "document_path":revision.get("document_path"),
        "pid":revision.get("pid"),
    }
    target_context["document_revision"]={
        "instance_id":target_context.get("instance_id"),
        "document_id":target_context.get("document_id"),
        "document_path":target_context.get("document_path"),
        "pid":target_context.get("pid"),
    }
    payload = {
        "schema_version":SCHEMA_VERSION,
        "strategy":strategy,
        "goal":g,
        "target_context":target_context if strategy in ("A_EXISTING_MXD","D_CURRENT_MXD_IN_PLACE_CARTOGRAPHY") else {},
        "context_fingerprint":(context or {}).get("fingerprint"),
        "tool_manifest_hash":manifest_hash(manifest),
        "profile_version":manifest.get("profile_version",""),
        "assumptions":assumptions,
        "blockers":blockers,
        "nodes":nodes,
        "dry_run_nodes":[n["step_id"] for n in dry_nodes],
    }
    ph = _hash(payload)
    payload["plan_hash"] = ph
    payload["plan_id"] = "plan_" + ph[:20]
    cap_errors = validate_plan_capabilities(payload, dry_run=True, manifest=manifest)
    if cap_errors:
        return {"ok":False,"status":"INVALID","errors":cap_errors,"warnings":[],"data":payload}
    return {
        "ok": not blockers,
        "status":"PLANNED" if not blockers else "BLOCKED",
        "plan_id":payload["plan_id"],
        "plan_hash":ph,
        "errors":blockers,
        "warnings":assumptions,
        "data":payload,
    }

def validate_compiled_plan(plan):
    if not isinstance(plan, dict):
        return [{"code":"INVALID_PLAN"}]
    required = ("schema_version","plan_id","plan_hash","strategy","goal","nodes","blockers")
    errors = [{"code":"REQUIRED","field":k} for k in required if k not in plan]
    if errors:
        return errors
    if plan.get("schema_version") != SCHEMA_VERSION:
        errors.append({"code":"SCHEMA_VERSION_UNSUPPORTED","field":"schema_version"})
    clone = dict(plan)
    expected_hash = clone.pop("plan_hash", None)
    clone.pop("plan_id", None)
    if expected_hash != _hash(clone):
        errors.append({"code":"PLAN_HASH_MISMATCH"})
    errors.extend(validate_plan_capabilities(plan, dry_run=True))
    return errors
