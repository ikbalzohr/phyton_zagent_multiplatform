# -*- coding: utf-8 -*-
"""ArcMap 10.6 Python 2.7 Add-In for Zagent Multi Platform.

This code executes inside ArcMap. Never launch ArcMap or use ArcPy in a
background process. User's current document is never saved automatically.
"""
import imp
import json
import os
import sys
import traceback

_ENVIRONMENT = "MULTI_PLATFORM"
_LOCATOR_NAME = "multi-platform.json"
_BOOTSTRAP_MODULE = "zagent_arcmap_bootstrap"

def _locator_path():
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        raise RuntimeError("LOCALAPPDATA is unavailable to the ArcMap Add-In.")
    return os.path.join(local, "Zagent", "ArcMap", _LOCATOR_NAME)

def _read_locator():
    with open(_locator_path(), "rb") as stream:
        cfg = json.loads(stream.read().decode("utf-8"))
    if cfg.get("environment") != _ENVIRONMENT:
        raise RuntimeError("Multi Platform Add-In refuses foreign environment.")
    engine = os.path.normpath(os.path.abspath(cfg["engine_root"]))
    expected_tail = os.path.normcase(os.path.join("agents", "arcmap", "engine"))
    if not os.path.normcase(engine).endswith(expected_tail):
        raise RuntimeError("ArcMap engine path is not a Zagent installation.")
    installation_root = os.path.dirname(os.path.dirname(os.path.dirname(engine)))
    expected_data = os.path.join(installation_root, "data", "arcmap")
    paths = (
        ("data_root", expected_data),
        ("config_dir", os.path.join(expected_data, "config")),
        ("ipc_root", os.path.join(expected_data, "ipc")),
    )
    for key, expected in paths:
        actual = os.path.normpath(os.path.abspath(cfg.get(key, "")))
        if os.path.normcase(actual) != os.path.normcase(expected):
            raise RuntimeError("ArcMap Add-In locator path mismatch: " + key)
    cfg["engine_root"] = engine
    if not os.path.isfile(os.path.join(engine, "arcmap_bridge", "bootstrap.py")):
        raise RuntimeError("Multi Platform bridge bootstrap is missing.")
    return cfg

def _load_bridge():
    cfg = _read_locator()
    engine = cfg["engine_root"]
    bootstrap_path = os.path.join(engine, "arcmap_bridge", "bootstrap.py")
    existing = sys.modules.get(_BOOTSTRAP_MODULE)
    if existing is not None:
        actual = os.path.normcase(os.path.abspath(getattr(existing, "__file__", "")))
        if actual != os.path.normcase(os.path.abspath(bootstrap_path)):
            raise RuntimeError("Another ArcMap bridge is loaded. Restart ArcMap.")
        return existing
    for key in ("data_root", "config_dir", "ipc_root"):
        os.environ["ZAGENT_ARCMAP_" + key.upper()] = cfg[key]
    os.environ["ZAGENT_ARCMAP_ENGINE_ROOT"] = engine
    return imp.load_source(_BOOTSTRAP_MODULE, bootstrap_path)

def _log_exception():
    try:
        directory = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Zagent", "ArcMap")
        if not os.path.isdir(directory):
            os.makedirs(directory)
        with open(os.path.join(directory, "multi-platform-addin-errors.log"), "a") as stream:
            stream.write(traceback.format_exc() + "\n")
    except Exception:
        pass

class BridgeExtension(object):
    def __init__(self):
        self.enabled = True
        self._bridge = None

    def _connect(self, changed=False):
        try:
            if self._bridge is None:
                self._bridge = _load_bridge()
            if changed:
                self._bridge.document_changed()
            self._bridge.start()
        except Exception:
            _log_exception()

    def startup(self):
        self._connect()

    def openDocument(self):
        self._connect(True)

    def newDocument(self):
        self._connect(True)

    def activeViewChanged(self):
        self._connect()

    def beforeCloseDocument(self):
        try:
            if self._bridge is not None:
                self._bridge.document_changed()
        except Exception:
            _log_exception()
        return True

    def shutdown(self):
        try:
            if self._bridge is not None:
                self._bridge.stop()
        except Exception:
            _log_exception()
