# -*- coding: utf-8 -*-
from __future__ import print_function
import json
import os
import ntpath

BRIDGE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_ROOT = os.environ.get("ZAGENT_ARCMAP_ENGINE_ROOT") or os.path.dirname(BRIDGE_DIR)
AGENT_ROOT = os.path.dirname(ENGINE_ROOT)
STATIC_CONFIG_DIR = os.path.join(ENGINE_ROOT, "config")
RUNTIME_LOCATOR = os.path.join(BRIDGE_DIR, "bridge_runtime.json")

def _read_json_file(path):
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        if not isinstance(raw, str):
            raw = raw.decode("utf-8")
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

_LOCATOR = _read_json_file(RUNTIME_LOCATOR)

DATA_ROOT = (
    os.environ.get("ZAGENT_ARCMAP_DATA_ROOT")
    or _LOCATOR.get("data_root")
    or os.path.join(AGENT_ROOT, "data")
)
CONFIG_DIR = (
    os.environ.get("ZAGENT_ARCMAP_CONFIG_DIR")
    or _LOCATOR.get("config_dir")
    or os.path.join(DATA_ROOT, "config")
)
IPC_ROOT = (
    os.environ.get("ZAGENT_ARCMAP_IPC_ROOT")
    or _LOCATOR.get("ipc_root")
    or os.path.join(DATA_ROOT, "ipc")
)

def _load_json(name, default):
    for base in (CONFIG_DIR, STATIC_CONFIG_DIR):
        path = os.path.join(base, name)
        try:
            with open(path, "rb") as fh:
                raw = fh.read()
            if not isinstance(raw, str):
                raw = raw.decode("utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                merged = default.copy()
                merged.update(data)
                return merged
        except Exception:
            pass
    return default.copy()

AGENT = _load_json("agent_config.json", {
    "safe_mode": True,
    "allow_live_write": False,
    "allow_save": False,
    "allow_destructive_operations": False,
    "allow_geoprocessing": False,
    "allow_export": True,
    "ipc_poll_ms": 500,
    "archive_ipc": True,
    "default_export_dpi": 400,
    "default_export_formats": ["PDF", "PNG"],
    "default_output_folder": "Hasil Peta"
})

PATHS = _load_json("paths.json", {})

def _is_within(path, root):
    child = ntpath.normcase(ntpath.abspath(path))
    base = ntpath.normcase(ntpath.abspath(root))
    return child == base or child.startswith(base.rstrip("\\/") + "\\")

_MANUAL_BASELINE = PATHS.get("manual_baseline") or ""
if _MANUAL_BASELINE and _is_within(ENGINE_ROOT, _MANUAL_BASELINE):
    raise RuntimeError("Zagent ArcMap engine may not point inside an immutable legacy Manual baseline.")
