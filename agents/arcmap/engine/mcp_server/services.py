import os
import threading
from pathlib import Path

from .ipc_client import (
    send_command,
    send_command_via,
    ArcMapBridgeError,
    owner_status,
    owner_status_for,
)
from .safety import SafetyPolicy
from .request_context import current
from .config import AGENT

_ARCMAP_LOCK = threading.RLock()

_ENVIRONMENT = os.environ.get("ZAGENT_ENVIRONMENT", "").strip().upper()
_UPSTREAM_IPC_ROOT = os.environ.get(
    "ZAGENT_ARCMAP_UPSTREAM_IPC_ROOT",
    "",
).strip()
_UPSTREAM_DATA_ROOT = os.environ.get(
    "ZAGENT_ARCMAP_UPSTREAM_DATA_ROOT",
    "",
).strip()
_UPSTREAM_READ_ONLY = (
    _ENVIRONMENT == "DEVELOPMENT"
    and bool(_UPSTREAM_IPC_ROOT)
    and bool(_UPSTREAM_DATA_ROOT)
)


class AgentServices:
    def __init__(self):
        self.safety = SafetyPolicy()

    @property
    def upstream_read_only(self):
        return _UPSTREAM_READ_ONLY

    def bridge_owner_status(self):
        """Return authoritative ArcMap bridge owner state.

        Development may observe the Production-owned bridge through a
        read-only upstream IPC channel. No second ArcMap bridge owner is
        created.
        """
        if self.upstream_read_only:
            status = owner_status_for(_UPSTREAM_DATA_ROOT)
            status["bridge_mode"] = "UPSTREAM_READ_ONLY"
            status["upstream_ipc_root"] = _UPSTREAM_IPC_ROOT
            return status
        status = owner_status()
        status["bridge_mode"] = "LOCAL_OWNER"
        return status

    def _send(self, action, **payload):
        if self.upstream_read_only:
            return send_command_via(
                Path(_UPSTREAM_IPC_ROOT),
                Path(_UPSTREAM_DATA_ROOT),
                action,
                **payload
            )
        return send_command(action, **payload)

    def _health(self):
        if not AGENT.get("require_health_check", True):
            return None
        try:
            r = self._send("ping", timeout=3)
            if not r.get("ok"):
                return {
                    "ok": False,
                    "error": "ArcMap bridge health check failed.",
                    "details": r,
                }
        except ArcMapBridgeError as exc:
            return {"ok": False, "error": str(exc)}
        return None

    def call(self, action, kind="read", **payload):
        # One UI-bound ArcMap owner; context expiry is rechecked under lock.
        with _ARCMAP_LOCK:
            return self._call_locked(action, kind, **payload)

    def _call_locked(self, action, kind="read", **payload):
        import time
        ctx = current()
        if not ctx.get('principal_id') or not ctx.get('workspace_id') or not ctx.get('resource_id'):
            raise PermissionError('AUTHENTICATED_EXECUTION_CONTEXT_REQUIRED')
        if time.time() >= ctx.get('expires_at', 0):
            raise PermissionError('CONTEXT_EXPIRED_WHILE_QUEUED')
        if kind != 'read' and ctx.get('effective_access') != 'write':
            raise PermissionError('WRITE_SCOPE_REQUIRED')
        if self.upstream_read_only and kind != "read":
            return {
                "ok": False,
                "code": "DEV_UPSTREAM_READ_ONLY",
                "error": (
                    "Zagent Dev is connected to the Production-owned ArcMap "
                    "bridge in read-only upstream mode. Dev write/control "
                    "operations are blocked to protect Production ownership."
                ),
                "bridge_mode": "UPSTREAM_READ_ONLY",
                "upstream_production_unchanged": True,
            }

        if kind != "read":
            blocked = self.safety.guard(kind)
            if blocked:
                return blocked
            try:
                health = self._send("ping", timeout=3)
                if not health.get("ok"):
                    return health
                expected = payload.get("_expected_context")
                if expected and expected != health.get("context"):
                    return {
                        "ok": False,
                        "code": "CURRENT_MXD_CHANGED",
                        "error": "Document changed after observation.",
                    }
                payload["_expected_context"] = (
                    expected or health.get("context") or {}
                )
            except ArcMapBridgeError as exc:
                return {"ok": False, "error": str(exc)}

        try:
            result = self._send(action, **payload)
            if isinstance(result, dict):
                result.setdefault("safety", self.safety.status())
                result.setdefault(
                    "bridge_mode",
                    (
                        "UPSTREAM_READ_ONLY"
                        if self.upstream_read_only
                        else "LOCAL_OWNER"
                    ),
                )
                if kind == "live_write" and result.get("ok"):
                    observed = self._send(
                        "inspect_current_map",
                        _expected_context=payload.get(
                            "_expected_context"
                        ),
                    )
                    result["verification"] = {
                        "status": (
                            "OBSERVED"
                            if observed.get("ok")
                            else "FAILED"
                        ),
                        "state": observed,
                        "saved": False,
                    }
                    if not observed.get("ok"):
                        result["ok"] = False
                        result["code"] = (
                            "POST_ACTION_VERIFICATION_FAILED"
                        )
                        result["action_may_have_completed"] = True
            return result
        except ArcMapBridgeError as exc:
            return {
                "ok": False,
                "error": str(exc),
                "safety": self.safety.status(),
                "bridge_mode": (
                    "UPSTREAM_READ_ONLY"
                    if self.upstream_read_only
                    else "LOCAL_OWNER"
                ),
            }
