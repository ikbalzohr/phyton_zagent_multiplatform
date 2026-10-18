import json
import os
import time

os.environ["ZAGENT_ENVIRONMENT"] = "DEVELOPMENT"
os.environ["ZAGENT_ARCMAP_DATA_ROOT"] = r"D:\3-Ikbalzohr\Agent\appBridge\production\Zagent\v3\dev\data\arcmap"
os.environ["ZAGENT_ARCMAP_CONFIG_DIR"] = r"D:\3-Ikbalzohr\Agent\appBridge\production\Zagent\v3\dev\data\arcmap\config"
os.environ["ZAGENT_ARCMAP_IPC_ROOT"] = r"D:\3-Ikbalzohr\Agent\appBridge\production\Zagent\v3\dev\data\arcmap\ipc"

from mcp_server.services import AgentServices
from orchestrator.planner import plan_goal

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

started = time.monotonic()
result = plan_goal(AgentServices(), goal)
print(json.dumps({
    "elapsed_seconds": round(time.monotonic() - started, 3),
    "ok": result.get("ok"),
    "status": result.get("status"),
    "plan_id": result.get("plan_id"),
    "plan_hash": result.get("plan_hash"),
    "errors": result.get("errors"),
    "context_errors": (result.get("context") or {}).get("errors"),
}, ensure_ascii=False))
