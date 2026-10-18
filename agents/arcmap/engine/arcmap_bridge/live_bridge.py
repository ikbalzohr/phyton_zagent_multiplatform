# -*- coding: utf-8 -*-
from __future__ import print_function
import ctypes
import os
import sys
import json
import time

BRIDGE_DIR = os.path.dirname(os.path.abspath(__file__))
if BRIDGE_DIR not in sys.path:
    sys.path.insert(0, BRIDGE_DIR)

from core.config import AGENT, DATA_ROOT, ENGINE_ROOT
from core.runner import process_next
from core.ipc import ensure_dirs, quarantine_stale
from core.current_map import get_mxd
from core import bridge_state

_TIMER_ID = None
_TIMER_CALLBACK = None
_BUSY = False
_OWNER_MUTEX = None
_OWNER_MUTEX_NAME = u"Local\Zagent.ArcMap.SessionOwner.v1"
_ERROR_ALREADY_EXISTS = 183
_OWNER_FILE = os.path.join(DATA_ROOT, "runtime", "arcmap-owner.json")
_KERNEL32 = ctypes.windll.kernel32
_LAST_HEARTBEAT = 0.0
_LAST_ERROR = None
_LAST_TIMER_TICK_EPOCH = 0.0
_TIMER_STARTED_EPOCH = 0.0
_TIMER_INTERVAL_MS = 0
_HEARTBEAT_SEQUENCE = 0
_KERNEL32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
_KERNEL32.CreateMutexW.restype = ctypes.c_void_p
_KERNEL32.CloseHandle.argtypes = [ctypes.c_void_p]
_KERNEL32.CloseHandle.restype = ctypes.c_int
_MOVEFILE_REPLACE_EXISTING = 0x1
_MOVEFILE_WRITE_THROUGH = 0x8
_KERNEL32.MoveFileExW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong]
_KERNEL32.MoveFileExW.restype = ctypes.c_int

_USER32 = ctypes.windll.user32
UINT_PTR = ctypes.c_size_t
TIMERPROC = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint, UINT_PTR, ctypes.c_ulong)

_USER32.SetTimer.argtypes = [ctypes.c_void_p, UINT_PTR, ctypes.c_uint, TIMERPROC]
_USER32.SetTimer.restype = UINT_PTR
_USER32.KillTimer.argtypes = [ctypes.c_void_p, UINT_PTR]
_USER32.KillTimer.restype = ctypes.c_int


def _path_unicode(path):
    try:
        return unicode(path)
    except NameError:
        return str(path)

def _replace_file_atomic(temp, target):
    flags = _MOVEFILE_REPLACE_EXISTING | _MOVEFILE_WRITE_THROUGH
    if not _KERNEL32.MoveFileExW(_path_unicode(temp), _path_unicode(target), flags):
        raise ctypes.WinError()


def _ensure_owner_dir():
    folder = os.path.dirname(_OWNER_FILE)
    if not os.path.isdir(folder):
        os.makedirs(folder)

def _write_owner_state(running, timer_id=None):
    try:
        _ensure_owner_dir()
        state = {
            "product": "Zagent ArcMap",
            "version": "1.0.0",
            "pid": os.getpid(),
            "running": bool(running),
            "timer_id": timer_id,
            "engine_root": ENGINE_ROOT,
            "updated_at_epoch": time.time(),
            "timer_started_epoch": _TIMER_STARTED_EPOCH,
            "timer_callback_epoch": _LAST_TIMER_TICK_EPOCH,
            "timer_interval_ms": _TIMER_INTERVAL_MS,
            "heartbeat_sequence": _HEARTBEAT_SEQUENCE,
            "context": bridge_state.context(),
            "last_error": _LAST_ERROR,
            "protocol_version": 2
        }
        temp = _OWNER_FILE + ".tmp"
        raw = json.dumps(state, indent=2)
        if not isinstance(raw, bytes):
            raw = raw.encode("utf-8")
        with open(temp, "wb") as fh:
            fh.write(raw)
        _replace_file_atomic(temp, _OWNER_FILE)
    except Exception:
        pass

def _acquire_owner_mutex():
    global _OWNER_MUTEX
    if _OWNER_MUTEX:
        return True
    handle = _KERNEL32.CreateMutexW(None, False, _OWNER_MUTEX_NAME)
    if not handle:
        raise RuntimeError("Could not create Zagent ArcMap ownership mutex.")
    error = _KERNEL32.GetLastError()
    if error == _ERROR_ALREADY_EXISTS:
        _KERNEL32.CloseHandle(handle)
        raise RuntimeError(
            "Another Zagent ArcMap bridge already owns ArcMap control. "
            "Dual bridge ownership is not allowed."
        )
    _OWNER_MUTEX = handle
    return True

