# -*- coding: utf-8 -*-
from __future__ import print_function
import json
import os
import shutil
import time
import traceback
from .config import IPC_ROOT, AGENT

IPC_DIR = IPC_ROOT
INBOX = os.path.join(IPC_DIR, "inbox")
OUTBOX = os.path.join(IPC_DIR, "outbox")
ARCHIVE = os.path.join(IPC_DIR, "archive")
LOGS = os.path.join(IPC_DIR, "logs")

def ensure_dirs():
    for p in (IPC_DIR, INBOX, OUTBOX, ARCHIVE, LOGS):
        if not os.path.isdir(p):
            os.makedirs(p)

def _read_json(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    if not isinstance(raw, str):
        raw = raw.decode("utf-8")
    return json.loads(raw)

def _write_json_atomic(path, data):
    temp = path + ".tmp"
    raw = json.dumps(data, indent=2, ensure_ascii=False)
    if not isinstance(raw, bytes):
        raw = raw.encode("utf-8")
    with open(temp, "wb") as fh:
        fh.write(raw)
    if os.path.exists(path):
        os.remove(path)
    os.rename(temp, path)

def list_commands():
    ensure_dirs()
    names = [n for n in os.listdir(INBOX) if n.lower().endswith(".json")]
    names.sort(key=lambda name: os.path.getmtime(os.path.join(INBOX, name)))
    return [os.path.join(INBOX, n) for n in names]

def archive_command(path):
    if not AGENT.get("archive_ipc", True):
        try:
            os.remove(path)
        except Exception:
            pass
        return
    ensure_dirs()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = os.path.join(ARCHIVE, stamp + "_" + os.path.basename(path))
    try:
        shutil.move(path, target)
    except Exception:
        try:
            os.remove(path)
        except Exception:
            pass

def write_result(request_id, result):
    ensure_dirs()
    _write_json_atomic(os.path.join(OUTBOX, request_id + ".json"), result)

def log_error(request_id, exc):
    ensure_dirs()
    path = os.path.join(LOGS, "bridge_errors.log")
    try:
        with open(path, "ab") as fh:
            text = "[{0}] {1}: {2}\n{3}\n".format(
                time.strftime("%Y-%m-%d %H:%M:%S"), request_id,
                str(exc), traceback.format_exc())
            if not isinstance(text, bytes):
                text = text.encode("utf-8", "replace")
            fh.write(text)
    except Exception:
        pass
def quarantine_stale():
    """Never replay requests from an old/disconnected MCP process."""
    ensure_dirs()
    count = 0
    for path in list_commands():
        try:
            command = _read_json(path)
            deadline = command.get("expires_at_epoch")
            if isinstance(deadline, (int, float)) and deadline > time.time():
                continue
            archive_command(path)
            count += 1
        except (IOError, OSError, ValueError):
            archive_command(path)
            count += 1
    return count
