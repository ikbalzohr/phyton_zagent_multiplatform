# -*- coding: utf-8 -*-
import arcpy
from core.registry import action, names
from core.current_map import get_mxd
from core.config import AGENT
from core.bridge_state import context


def _stage2_action_names():
    return [x for x in names() if x.startswith("stage2_")]

def _stage3_action_names():
    return [x for x in names() if x.startswith("stage3_")]


@action("ping")
def ping(command):
    mxd = get_mxd()
    try:
        install = arcpy.GetInstallInfo()
    except Exception:
        install = {}
    all_actions = names()
    stage2_actions = _stage2_action_names()
    stage3_actions = _stage3_action_names()
    return {
        "ok": True,
        "status": "ARCMAP_AGENT_OK",
        "context": context(mxd),
        "mxd": getattr(mxd, "filePath", ""),
        "document_title": getattr(mxd, "title", ""),
        "arcgis_version": install.get("Version", ""),
        "safe_mode": bool(AGENT.get("safe_mode", True)),
        "bridge_action_count": len(all_actions),
        "stage2_bridge_action_count": len(stage2_actions),
        "stage2_bridge_loaded": len(stage2_actions) >= 8,
        "stage2_bridge_actions": stage2_actions,
        "stage3_bridge_action_count": len(stage3_actions),
        "stage3_bridge_loaded": len(stage3_actions) >= 20,
        "stage3_bridge_actions": stage3_actions,
        "zagent_version": "1.0.0"
    }


@action("status")
def status(command):
    mxd = get_mxd()
    frames = arcpy.mapping.ListDataFrames(mxd)
    all_actions = names()
    stage2_actions = _stage2_action_names()
    stage3_actions = _stage3_action_names()
    return {
        "ok": True,
        "mxd": getattr(mxd, "filePath", ""),
        "document_title": getattr(mxd, "title", ""),
        "data_frames": [df.name for df in frames],
        "bridge_action_count": len(all_actions),
        "stage2_bridge_action_count": len(stage2_actions),
        "stage2_bridge_loaded": len(stage2_actions) >= 8,
        "stage3_bridge_action_count": len(stage3_actions),
        "stage3_bridge_loaded": len(stage3_actions) >= 20,
        "zagent_version": "1.0.0",
        "saved": False
    }


@action("refresh")
def refresh(command):
    arcpy.RefreshActiveView()
    arcpy.RefreshTOC()
    return {"ok": True, "saved": False}