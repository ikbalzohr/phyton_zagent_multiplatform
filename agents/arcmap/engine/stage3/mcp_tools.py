# -*- coding: utf-8 -*-
from __future__ import annotations

import inspect
import os
import sys
from typing import Any, Dict, List, Optional

STAGE3_TOOL_NAMES = [
    "arcmap_stage3_health",
    "arcmap_stage3_blank_init",
    "arcmap_stage3_ensure_dataframe",
    "arcmap_stage3_set_page_a4",
    "arcmap_stage3_create_text",
    "arcmap_stage3_create_neatline",
    "arcmap_stage3_create_legend",
    "arcmap_stage3_create_north_arrow",
    "arcmap_stage3_create_scale_bar",
    "arcmap_stage3_create_featureclass",
    "arcmap_stage3_create_xy_featureclass",
    "arcmap_stage3_create_geometry_features",
    "arcmap_stage3_add_dataset_auto",
    "arcmap_stage3_ingest_folder",
    "arcmap_stage3_set_extent_auto",
    "arcmap_stage3_build_blank_a4",
    "arcmap_stage3_build_no_data_a4",
    "arcmap_stage3_save_checkpoint",
    "arcmap_stage3_restore_checkpoint",
    "arcmap_stage3_export_current",
]


_RUNTIME_NAMESPACE: Dict[str, Any] = {}


def _invoke_transport(fn, action: str, payload: Dict[str, Any]) -> Any:
    command = dict(payload or {})
    command["action"] = action
    attempts = [
        # Preferred signature for Zagent ArcMap IPC:
        # send_command(action, timeout=..., **payload)
        lambda: fn(action, **payload),
        lambda: fn(action=action, **payload),
        # Command-object transports are the next safest fallback.
        lambda: fn(command),
        lambda: fn(command=command),
        # Legacy payload-object signatures are last because a function with a
        # positional timeout parameter can otherwise accept payload silently.
        lambda: fn(action, payload),
        lambda: fn(action=action, payload=payload),
    ]
    last_type_error = None
    for call in attempts:
        try:
            return call()
        except TypeError as exc:
            last_type_error = exc
    if last_type_error is not None:
        raise last_type_error
    raise RuntimeError("No compatible transport signature")


def _service_transport_candidates() -> List[Any]:
    out: List[Any] = []
    services = _RUNTIME_NAMESPACE.get("services")
    if services is None:
        return out

    names = (
        "send_command", "_send_command",
        "call_bridge", "_call_bridge",
        "bridge_request", "_bridge_request",
        "request_bridge", "_request_bridge",
        "invoke_bridge", "_invoke_bridge",
    )
    for name in names:
        fn = getattr(services, name, None)
        if callable(fn):
            out.append(fn)

    for child_name in ("bridge", "client", "ipc", "transport", "bridge_client"):
        child = getattr(services, child_name, None)
        if child is None:
            continue
        for name in names:
            fn = getattr(child, name, None)
            if callable(fn):
                out.append(fn)
    return out


def _send(action: str, payload: Optional[Dict[str, Any]] = None) -> Any:
    payload = dict(payload or {})
    errors: List[str] = []

    # 1) Prefer the transport already owned by the running AgentServices object.
    for fn in _service_transport_candidates():
        try:
            return _invoke_transport(fn, action, payload)
        except TypeError as exc:
            errors.append("services transport signature: %r" % (exc,))
        except Exception:
            # A non-signature exception means we found a real transport and the
            # bridge itself returned/raised an operational error. Preserve it.
            raise

    # 2) Known IPC module names used by earlier ArcMap Agent builds.
    candidates = [
        ("mcp_server.ipc_client", "send_command"),
        ("ipc_client", "send_command"),
    ]
    for mod_name, fn_name in candidates:
        try:
            mod = __import__(mod_name, fromlist=[fn_name])
            fn = getattr(mod, fn_name)
            return _invoke_transport(fn, action, payload)
        except (ImportError, AttributeError) as exc:
            errors.append("%s.%s: %r" % (mod_name, fn_name, exc))
        except TypeError as exc:
            errors.append("%s.%s signature: %r" % (mod_name, fn_name, exc))
        except Exception:
            raise

    # 3) Last-resort scan for a specifically named send_command function.
    for mod in list(sys.modules.values()):
        if mod is None:
            continue
        fn = getattr(mod, "send_command", None)
        if callable(fn):
            try:
                return _invoke_transport(fn, action, payload)
            except TypeError as exc:
                errors.append("loaded.%s.send_command: %r" % (getattr(mod, "__name__", "?"), exc))
            except Exception:
                raise

    raise RuntimeError("Stage3 could not find MCP->Bridge transport. " + " | ".join(errors[-8:]))


