# -*- coding: utf-8 -*-
"""Stable toolbox entry for the installed Zagent Multi Platform ArcMap bridge."""
import imp
import json
import os
import sys

def _source_toolbox():
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("LOCALAPPDATA is not available.")
    path = os.path.join(local, "Zagent", "ArcMap", "multi-platform.json")
    with open(path, "rb") as stream:
        cfg = json.loads(stream.read().decode("utf-8"))
    if cfg.get("environment") != "MULTI_PLATFORM":
        raise RuntimeError("Wrong Zagent ArcMap environment.")
    engine = os.path.normpath(os.path.abspath(cfg["engine_root"]))
    toolbox = os.path.join(engine, "arcmap_bridge", "ArcMapAgent.pyt")
    if not os.path.isfile(toolbox):
        raise RuntimeError("Zagent Multi Platform toolbox was not found.")
    module_name = "zagent_multi_platform_arcmap_toolbox"
    existing = sys.modules.get(module_name)
    if existing is not None:
        actual = os.path.normcase(os.path.abspath(getattr(existing, "__file__", "")))
        if actual != os.path.normcase(os.path.abspath(toolbox)):
            raise RuntimeError("Foreign ArcMap toolbox already loaded; restart ArcMap.")
        return existing
    for key in ("data_root", "config_dir", "ipc_root"):
        os.environ["ZAGENT_ARCMAP_" + key.upper()] = cfg[key]
    os.environ["ZAGENT_ARCMAP_ENGINE_ROOT"] = engine
    return imp.load_source(module_name, toolbox)

class Toolbox(object):
    def __init__(self):
        original = _source_toolbox().Toolbox()
        self.label = "Zagent Multi Platform"
        self.alias = "zagent_arcmap_multi_platform"
        self.tools = original.tools
