import os

from ..request_context import current
from ..services import _ARCMAP_LOCK
from ..visual_store import publish, staging_path
from ..window_capture import WindowCaptureError, capture_arcmap_window

def register(mcp, s):
    @mcp.tool()
    def arcmap_window_capture(confirm_current_arcmap_window: bool = False,
                              name: str = "arcmap-window",
                              label: str = "",
                              session_id: str = ""):
        if not confirm_current_arcmap_window:
            return {"ok": False, "code": "WINDOW_CAPTURE_CONFIRMATION_REQUIRED",
                    "error": "Set confirm_current_arcmap_window=true to capture the CURRENT ArcMap window."}
        with _ARCMAP_LOCK:
            session = current().get("session_id")
            if not session or (session_id and session_id != session):
                return {"ok": False, "code": "SESSION_IDENTITY_MISMATCH",
                        "error": "Capture requires the authoritative Tunnel session."}
            before = s.call("ping")
            if not before.get("ok"):
                return before
            context = before.get("context") or {}
            output_path = staging_path(name or "arcmap-window", ".png")
            try:
                capture = capture_arcmap_window(int(context.get("pid") or 0), output_path)
                after = s.call("ping")
                if not after.get("ok"):
                    return after
                if after.get("context") != context:
                    return {"ok": False, "code": "CURRENT_MXD_CHANGED",
                            "error": "Capture discarded because the live ArcMap context changed."}
                return publish(output_path, source="arcmap", kind="arcmap_application_window",
                               label=label or None, session_id=session,
                               metadata={"window": capture, "context": context,
                                         "mxd_source": before.get("mxd"), "saved": False})
            except WindowCaptureError as exc:
                return {"ok": False, "code": exc.code, "error": str(exc), "details": exc.details}
            finally:
                if os.path.isfile(output_path):
                    os.remove(output_path)
