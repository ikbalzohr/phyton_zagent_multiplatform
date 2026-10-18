# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import arcpy

from core.registry import action
from core.current_map import get_mxd
from core.safety import require_export
from core.path_guard import guard_manual_write
from features.export import _export


def _safe_get(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _prepare(path, overwrite):
    blocked = guard_manual_write(path, "output_path")
    if blocked:
        return blocked
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    if os.path.exists(path) and not overwrite:
        return {
            "ok": False,
            "error": "Output exists and overwrite=False: {0}".format(path),
            "output_path": path
        }
    return None


def _page_size(mxd):
    value = _safe_get(mxd, "pageSize", None)
    width = _safe_get(value, "width", None) if value is not None else None
    height = _safe_get(value, "height", None) if value is not None else None
    if width is None or height is None:
        try:
            width, height = value[0], value[1]
        except Exception:
            pass
    try:
        width = float(width) if width is not None else None
        height = float(height) if height is not None else None
    except Exception:
        pass
    return {"width": width, "height": height}


def _broken_sources(mxd):
    rows = []
    try:
        for obj in arcpy.mapping.ListBrokenDataSources(mxd):
            rows.append({
                "name": _safe_get(obj, "name", "") or "",
                "data_source": _safe_get(obj, "dataSource", "") or ""
            })
    except Exception:
        pass
    return rows


@action("export_preflight")
def export_preflight(command):
    path = command.get("output_path", "") or ""
    if not path:
        return {"ok": False, "error": "output_path is required", "saved": False}
    blocked = guard_manual_write(path, "output_path")
    if blocked:
        blocked["saved"] = False
        return blocked

    mxd = get_mxd()
    broken = _broken_sources(mxd)
    folder = os.path.dirname(path)
    return {
        "ok": True,
        "output_path": path,
        "parent_folder": folder,
        "parent_exists": bool(folder and os.path.isdir(folder)),
        "output_exists": os.path.exists(path),
        "broken_data_source_count": len(broken),
        "broken_data_sources": broken,
        "page_size": _page_size(mxd),
        "ddp_enabled": bool(_safe_get(mxd, "isDDPEnabled", False)),
        "ready": len(broken) == 0,
        "saved": False
    }


@action("export_bundle")
def export_bundle(command):
    blocked = require_export()
    if blocked:
        return blocked

    output_dir = command.get("output_dir", "") or ""
    base_name = command.get("base_name", "") or ""
    if not output_dir or not base_name:
        return {"ok": False, "error": "output_dir and base_name are required"}

    # Prevent path traversal through base_name.
    clean_name = os.path.basename(base_name)
    if clean_name != base_name or clean_name in ("", ".", ".."):
        return {"ok": False, "error": "base_name must be a plain file stem"}

    if not os.path.isdir(output_dir):
        blocked = guard_manual_write(os.path.join(output_dir, clean_name + ".pdf"), "output_path")
        if blocked:
            return blocked
        os.makedirs(output_dir)

    mxd = get_mxd()
    resolution = int(command.get("resolution", 400))
    jpeg_quality = int(command.get("jpeg_quality", 90))
    overwrite = bool(command.get("overwrite", False))
    files = []

    specs = []
    if bool(command.get("include_pdf", True)):
        specs.append(("pdf", os.path.join(output_dir, clean_name + ".pdf")))
    if bool(command.get("include_png", True)):
        specs.append(("png", os.path.join(output_dir, clean_name + ".png")))
    if bool(command.get("include_jpeg", False)):
        specs.append(("jpeg", os.path.join(output_dir, clean_name + ".jpg")))

    # Preflight all paths before any file is written.
    for kind, path in specs:
        prep = _prepare(path, overwrite)
        if prep:
            return prep
    for kind, path in specs:
        result = _export(dict(command, output_path=path), kind)
        if not result.get("ok"):
            return dict(result, completed_files=files)
        files.append(dict(result, format=kind, path=path))

    return {"ok": True, "files": files, "saved": False}


@action("export_tiff")
def export_tiff(command):
    blocked = require_export()
    if blocked:
        return blocked

    path = command.get("output_path", "") or ""
    prep = _prepare(path, bool(command.get("overwrite", False)))
    if prep:
        return prep
    resolution = int(command.get("resolution", 400))
    arcpy.mapping.ExportToTIFF(get_mxd(), path, resolution=resolution)
    return {"ok": True, "output_path": path, "saved": False}


@action("get_data_driven_pages_state")
def get_data_driven_pages_state(command):
    mxd = get_mxd()
    enabled = bool(_safe_get(mxd, "isDDPEnabled", False))
    result = {
        "ok": True,
        "enabled": enabled,
        "page_count": 0,
        "current_page_id": None,
        "current_page_name": None,
        "saved": False
    }
    if not enabled:
        return result

    ddp = mxd.dataDrivenPages
    result["page_count"] = int(_safe_get(ddp, "pageCount", 0) or 0)
    result["current_page_id"] = _safe_get(ddp, "currentPageID", None)
    try:
        row = ddp.pageRow
        name_field = _safe_get(ddp, "pageNameField", None)
        field_name = _safe_get(name_field, "name", None)
        if field_name:
            result["current_page_name"] = getattr(row, field_name)
    except Exception:
        pass
    return result


@action("export_data_driven_pages_pdf")
def export_data_driven_pages_pdf(command):
    blocked = require_export()
    if blocked:
        return blocked

    mxd = get_mxd()
    if not bool(_safe_get(mxd, "isDDPEnabled", False)):
        return {"ok": False, "error": "Data Driven Pages are not enabled", "saved": False}

    path = command.get("output_path", "") or ""
    prep = _prepare(path, bool(command.get("overwrite", False)))
    if prep:
        return prep

    page_range_type = (command.get("page_range_type", "ALL") or "ALL").upper()
    page_range_string = command.get("page_range_string", "") or ""
    ddp = mxd.dataDrivenPages
    if page_range_type == "RANGE":
        ddp.exportToPDF(path, "RANGE", page_range_string)
    else:
        ddp.exportToPDF(path, page_range_type)
    return {
        "ok": True,
        "output_path": path,
        "page_range_type": page_range_type,
        "saved": False
    }