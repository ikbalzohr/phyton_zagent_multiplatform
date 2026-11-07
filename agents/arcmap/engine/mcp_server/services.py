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
# Disk ArcPy calls serialize independently of the Desktop IPC owner.
_HEADLESS_LOCK = threading.RLock()

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

    def _inspection_context_locked(self):
        """Recheck authenticated ingress authority and expiry at point of use."""
        import time
        from .request_context import correlation
        from .execution_context import VerifiedContext, owner_key
        if not isinstance(correlation.get(), VerifiedContext):
            raise PermissionError('AUTHENTICATED_EXECUTION_CONTEXT_REQUIRED')
        ctx = current()
        if not ctx.get('principal_id') or not ctx.get('workspace_id') or not ctx.get('resource_id'):
            raise PermissionError('AUTHENTICATED_EXECUTION_CONTEXT_REQUIRED')
        if time.time() >= ctx.get('expires_at', 0):
            raise PermissionError('CONTEXT_EXPIRED_WHILE_QUEUED')
        if ctx.get('effective_access') not in ('read', 'write'):
            raise PermissionError('READ_SCOPE_REQUIRED')
        if not os.environ.get('ZAGENT_DEVICE_ID') or ctx.get('device_id') != os.environ['ZAGENT_DEVICE_ID']:
            raise PermissionError('IDENTITY_MISMATCH_OR_DEVICE_NOT_CONFIGURED')
        resources = [r for r in ctx.get('effective_resources', []) if r.get('kind') in ('arcmap', 'gis')]
        if len(resources) != 1 or resources[0].get('resource_id') != ctx['resource_id']:
            raise PermissionError('ONE_ARCMAP_RESOURCE_REQUIRED')
        if ctx.get('session_id') != owner_key(ctx):
            raise PermissionError('OWNER_CONTEXT_MISMATCH')
        return ctx

    def execution_capabilities(self):
        """Authenticated static contract; never waits for Desktop or disk work."""
        self._inspection_context_locked()
        return {
            'ok': True, 'status': 'source_only', 'deployment_verified': False,
            'operations': {
                'inspect_map': {'supported': True, 'modes': ['headless', 'attached']},
                'export': {'supported': True, 'modes': ['headless'],
                           'operations': ['print_ready_template'],
                           'attached_supported': False,
                           'print_ready_accepted_by_export': False},
                'mutation': {'supported': False, 'reason': 'UNSUPPORTED_IN_MVP'},
                'ui_control': {'supported': False, 'reason': 'ATTACHED_ONLY_LEGACY_TOOLS'},
            },
            'filesystem_sandbox': False,
            'authority': 'authenticated ArcMap/GIS resource; not the Files profile',
            'runtime_readiness': 'NOT_PROBED',
            'legacy_tools': 'unchanged defaults; not implicitly dual-mode',
        }

    def inspect_mxd(self, *, mxd_path):
        """One authenticated disk read; never contacts the UI bridge."""
        from .execution_modes import mxd_error
        from orchestrator.adapters.file_worker.arcgis_process import ArcGISProcessFileWorker
        with _HEADLESS_LOCK:
            self._inspection_context_locked()
            code = mxd_error(mxd_path)
            if code:
                return {'ok': False, 'code': code}
            worker = ArcGISProcessFileWorker(Path(__file__).resolve().parents[1], timeout_seconds=300)
            return worker.inspect_mxd(mxd_path=mxd_path)

    def print_ready_template(self, *, template_mxd, data_root, output_root,
                             scale=70000, dpi=400, main_frame='Layers',
                             expected_crs='WGS_1984_UTM_Zone_51N'):
        """Authenticated headless/disk export; never contacts the CURRENT bridge."""
        from orchestrator.adapters.file_worker.arcgis_process import ArcGISProcessFileWorker
        with _HEADLESS_LOCK:
            ctx = self._inspection_context_locked()
            if ctx.get('effective_access') != 'write':
                raise PermissionError('WRITE_SCOPE_REQUIRED')
            if self.upstream_read_only:
                return {'ok': False, 'code': 'DEV_UPSTREAM_READ_ONLY'}
            for required_kind in ('save', 'export'):
                blocked = self.safety.guard(required_kind)
                if blocked:
                    return blocked
            worker = ArcGISProcessFileWorker(Path(__file__).resolve().parents[1], timeout_seconds=300)
            return worker.print_ready_template(
                template_mxd=template_mxd, data_root=data_root,
                output_root=output_root, scale=scale, dpi=dpi,
                main_frame=main_frame, expected_crs=expected_crs)

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
            required_kinds = [kind]
            if action in ('stage3_build_blank_a4', 'stage3_build_no_data_a4'):
                # Builders always clear layers, even when no input data is used.
                required_kinds.append('destructive')
                if payload.get('save_mxd', True):
                    required_kinds.append('save')
                if payload.get('export_pdf', True) or payload.get('export_png', True):
                    required_kinds.append('export')
            elif action == 'stage3_blank_init' and payload.get('clear_layers', True):
                required_kinds.append('destructive')
            elif action == 'stage3_restore_checkpoint':
                # Restoring copies over an MXD on disk; it is not a live reopen.
                required_kinds.append('save')
            for required_kind in required_kinds:
                blocked = self.safety.guard(required_kind)
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
                    try:
                        observed = self._send(
                            "inspect_current_map",
                            _expected_context=payload.get(
                                "_expected_context"
                            ),
                        )
                    except ArcMapBridgeError as exc:
                        # The action already succeeded. Do not erase that fact
                        # when its independent observation channel is unavailable.
                        observed = {"ok": False, "error": str(exc)}
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