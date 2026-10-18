# -*- coding: utf-8 -*-
from __future__ import print_function

import arcpy

from core.registry import action
from core.current_map import get_mxd
from core.safety import require_live_write
from features import observability


def _safe_get(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _page_size(mxd):
    value = _safe_get(mxd, "pageSize", None)
    width = None
    height = None
    if value is not None:
        width = _safe_get(value, "width", None)
        height = _safe_get(value, "height", None)
        if width is None or height is None:
            try:
                width = value[0]
                height = value[1]
            except Exception:
                pass
    try:
        width = float(width) if width is not None else None
        height = float(height) if height is not None else None
    except Exception:
        pass
    return {"width": width, "height": height}


def _element_state(el, index):
    row = {
        "index": index,
        "type": _safe_get(el, "type", "") or "",
        "name": _safe_get(el, "name", "") or "",
        "x": _safe_get(el, "elementPositionX", None),
        "y": _safe_get(el, "elementPositionY", None),
        "width": _safe_get(el, "elementWidth", None),
        "height": _safe_get(el, "elementHeight", None)
    }
    if row["type"] == "TEXT_ELEMENT" or hasattr(el, "text"):
        row["text"] = _safe_get(el, "text", "") or ""
        row["font_size"] = _safe_get(el, "fontSize", None)
    return row


def _elements(mxd):
    return list(arcpy.mapping.ListLayoutElements(mxd))


def _resolve(mxd, index=-1, name="", element_type=""):
    els = _elements(mxd)
    if index is not None and int(index) >= 0:
        idx = int(index)
        if idx >= len(els):
            raise RuntimeError("Layout element index out of range: {0}".format(idx))
        el = els[idx]
        if element_type and _safe_get(el, "type", "") != element_type:
            raise RuntimeError("Element type mismatch at index {0}".format(idx))
        return el, idx

    matches = []
    for idx, el in enumerate(els):
        if name and (_safe_get(el, "name", "") or "") != name:
            continue
        if element_type and (_safe_get(el, "type", "") or "") != element_type:
            continue
        matches.append((el, idx))
    if not matches:
        raise RuntimeError("Layout element not found")
    if len(matches) != 1:
        raise RuntimeError("Layout element selector is ambiguous ({0} matches)".format(len(matches)))
    return matches[0]


def _apply_state(el, command):
    before = _element_state(el, command.get("index", -1))
    if command.get("text") is not None and hasattr(el, "text"):
        el.text = command.get("text")
    if command.get("font_size") is not None and hasattr(el, "fontSize"):
        el.fontSize = float(command.get("font_size"))
    if command.get("x") is not None and hasattr(el, "elementPositionX"):
        el.elementPositionX = float(command.get("x"))
    if command.get("y") is not None and hasattr(el, "elementPositionY"):
        el.elementPositionY = float(command.get("y"))
    if command.get("width") is not None and hasattr(el, "elementWidth"):
        el.elementWidth = float(command.get("width"))
    if command.get("height") is not None and hasattr(el, "elementHeight"):
        el.elementHeight = float(command.get("height"))
    return before


@action("get_layout_manifest")
def get_layout_manifest(command):
    mxd = get_mxd()
    rows = []
    for index, el in enumerate(_elements(mxd)):
        rows.append(_element_state(el, index))
    return {
        "ok": True,
        "page_size": _page_size(mxd),
        "element_count": len(rows),
        "elements": rows,
        "saved": False
    }


@action("get_layout_element_state")
def get_layout_element_state(command):
    mxd = get_mxd()
    el, index = _resolve(
        mxd,
        command.get("index", -1),
        command.get("name", ""),
        command.get("element_type", "")
    )
    row = _element_state(el, index)
    row.update({"ok": True, "saved": False})
    return row


@action("set_layout_element_state")
def set_layout_element_state(command):
    blocked = require_live_write()
    if blocked:
        return blocked

    mxd = get_mxd()
    el, index = _resolve(
        mxd,
        command.get("index", -1),
        command.get("name", ""),
        command.get("element_type", "")
    )
    local = dict(command)
    local["index"] = index
    before = _apply_state(el, local)
    arcpy.RefreshActiveView()
    return {
        "ok": True,
        "index": index,
        "before": before,
        "after": _element_state(el, index),
        "saved": False
    }


@action("validate_layout_bounds")
def validate_layout_bounds(command):
    mxd = get_mxd()
    page = _page_size(mxd)
    width = page.get("width")
    height = page.get("height")
    warnings = []

    if width is None or height is None:
        return {
            "ok": True,
            "page_size": page,
            "warnings": ["ArcMap pageSize could not be resolved numerically."],
            "out_of_bounds": [],
            "saved": False
        }

    out = []
    for index, el in enumerate(_elements(mxd)):
        state = _element_state(el, index)
        x = state.get("x")
        y = state.get("y")
        w = state.get("width")
        h = state.get("height")
        if x is None or y is None:
            continue
        flags = []
        try:
            if float(x) < 0:
                flags.append("left")
            if float(y) < 0:
                flags.append("bottom")
            if w is not None and float(x) + float(w) > width:
                flags.append("right")
            if h is not None and float(y) + float(h) > height:
                flags.append("top")
        except Exception:
            continue
        if flags:
            item = dict(state)
            item["outside"] = flags
            out.append(item)

    if out:
        warnings.append(
            "Bounds use ArcMap elementPositionX/Y plus width/height and are a conservative QA check; element anchor points can affect interpretation.")
    return {
        "ok": True,
        "page_size": page,
        "out_of_bounds_count": len(out),
        "out_of_bounds": out,
        "warnings": warnings,
        "saved": False
    }


@action("apply_layout_recipe")
def apply_layout_recipe(command):
    blocked = require_live_write()
    if blocked:
        return blocked

    updates = command.get("updates", []) or []
    if not isinstance(updates, list):
        return {"ok": False, "error": "updates must be a list", "saved": False}
    if len(updates) > 100:
        return {"ok": False, "error": "Maximum 100 layout updates per recipe", "saved": False}

    atomic = bool(command.get("atomic", True))
    snapshot_result = observability.snapshot_state({}) if atomic else None
    snapshot_id = snapshot_result.get("snapshot_id") if snapshot_result else None
    results = []

    try:
        for pos, update in enumerate(updates):
            if not isinstance(update, dict):
                raise RuntimeError("Update {0} must be an object".format(pos))
            local = dict(update)
            result = set_layout_element_state(local)
            results.append(result)
            if not result.get("ok"):
                raise RuntimeError(result.get("error", "Layout update failed"))
    except Exception as exc:
        rollback = None
        if atomic and snapshot_id:
            rollback = observability.restore_snapshot({"snapshot_id": snapshot_id})
        return {
            "ok": False,
            "error": str(exc),
            "results": results,
            "snapshot_id": snapshot_id,
            "rolled_back": bool(rollback and rollback.get("ok")),
            "rollback": rollback,
            "saved": False
        }

    arcpy.RefreshActiveView()
    return {
        "ok": True,
        "update_count": len(results),
        "results": results,
        "snapshot_id": snapshot_id,
        "atomic": atomic,
        "saved": False
    }