def arcmap_stage3_health() -> Any:
    """Check Stage 3 bridge installation, ArcObjects layout backend, and current document readiness."""
    return _send("stage3_health")


def arcmap_stage3_blank_init(clear_layers: bool = True, dataframe_name: str = "Layers", document_title: str = "") -> Any:
    """Initialize the CURRENT ArcMap document as a clean Stage 3 workspace."""
    return _send("stage3_blank_init", locals())


def arcmap_stage3_ensure_dataframe(name: str = "Layers", spatial_reference: str = "", activate: bool = True) -> Any:
    """Ensure a usable data frame exists and optionally apply a spatial reference."""
    return _send("stage3_ensure_dataframe", locals())


def arcmap_stage3_set_page_a4(orientation: str = "landscape", units: str = "centimeters") -> Any:
    """Configure the current layout page for A4 portrait or landscape."""
    return _send("stage3_set_page_a4", locals())


def arcmap_stage3_create_text(text: str, name: str = "ZAGENT_TEXT", x_frac: float = 0.5, y_frac: float = 0.95,
                              font_size: float = 14.0, bold: bool = False, anchor: str = "CENTER") -> Any:
    """Create a new layout text element at a relative page position."""
    return _send("stage3_create_text", locals())


def arcmap_stage3_create_neatline(name: str = "ZAGENT_NEATLINE", margin_frac: float = 0.02, line_width: float = 1.0) -> Any:
    """Create an outer layout neatline."""
    return _send("stage3_create_neatline", locals())


def arcmap_stage3_create_legend(name: str = "ZAGENT_LEGEND", x_frac: float = 0.78, y_frac: float = 0.20,
                                width_frac: float = 0.20, height_frac: float = 0.42, title: str = "LEGENDA") -> Any:
    """Create a legend linked to the active data frame."""
    return _send("stage3_create_legend", locals())


def arcmap_stage3_create_north_arrow(name: str = "ZAGENT_NORTH_ARROW", x_frac: float = 0.92, y_frac: float = 0.82,
                                     size_frac: float = 0.08) -> Any:
    """Create a north arrow in the layout."""
    return _send("stage3_create_north_arrow", locals())


def arcmap_stage3_create_scale_bar(name: str = "ZAGENT_SCALE_BAR", x_frac: float = 0.38, y_frac: float = 0.06,
                                   width_frac: float = 0.26, units: str = "meters") -> Any:
    """Create a scale bar in the layout."""
    return _send("stage3_create_scale_bar", locals())


def arcmap_stage3_create_featureclass(workspace: str, name: str, geometry_type: str,
                                      spatial_reference: str = "", fields: Optional[List[Dict[str, Any]]] = None) -> Any:
    """Create a new feature class for POINT, POLYLINE, or POLYGON geometry."""
    return _send("stage3_create_featureclass", locals())


def arcmap_stage3_create_xy_featureclass(csv_path: str, out_featureclass: str, x_field: str, y_field: str,
                                         spatial_reference: str = "EPSG:4326", z_field: str = "") -> Any:
    """Create a persistent feature class from X/Y coordinates in CSV or DBF."""
    return _send("stage3_create_xy_featureclass", locals())


def arcmap_stage3_create_geometry_features(out_featureclass: str, geometry_type: str,
                                           features: List[Dict[str, Any]], spatial_reference: str = "EPSG:4326") -> Any:
    """Create geometry from JSON-like point/path/ring coordinate definitions."""
    return _send("stage3_create_geometry_features", locals())


def arcmap_stage3_add_dataset_auto(path: str, dataframe_name: str = "", layer_name: str = "", position: str = "TOP") -> Any:
    """Add SHP, raster, layer file, or geodatabase dataset to the current map."""
    return _send("stage3_add_dataset_auto", locals())


def arcmap_stage3_ingest_folder(data_root: str, recursive: bool = True, add_to_map: bool = True,
                                max_items: int = 500, dataframe_name: str = "") -> Any:
    """Discover and optionally add supported GIS datasets from a folder tree."""
    return _send("stage3_ingest_folder", locals())


def arcmap_stage3_set_extent_auto(padding_percent: float = 5.0, dataframe_name: str = "") -> Any:
    """Set the active data frame extent to all visible layers with optional padding."""
    return _send("stage3_set_extent_auto", locals())


