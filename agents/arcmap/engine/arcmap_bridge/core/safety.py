# -*- coding: utf-8 -*-
from .config import AGENT

def _blocked(message):
    return {"ok": False, "blocked": True, "error": message}

def require_live_write():
    if not AGENT.get("allow_live_write", False):
        return _blocked("Live write operations are disabled by agent_config.json.")
    return None

def require_save():
    if not AGENT.get("allow_save", False):
        return _blocked("Saving MXD is disabled by Safe Mode.")
    return None

def require_destructive():
    if not AGENT.get("allow_destructive_operations", False):
        return _blocked("Destructive operations are disabled by Safe Mode.")
    return None

def require_geoprocessing():
    if not AGENT.get("allow_geoprocessing", False):
        return _blocked("Geoprocessing is disabled by Safe Mode.")
    return None

def require_export():
    if not AGENT.get("allow_export", True):
        return _blocked("Export operations are disabled by agent_config.json.")
    return None
