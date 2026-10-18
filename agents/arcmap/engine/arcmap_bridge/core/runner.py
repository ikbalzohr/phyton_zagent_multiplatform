# -*- coding: utf-8 -*-
from __future__ import print_function
import os
import time
from . import ipc
from .dispatcher import dispatch
from .bridge_state import validate

def process_next():
    files = ipc.list_commands()
    if not files:
        return False
    path = files[0]
    request_id = os.path.splitext(os.path.basename(path))[0]
    timing = {}
    try:
        # Claim before executing: a timeout can remove unclaimed work safely.
        claimed = path + ".processing"
        try:
            os.rename(path, claimed)
        except OSError:
            return True
        path = claimed
        claim_epoch = time.time()
        command = ipc._read_json(path)
        timing = command.setdefault("timing", {})
        timing["addin_claim_epoch"] = claim_epoch
        timing["addin_command_read_epoch"] = time.time()
        if command.get("request_id") != request_id:
            raise ValueError("IPC request ID does not match filename.")

        timing["current_mxd_validate_start_epoch"] = time.time()
        result = validate(command)
        timing["current_mxd_validate_end_epoch"] = time.time()

        if result is None:
            timing["dispatch_start_epoch"] = time.time()
            result = dispatch(command)
            timing["dispatch_end_epoch"] = time.time()

        result["request_id"] = request_id
        result["correlation"] = command.get("correlation") or {}
        result["timing"] = timing
        timing["result_write_epoch"] = time.time()
        ipc.write_result(request_id, result)
    except Exception as exc:
        timing["error_epoch"] = time.time()
        ipc.log_error(request_id, exc)
        ipc.write_result(request_id, {
            "ok": False,
            "request_id": request_id,
            "error": str(exc),
            "timing": timing
        })
    finally:
        ipc.archive_command(path)
    return True