def _release_owner_mutex():
    global _OWNER_MUTEX
    if _OWNER_MUTEX:
        try:
            _KERNEL32.CloseHandle(_OWNER_MUTEX)
        except Exception:
            pass
        _OWNER_MUTEX = None

def _timer_proc(hwnd, message, timer_id, tick):
    global _BUSY, _LAST_HEARTBEAT, _LAST_ERROR, _LAST_TIMER_TICK_EPOCH, _HEARTBEAT_SEQUENCE
    _LAST_TIMER_TICK_EPOCH = time.time()
    if _BUSY:
        return
    _BUSY = True
    try:
        # ArcPy stays on the UI thread. Keep queue draining bounded by time.
        now = _LAST_TIMER_TICK_EPOCH
        if now - _LAST_HEARTBEAT >= 1:
            _HEARTBEAT_SEQUENCE += 1
            _write_owner_state(True, _TIMER_ID)
            _LAST_HEARTBEAT = now
        count = 0
        while count < 50 and time.time() - now < 0.10 and process_next():
            count += 1
    except Exception as exc:
        _LAST_ERROR = str(exc)
        print("[Zagent ArcMap] bridge error: {0}".format(exc))
    finally:
        _BUSY = False



def start_bridge(interval_ms=None):
    global _TIMER_ID, _TIMER_CALLBACK, _TIMER_STARTED_EPOCH, _TIMER_INTERVAL_MS
    if _TIMER_ID:
        print("ZAGENT ARCMAP BRIDGE ALREADY RUNNING: {0}".format(_TIMER_ID))
        return _TIMER_ID
    _acquire_owner_mutex()
    try:
        ensure_dirs()
        quarantine_stale()
        get_mxd()  # fail fast if not inside ArcMap context
    except Exception:
        _release_owner_mutex()
        raise
    interval_ms = int(interval_ms or AGENT.get("ipc_poll_ms", 500))
    _TIMER_INTERVAL_MS = interval_ms
    _TIMER_CALLBACK = TIMERPROC(_timer_proc)
    _TIMER_ID = _USER32.SetTimer(None, 0, interval_ms, _TIMER_CALLBACK)
    if not _TIMER_ID:
        _TIMER_CALLBACK = None
        _release_owner_mutex()
        raise RuntimeError("Windows SetTimer failed.")
    _TIMER_STARTED_EPOCH = time.time()
    _write_owner_state(True, _TIMER_ID)
    print("========================================")
    print("ZAGENT ARCMAP LIVE BRIDGE STARTED")
    print("Timer ID : {0}".format(_TIMER_ID))
    print("Interval : {0} ms".format(interval_ms))
    print("MXD      : CURRENT")
    print("Auto Save: DISABLED")
    print("========================================")
    return _TIMER_ID

def stop_bridge():
    global _TIMER_ID, _TIMER_CALLBACK
    if not _TIMER_ID:
        _release_owner_mutex()
        print("ZAGENT ARCMAP BRIDGE NOT RUNNING")
        return True
    result = _USER32.KillTimer(None, _TIMER_ID)
    if not result:
        raise RuntimeError("KillTimer failed; callback retained to avoid unsafe unload.")
    old = _TIMER_ID
    _TIMER_ID = None
    _TIMER_CALLBACK = None
    _write_owner_state(False, None)
    _release_owner_mutex()
    print("ZAGENT ARCMAP LIVE BRIDGE STOPPED: {0}".format(old))
    return bool(result)

def bridge_status():
    mxd = get_mxd()
    status = {
        "running": bool(_TIMER_ID),
        "timer_id": _TIMER_ID,
        "timer_started_epoch": _TIMER_STARTED_EPOCH,
        "timer_callback_epoch": _LAST_TIMER_TICK_EPOCH,
        "timer_interval_ms": _TIMER_INTERVAL_MS,
        "heartbeat_sequence": _HEARTBEAT_SEQUENCE,
        "mxd": getattr(mxd, "filePath", ""),
        "auto_save": False,
        "safe_mode": bool(AGENT.get("safe_mode", True)),
        "product": "Zagent ArcMap",
        "version": "1.0.0",
        "owner_pid": os.getpid(),
        "owner_file": _OWNER_FILE,
        "context": bridge_state.context(mxd),
        "protocol_version": 2
    }
    print(status)
    return status
