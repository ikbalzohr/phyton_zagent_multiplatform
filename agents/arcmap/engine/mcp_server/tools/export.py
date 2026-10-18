import os
from ..request_context import current
from ..services import _ARCMAP_LOCK

from ..visual_store import latest, list_artifacts, prune, publish, staging_path, visual_root


def register(mcp, s):
    @mcp.tool()
    def arcmap_export_pdf(output_path: str, resolution: int = 400, overwrite: bool = False):
        """Export CURRENT layout to PDF. Does not save MXD."""
        return s.call("export_pdf", "export", output_path=output_path,
                      resolution=resolution, overwrite=overwrite, timeout=60)

    @mcp.tool()
    def arcmap_export_png(output_path: str, resolution: int = 400, overwrite: bool = False):
        """Export CURRENT layout to PNG. Does not save MXD."""
        return s.call("export_png", "export", output_path=output_path,
                      resolution=resolution, overwrite=overwrite, timeout=60)

    @mcp.tool()
    def arcmap_export_jpeg(output_path: str, resolution: int = 400,
                           jpeg_quality: int = 90, overwrite: bool = False):
        """Export CURRENT layout to JPEG. Does not save MXD."""
        return s.call("export_jpeg", "export", output_path=output_path,
                      resolution=resolution, jpeg_quality=jpeg_quality, overwrite=overwrite,
                      timeout=60)

    @mcp.tool()
    def arcmap_visual_snapshot(name: str = "arcmap", resolution: int = 200,
                               label: str = "", session_id: str = "", data_frame: str = ""):
        """Export CURRENT layout to PNG and publish it to the shared Zagent visual store."""
        with _ARCMAP_LOCK:
            session = current().get("session_id")
            if not session or (session_id and session_id != session):
                return {"ok": False, "code": "SESSION_IDENTITY_MISMATCH",
                        "error": "Snapshot requires the authoritative Tunnel session."}
            before = s.call("inspect_current_map")
            if not before.get("ok"):
                return before
            output_path = staging_path(name or "arcmap", ".png")
            try:
                result = s.call("export_png", "export", output_path=output_path,
                                resolution=resolution, overwrite=False, data_frame=data_frame,
                                _expected_context=before.get("context"), timeout=60)
                if not result.get("ok"):
                    return result
                if result.get("context") != before.get("context"):
                    return {"ok": False, "code": "CURRENT_MXD_CHANGED",
                            "error": "Snapshot discarded because document changed."}
                return publish(output_path, source="arcmap",
                    kind="arcmap_dataframe" if data_frame else "arcmap_layout",
                    label=label or None, session_id=session,
                    metadata={"resolution": int(resolution), "arcmap_result": result,
                              "state": before, "mxd_source": before.get("document_path"),
                              "data_frame": data_frame or None})
            finally:
                if os.path.isfile(output_path):
                    os.remove(output_path)

    @mcp.tool()
    def arcmap_visual_latest():
        """Return the newest artifact in the shared Zagent visual store."""
        return {"root": visual_root(), "artifact": latest(source="arcmap")}

    @mcp.tool()
    def arcmap_visual_list(source: str = "", limit: int = 50):
        """List recent shared visual artifacts without returning image bytes."""
        return {
            "root": visual_root(),
            "artifacts": list_artifacts(source=source or None, limit=limit),
        }

    @mcp.tool()
    def arcmap_visual_prune(max_artifacts: int = 200, max_age_hours: float = 0.0):
        """Prune old shared visual artifacts by count and optional age."""
        return prune(
            max_artifacts=max_artifacts,
            max_age_hours=max_age_hours if max_age_hours > 0 else None,
        )