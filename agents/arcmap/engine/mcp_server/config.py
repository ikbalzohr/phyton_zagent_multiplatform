import json
import os
import ntpath
from pathlib import Path

ENGINE_ROOT = Path(
    os.environ.get("ZAGENT_ARCMAP_ENGINE_ROOT")
    or Path(__file__).resolve().parents[1]
)
AGENT_ROOT = ENGINE_ROOT.parent
DATA_ROOT = Path(
    os.environ.get("ZAGENT_ARCMAP_DATA_ROOT")
    or (AGENT_ROOT / "data")
)
CONFIG_DIR = Path(
    os.environ.get("ZAGENT_ARCMAP_CONFIG_DIR")
    or (DATA_ROOT / "config")
)
IPC_ROOT = Path(
    os.environ.get("ZAGENT_ARCMAP_IPC_ROOT")
    or (DATA_ROOT / "ipc")
)
STATIC_CONFIG_DIR = ENGINE_ROOT / "config"

def load_json(name, default):
    for base in (CONFIG_DIR, STATIC_CONFIG_DIR):
        path = base / name
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                merged = default.copy()
                merged.update(data)
                return merged
        except Exception:
            pass
    return default.copy()

AGENT = load_json("agent_config.json", {
    "safe_mode": True,
    "allow_live_write": False,
    "allow_save": False,
    "allow_destructive_operations": False,
    "allow_geoprocessing": False,
    "allow_export": True,
    "require_health_check": True,
    "command_timeout_seconds": 15,
    "ipc_poll_ms": 500,
    "archive_ipc": True,
    "default_export_dpi": 400,
    "default_export_formats": ["PDF", "PNG"],
    "default_output_folder": "Hasil Peta"
})
PATHS = load_json("paths.json", {})

def _is_within(path, root):
    child = ntpath.normcase(ntpath.abspath(str(path)))
    base = ntpath.normcase(ntpath.abspath(str(root)))
    return child == base or child.startswith(base.rstrip("\\/") + "\\")

_MANUAL_BASELINE = PATHS.get("manual_baseline") or ""
if _MANUAL_BASELINE and _is_within(ENGINE_ROOT, _MANUAL_BASELINE):
    raise RuntimeError("Zagent ArcMap engine may not point inside an immutable legacy Manual baseline.")
