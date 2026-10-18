import hashlib
import json
from pathlib import Path

_MANIFEST_PATH = Path(__file__).resolve().parent / "manifest.json"

def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def load_manifest():
    with _MANIFEST_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)

def manifest_hash(manifest=None):
    data = manifest if manifest is not None else load_manifest()
    return hashlib.sha256(_canonical(data).encode("utf-8")).hexdigest()

def primitive_map(manifest=None):
    data = manifest if manifest is not None else load_manifest()
    return {item["name"]: item for item in data.get("primitives", [])}

def validate_plan_capabilities(plan, dry_run=True, manifest=None):
    caps = primitive_map(manifest)
    errors = []
    for node in plan.get("nodes", []):
        action = node.get("action")
        cap = caps.get(action)
        if not cap:
            errors.append({"code":"CAPABILITY_UNAVAILABLE","step_id":node.get("step_id"),"action":action})
            continue
        if node.get("lane") != cap.get("lane"):
            errors.append({"code":"CAPABILITY_LANE_MISMATCH","step_id":node.get("step_id"),"action":action})
        if node.get("effect_class") != cap.get("effect_class"):
            errors.append({"code":"CAPABILITY_EFFECT_MISMATCH","step_id":node.get("step_id"),"action":action})
        if dry_run and node.get("selected_for_dry_run", False) and not cap.get("dry_run_eligible", False):
            errors.append({"code":"DRY_RUN_WRITE_BLOCKED","step_id":node.get("step_id"),"action":action})
    return errors
