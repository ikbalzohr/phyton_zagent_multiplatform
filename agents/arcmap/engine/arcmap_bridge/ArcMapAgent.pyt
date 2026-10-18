# -*- coding: utf-8 -*-
import imp
import os
import sys
import arcpy

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_ROOT = os.path.dirname(BRIDGE_DIR)

def _bootstrap():
    name = "zagent_arcmap_bootstrap"
    existing = sys.modules.get(name)
    if existing is not None:
        expected = os.path.normcase(os.path.join(BRIDGE_DIR, "bootstrap.py"))
        actual = os.path.normcase(os.path.abspath(existing.__file__))
        if actual != expected:
            raise RuntimeError("Another Zagent bridge is loaded. Restart ArcMap before switching environments.")
        return existing
    return imp.load_source(name, os.path.join(BRIDGE_DIR, "bootstrap.py"))

class Toolbox(object):
    def __init__(self):
        self.label = "Zagent ArcMap"
        self.alias = "zagent_arcmap"
        self.tools = [StartBridge, StopBridge, BridgeStatus]

class StartBridge(object):
    def __init__(self):
        self.label = "Start Zagent Live Bridge"
        self.description = "Start the Zagent bridge for CURRENT MXD with exclusive-session ownership."
        self.canRunInBackground = False
    def getParameterInfo(self):
        p = arcpy.Parameter(displayName="Poll interval (ms)", name="interval_ms",
                            datatype="GPLong", parameterType="Optional", direction="Input")
        p.value = 500
        return [p]
    def execute(self, parameters, messages):
        _bootstrap().start(int(parameters[0].value or 500))

class StopBridge(object):
    def __init__(self):
        self.label = "Stop Zagent Live Bridge"
        self.description = "Stop the Zagent ArcMap bridge. ArcMap remains open."
        self.canRunInBackground = False
    def getParameterInfo(self):
        return []
    def execute(self, parameters, messages):
        _bootstrap().stop()

class BridgeStatus(object):
    def __init__(self):
        self.label = "Zagent Bridge Status"
        self.description = "Show Zagent ArcMap bridge ownership and CURRENT MXD status."
        self.canRunInBackground = False
    def getParameterInfo(self):
        return []
    def execute(self, parameters, messages):
        _bootstrap().status()