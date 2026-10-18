# -*- coding: utf-8 -*-
from __future__ import print_function
import os
import sys
import traceback
from .registry import get, names, ACTIONS
from . import concurrent_edit_guard

# Import built-in feature modules for registration side effects.
from features import connection
from features import inspection
from features import layers
from features import layout_text
from features import extent_zoom
from features import labels
from features import symbology
from features import data_sources
from features import selection
from features import geoprocessing
from features import spatial_analysis
from features import layout
from features import export
from features import project
from features import observability
from features import layer_management
from features import cartography
from features import analysis_extended
from features import layout_automation
from features import export_qa
from features import map_recipe
from features import cartographic_program
from features import native_layer_properties
from features import native_grids
from features import smart_corner
from features import analytics
from features import concurrent_edit
from features import native_label_preset
from features import gis_server_connector
from features import native_scale_bar
from features import calculate_geometry
from features import smart_coordinate_importer

# Engine root is derived from the installed Zagent ArcMap package.
WORK_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if WORK_ROOT not in sys.path:
    sys.path.insert(0, WORK_ROOT)

# Stage 2: explicit registry integration.
STAGE2_BRIDGE_STATUS = {
    "ok": False,
    "installed": [],
    "count": 0,
    "error": "not loaded"
}
try:
    from stage2.bridge import install_into_registry as _install_stage2_registry
    _stage2_installed = _install_stage2_registry(ACTIONS)
    STAGE2_BRIDGE_STATUS = {
        "ok": True,
        "installed": _stage2_installed,
        "count": len(_stage2_installed)
    }
except Exception as _stage2_exc:
    STAGE2_BRIDGE_STATUS = {
        "ok": False,
        "installed": [],
        "count": 0,
        "error": str(_stage2_exc),
        "traceback": traceback.format_exc()
    }

# Stage 3: explicit registry integration.  This intentionally mirrors Stage 2.
# The previous Stage 3 patch tried to wrap a process_command symbol that does not
# exist in this modular dispatcher, which left the live bridge at 98 actions.
STAGE3_BRIDGE_STATUS = {
    "ok": False,
    "installed": [],
    "count": 0,
    "error": "not loaded"
}
try:
    from stage3.bridge import install_into_registry as _install_stage3_registry
    _stage3_installed = _install_stage3_registry(ACTIONS)
    STAGE3_BRIDGE_STATUS = {
        "ok": True,
        "installed": _stage3_installed,
        "count": len(_stage3_installed)
    }
except Exception as _stage3_exc:
    STAGE3_BRIDGE_STATUS = {
        "ok": False,
        "installed": [],
        "count": 0,
        "error": str(_stage3_exc),
        "traceback": traceback.format_exc()
    }


def dispatch(command):
    action_name = command.get("action", "")
    request_id = command.get("request_id")
    func = get(action_name)
    if func is None:
        return {
            "ok": False,
            "error": "Unknown action: {0}".format(action_name),
            "available_actions": names(),
            "request_id": request_id
        }
    try:
        blocked = concurrent_edit_guard.reject_mutation(command)
        if blocked:
            blocked['action'] = action_name
            blocked['request_id'] = request_id
            return blocked
        payload = func(command)
        if not isinstance(payload, dict):
            payload = {"ok": True, "result": payload}
        payload.setdefault("ok", True)
        payload["action"] = action_name
        payload["request_id"] = request_id
        return payload
    except Exception as exc:
        payload = {
            "ok": False,
            "action": action_name,
            "request_id": request_id,
            "error": str(exc),
            "traceback": traceback.format_exc()
        }
        if getattr(exc, "code", None):
            payload["code"] = exc.code
        return payload