def arcmap_stage3_build_blank_a4(output_dir: str, base_name: str = "ZAGENT_STAGE3_MAP", data_root: str = "",
                                 orientation: str = "landscape", title: str = "PETA",
                                 spatial_reference: str = "", scale: float = 0.0,
                                 include_legend: bool = True, include_north_arrow: bool = True,
                                 include_scale_bar: bool = True, save_mxd: bool = True,
                                 export_pdf: bool = True, export_png: bool = True) -> Any:
    """Build an A4 map from the CURRENT blank document and optional raw-data folder."""
    return _send("stage3_build_blank_a4", locals())


def arcmap_stage3_build_no_data_a4(output_dir: str, base_name: str = "ZAGENT_STAGE3_EMPTY_MAP",
                                   orientation: str = "landscape", title: str = "PETA",
                                   subtitle: str = "", save_mxd: bool = True,
                                   export_pdf: bool = True, export_png: bool = True) -> Any:
    """Build and export an A4 layout even when no GIS dataset is available."""
    return _send("stage3_build_no_data_a4", locals())


def arcmap_stage3_save_checkpoint(snapshot_root: str, label: str = "checkpoint") -> Any:
    """Persist a full-MXD Stage 3 checkpoint to disk."""
    return _send("stage3_save_checkpoint", locals())


def arcmap_stage3_restore_checkpoint(checkpoint_mxd: str, target_mxd: str = "") -> Any:
    """Restore a Stage 3 MXD checkpoint to a target path."""
    return _send("stage3_restore_checkpoint", locals())


def arcmap_stage3_export_current(output_path: str, format: str = "PDF", resolution: int = 400) -> Any:
    """Export the current layout to PDF, PNG, JPEG, or TIFF."""
    return _send("stage3_export_current", locals())


_TOOL_FUNCS = [globals()[name] for name in STAGE3_TOOL_NAMES]


def _find_server_object(namespace: Dict[str, Any]):
    preferred = ["mcp", "server", "app"]
    for name in preferred:
        obj = namespace.get(name)
        if obj is not None and (hasattr(obj, "tool") or hasattr(obj, "add_tool")):
            return obj
    for obj in namespace.values():
        if obj is not None and (hasattr(obj, "tool") or hasattr(obj, "add_tool")):
            return obj
    return None


def auto_install(namespace: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Register Stage 3 tools without replacing existing MCP tools."""
    global _RUNTIME_NAMESPACE
    if namespace is None:
        frame = inspect.currentframe()
        try:
            namespace = frame.f_back.f_globals if frame and frame.f_back else globals()
        finally:
            del frame
    namespace = dict(namespace or {})
    _RUNTIME_NAMESPACE = namespace

    server = _find_server_object(namespace)
    if server is None:
        raise RuntimeError("Stage3 MCP installer could not locate MCP server object in caller globals")

    installed = []
    skipped = []
    existing_names = set()
    for attr in ("_tool_manager", "tool_manager"):
        mgr = getattr(server, attr, None)
        if mgr is not None:
            for a in ("_tools", "tools"):
                tools_obj = getattr(mgr, a, None)
                if isinstance(tools_obj, dict):
                    existing_names.update(tools_obj.keys())

    for fn in _TOOL_FUNCS:
        name = fn.__name__
        if name in existing_names:
            skipped.append(name)
            continue

        registered = False
        errors = []
        if hasattr(server, "tool"):
            # FastMCP/MCPServer builds normally accept an explicit name.
            try:
                server.tool(name=name)(fn)
                registered = True
            except TypeError as exc:
                errors.append(repr(exc))
                try:
                    server.tool()(fn)
                    registered = True
                except Exception as exc2:
                    errors.append(repr(exc2))
            except Exception as exc:
                errors.append(repr(exc))

        if not registered and hasattr(server, "add_tool"):
            try:
                server.add_tool(fn)
                registered = True
            except Exception as exc:
                errors.append(repr(exc))

        if not registered:
            raise RuntimeError("Could not register MCP tool %s: %s" % (name, " | ".join(errors)))
        installed.append(name)
        existing_names.add(name)

    return {
        "ok": True,
        "installed": installed,
        "skipped": skipped,
        "count": len(installed) + len(skipped),
        "tool_names": list(STAGE3_TOOL_NAMES),
        "services_detected": namespace.get("services") is not None,
    }

