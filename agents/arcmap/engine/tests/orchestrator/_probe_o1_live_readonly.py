import json
import os
import sys
import time

SOURCE_ROOT = r"D:\3-Ikbalzohr\Agent\appBridge\production\Zagent\v3\agents\arcmap\engine"
PROD_DATA = r"D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent\data\arcmap"
PROD_CONFIG = r"D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent\data\arcmap\config"
PROD_IPC = r"D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent\data\arcmap\ipc"

os.environ["ZAGENT_ARCMAP_ENGINE_ROOT"] = SOURCE_ROOT
os.environ["ZAGENT_ARCMAP_DATA_ROOT"] = PROD_DATA
os.environ["ZAGENT_ARCMAP_CONFIG_DIR"] = PROD_CONFIG
os.environ["ZAGENT_ARCMAP_IPC_ROOT"] = PROD_IPC
sys.path.insert(0, SOURCE_ROOT)

from mcp_server.services import AgentServices
from orchestrator.context import collect_live_context
from orchestrator.compiler import compile_plan

goal = {
    "schema_version": "2.0",
    "goal_type": "build_map",
    "raw_goal": "Susun peta administrasi PT Buol Agri Lestari dari data yang tersedia",
    "target_mode": "CURRENT",
    "required_layer_roles": ["batas_perusahaan", "jalan", "sungai", "desa"],
    "layout": {"paper": "A4", "orientation": "landscape"},
    "outputs": {"formats": ["PDF", "PNG"], "dpi": 400, "save_mxd": False},
    "dry_run": True,
    "max_repair_cycles": 3,
    "source_edit_policy": "read_only",
}

services = AgentServices()
started = time.monotonic()
before = collect_live_context(services)
plan = compile_plan(goal, context=before)
after = collect_live_context(services)
elapsed = time.monotonic() - started

nodes = (plan.get("data") or {}).get("nodes") or []
selected = [n for n in nodes if n.get("selected_for_dry_run")]
writes_selected = [n for n in selected if n.get("effect_class") != "read"]
df = before.get("dataframe") or {}
output = {
    "elapsed_seconds": round(elapsed, 3),
    "before_available": before.get("available"),
    "after_available": after.get("available"),
    "before_fingerprint": before.get("fingerprint"),
    "after_fingerprint": after.get("fingerprint"),
    "fingerprint_equal": before.get("fingerprint") == after.get("fingerprint"),
    "document_revision_equal": before.get("document_revision") == after.get("document_revision"),
    "plan_ok": plan.get("ok"),
    "plan_status": plan.get("status"),
    "plan_id": plan.get("plan_id"),
    "plan_hash": plan.get("plan_hash"),
    "blockers": plan.get("errors"),
    "selected_dry_run_nodes": [n.get("step_id") for n in selected],
    "selected_non_read_nodes": [{"step_id": n.get("step_id"), "effect_class": n.get("effect_class")} for n in writes_selected],
    "crs": df.get("spatial_reference"),
    "context_errors_before": before.get("errors"),
    "context_errors_after": after.get("errors"),
}
print(json.dumps(output, indent=2, ensure_ascii=False))
