# -*- coding: utf-8 -*-
from __future__ import print_function
import imp
import os
import sys
import site

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_ROOT = os.path.dirname(BRIDGE_DIR)

def _norm(path):
    try:
        return os.path.normcase(os.path.abspath(path or ""))
    except Exception:
        return ""

def _assert_no_foreign_arcmap_bridge():
    our = _norm(ENGINE_ROOT)
    suspicious = (
        "bootstrap",
        "live_bridge",
        "core",
        "core.config",
        "core.ipc",
        "core.runner",
        "core.dispatcher",
        "features.connection",
        "stage2",
        "stage3",
    )
    conflicts = []
    for name in suspicious:
        mod = sys.modules.get(name)
        path = _norm(getattr(mod, "__file__", "")) if mod is not None else ""
        if path and not (path == our or path.startswith(our + os.sep)):
            conflicts.append((name, path))
    legacy_live = sys.modules.get("live_bridge")
    legacy_running = bool(getattr(legacy_live, "_TIMER_ID", None)) if legacy_live is not None else False
    if conflicts:
        details = "; ".join(["{0}={1}".format(x[0], x[1]) for x in conflicts])
        state = "running" if legacy_running else "loaded"
        raise RuntimeError(
            "Another ArcMap Agent bridge is already {0} in this ArcMap session. "
            "Zagent refuses dual ownership. Stop the legacy bridge and restart ArcMap "
            "before starting Zagent ArcMap. Conflicts: {1}".format(state, details)
        )

def _load_live_bridge():
    _assert_no_foreign_arcmap_bridge()
    vendor = os.path.join(ENGINE_ROOT, "vendor27")
    if os.path.isdir(vendor):
        site.addsitedir(vendor)
    if ENGINE_ROOT not in sys.path:
        sys.path.insert(0, ENGINE_ROOT)
    if BRIDGE_DIR not in sys.path:
        sys.path.insert(0, BRIDGE_DIR)
    module_name = "zagent_arcmap_live_bridge"
    existing = sys.modules.get(module_name)
    if existing is not None:
        if _norm(getattr(existing, "__file__", "")) != _norm(os.path.join(BRIDGE_DIR, "live_bridge.py")):
            raise RuntimeError("Zagent refuses dual ownership: another bridge instance is loaded.")
        return existing
    return imp.load_source(module_name, os.path.join(BRIDGE_DIR, "live_bridge.py"))

def start(interval_ms=None):
    return _load_live_bridge().start_bridge(interval_ms)

def stop():
    return _load_live_bridge().stop_bridge()

def status():
    return _load_live_bridge().bridge_status()

def document_changed():
    bridge = _load_live_bridge()
    bridge.bridge_state.document_changed()