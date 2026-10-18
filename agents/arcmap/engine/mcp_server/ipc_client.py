import json
import os
import time
import uuid
from pathlib import Path

from .config import IPC_ROOT, DATA_ROOT, AGENT
from .request_context import current

DEFAULT_TIMEOUT = float(AGENT.get("command_timeout_seconds", 15))


class ArcMapBridgeError(RuntimeError):
    pass


def _channel(ipc_root, data_root):
    ipc = Path(ipc_root)
    data = Path(data_root)
    return {
        "ipc": ipc,
        "inbox": ipc / "inbox",
        "outbox": ipc / "outbox",
        "archive": ipc / "archive",
        "owner": data / "runtime" / "arcmap-owner.json",
    }


def _ensure_channel_dirs(channel):
    for p in (
        channel["ipc"],
        channel["inbox"],
        channel["outbox"],
        channel["archive"],
    ):
        p.mkdir(parents=True, exist_ok=True)


def ensure_dirs():
    _ensure_channel_dirs(_channel(IPC_ROOT, DATA_ROOT))


def _write_atomic(path: Path, data):
    tmp = path.with_suffix(path.suffix + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(str(tmp), str(path))


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_owner_json(owner_path: Path, attempts=8, delay=0.005):
    attempts = max(1, int(attempts))
    for index in range(attempts):
        owner = _read_json(owner_path)
        if isinstance(owner, dict) and owner:
            return owner
        if index + 1 < attempts:
            time.sleep(delay)
    return {}


def owner_status_for(data_root):
    owner_path = Path(data_root) / "runtime" / "arcmap-owner.json"
    owner = _read_owner_json(owner_path)
    age = max(
        0,
        time.time() - float(owner.get("updated_at_epoch", 0)),
    )
    return dict(
        owner,
        owner_file=str(owner_path),
        heartbeat_age_seconds=age,
        healthy=bool(owner.get("running")) and age <= 10,
    )


def owner_status():
    return owner_status_for(DATA_ROOT)


def send_command_via(
    ipc_root,
    data_root,
    action,
    timeout=DEFAULT_TIMEOUT,
    **payload
):
    channel = _channel(ipc_root, data_root)
    _ensure_channel_dirs(channel)

    request_id = str(uuid.uuid4())
    correlation = current()
    mcp_send_enter_epoch = time.time()
    expected = payload.pop("_expected_context", None)
    owner = owner_status_for(data_root)

    timing = {
        "mcp_receive_epoch": correlation.get("mcp_receive_epoch"),
        "mcp_tool_name": correlation.get("mcp_tool_name"),
        "mcp_send_enter_epoch": mcp_send_enter_epoch,
        "owner_checked_epoch": time.time(),
        "owner_heartbeat_epoch": owner.get("updated_at_epoch"),
        "owner_heartbeat_age_ms": round(
            float(owner.get("heartbeat_age_seconds", 0.0) or 0.0)
            * 1000.0,
            3,
        ),
    }

    if action not in ("ping", "status"):
        if not owner["healthy"]:
            raise ArcMapBridgeError(
                "BRIDGE_OFFLINE: no fresh UI-thread heartbeat; "
                "command not queued."
            )
        expected = expected or owner.get("context")
        if not expected:
            raise ArcMapBridgeError(
                "BRIDGE_PROTOCOL_REQUIRED: reconnect updated Add-In "
                "before actions."
            )

    timeout = max(0.1, min(float(timeout), 300))
    command = dict(payload)
    command["correlation"] = correlation
    command["timing"] = timing
    command.update(
        request_id=request_id,
        action=action,
        created_at_epoch=time.time(),
        expires_at_epoch=time.time() + timeout,
        _expected_context=expected,
    )

    command_path = channel["inbox"] / (request_id + ".json")
    result_path = channel["outbox"] / (request_id + ".json")
    timing["ipc_enqueue_epoch"] = time.time()
    _write_atomic(command_path, command)

    started = time.monotonic()
    while True:
        result = _read_json(result_path)
        if (
            isinstance(result, dict)
            and result.get("request_id") == request_id
        ):
            result_path.unlink(missing_ok=True)
            result_timing = result.setdefault("timing", {})
            result_timing["mcp_result_read_epoch"] = time.time()
            receive_epoch = result_timing.get("mcp_receive_epoch")
            if isinstance(receive_epoch, (int, float)):
                result_timing["mcp_total_ms"] = round(
                    (
                        result_timing["mcp_result_read_epoch"]
                        - receive_epoch
                    )
                    * 1000.0,
                    3,
                )
            return result

        if time.monotonic() - started >= timeout:
            try:
                command_path.unlink()
                outcome = "not executed (removed from queue)"
            except FileNotFoundError:
                outcome = (
                    "execution outcome unknown; inspect state "
                    "before retrying"
                )
            raise ArcMapBridgeError(
                "BRIDGE_TIMEOUT after %gs: %s. No automatic replay."
                % (timeout, outcome)
            )
        time.sleep(0.05)


def send_command(action, timeout=DEFAULT_TIMEOUT, **payload):
    return send_command_via(
        IPC_ROOT,
        DATA_ROOT,
        action,
        timeout=timeout,
        **payload
    )
