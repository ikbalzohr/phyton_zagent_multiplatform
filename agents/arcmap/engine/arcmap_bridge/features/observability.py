# -*- coding: utf-8 -*-
from __future__ import print_function
import uuid
import arcpy

from core.registry import action
from core.current_map import get_mxd, get_dataframe, find_layer, safe_layer_source
from core.safety import require_live_write

# In-memory, live-session snapshots. They are intentionally not persisted to disk.
_SNAPSHOTS = {}
_SNAPSHOT_ORDER = []
_MAX_SNAPSHOTS = 20


def _safe_get(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _supports(layer, capability):
    try:
        return bool(layer.supports(capability))
    except Exception:
        return False


def _extent_dict(ext):
    return {
        "xmin": float(ext.XMin),
        "ymin": float(ext.YMin),
        "xmax": float(ext.XMax),
        "ymax": float(ext.YMax)
    }


def _center_dict(ext):
    return {
        "x": float((ext.XMin + ext.XMax) / 2.0),
        "y": float((ext.YMin + ext.YMax) / 2.0)
    }


def _spatial_reference_dict(sr):
    if sr is None:
        return {"name": "", "wkid": None}
    return {
        "name": _safe_get(sr, "name", "") or "",
        "wkid": _safe_get(sr, "factoryCode", None)
    }


def _single_layer(mxd, layer_name, data_frame=""):
    matches = find_layer(mxd, layer_name, data_frame)
    if not matches:
        raise RuntimeError("Layer not found: {0}".format(layer_name))
    return matches[0], len(matches)


def _label_state_for_layer(lyr):
    classes = []
    if _supports(lyr, "LABELCLASSES"):
        try:
            live_classes = lyr.labelClasses
        except Exception:
            live_classes = []
        for index, label_class in enumerate(live_classes):
            classes.append({
                "index": index,
                "class_name": _safe_get(label_class, "className", "") or "",
                "expression": _safe_get(label_class, "expression", "") or "",
                "expression_parser": _safe_get(label_class, "expressionParser", None),
                "sql_query": _safe_get(label_class, "SQLQuery", "") or "",
                "show_class_labels": _safe_get(label_class, "showClassLabels", None)
            })
    return {
        "show_labels": _safe_get(lyr, "showLabels", None),
        "classes": classes
    }


def _selection_state_for_layer(lyr):
    selected = []
    try:
        values = lyr.getSelectionSet()
        if values:
            selected = sorted([int(value) for value in values])
    except Exception:
        selected = []
    return {
        "selection_count": len(selected),
        "selected_oids": selected
    }


def _layer_state_for_object(df, lyr, index=None):
    state = {
        "index": index,
        "data_frame": df.name,
        "name": lyr.name,
        "long_name": _safe_get(lyr, "longName", lyr.name),
        "visible": _safe_get(lyr, "visible", None),
        "data_source": safe_layer_source(lyr),
        "definition_query": "",
        "show_labels": _safe_get(lyr, "showLabels", None),
        "transparency": _safe_get(lyr, "transparency", None),
        "min_scale": _safe_get(lyr, "minScale", None),
        "max_scale": _safe_get(lyr, "maxScale", None),
        "is_group_layer": bool(_safe_get(lyr, "isGroupLayer", False)),
        "is_feature_layer": bool(_safe_get(lyr, "isFeatureLayer", False))
    }
    if _supports(lyr, "DEFINITIONQUERY"):
        try:
            state["definition_query"] = lyr.definitionQuery or ""
        except Exception:
            pass
    return state


def _json_scalar(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    try:
        unicode_type = unicode
    except NameError:
        unicode_type = str
    if isinstance(value, unicode_type):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_scalar(item) for item in value]
    try:
        return str(value)
    except Exception:
        return None


@action("get_dataframe_state")
def get_dataframe_state(command):
    mxd = get_mxd()
    df = get_dataframe(mxd, command.get("data_frame", ""))
    ext = df.extent
    sr = _safe_get(df, "spatialReference", None)
    return {
        "ok": True,
        "data_frame": df.name,
        "scale": (float(_safe_get(df, "scale", 0.0)) if _safe_get(df, "scale", None) not in (None, "") else None),
        "extent": _extent_dict(ext),
        "center": _center_dict(ext),
        "rotation": float(_safe_get(df, "rotation", 0.0) or 0.0),
        "spatial_reference": _spatial_reference_dict(sr),
        "saved": False
    }


@action("get_layer_state")
def get_layer_state(command):
    mxd = get_mxd()
    pair, match_count = _single_layer(
        mxd, command.get("layer_name", ""), command.get("data_frame", ""))
    df, lyr = pair
    result = _layer_state_for_object(df, lyr)
    result.update({
        "ok": True,
        "match_count": match_count,
        "saved": False
    })
    return result


@action("get_label_state")
def get_label_state(command):
    mxd = get_mxd()
    pair, match_count = _single_layer(
        mxd, command.get("layer_name", ""), command.get("data_frame", ""))
    df, lyr = pair
    state = _label_state_for_layer(lyr)
    state.update({
        "ok": True,
        "data_frame": df.name,
        "layer_name": lyr.name,
        "match_count": match_count,
        "saved": False
    })
    return state


@action("get_selection_state")
def get_selection_state(command):
    mxd = get_mxd()
    pair, match_count = _single_layer(
        mxd, command.get("layer_name", ""), command.get("data_frame", ""))
    df, lyr = pair
    state = _selection_state_for_layer(lyr)
    state.update({
        "ok": True,
        "data_frame": df.name,
        "layer_name": lyr.name,
        "match_count": match_count,
        "saved": False
    })
    return state


@action("list_fields")
def list_fields(command):
    mxd = get_mxd()
    pair, match_count = _single_layer(
        mxd, command.get("layer_name", ""), command.get("data_frame", ""))
    df, lyr = pair
    try:
        fields = arcpy.ListFields(lyr)
    except Exception:
        source = safe_layer_source(lyr)
        if not source:
            raise
        fields = arcpy.ListFields(source)
    rows = []
    for field in fields:
        rows.append({
            "name": field.name,
            "alias": _safe_get(field, "aliasName", field.name),
            "type": field.type,
            "length": _safe_get(field, "length", None),
            "nullable": _safe_get(field, "isNullable", None),
            "required": _safe_get(field, "required", None)
        })
    return {
        "ok": True,
        "data_frame": df.name,
        "layer_name": lyr.name,
        "match_count": match_count,
        "fields": rows,
        "saved": False
    }


@action("get_layer_order")
def get_layer_order(command):
    mxd = get_mxd()
    df = get_dataframe(mxd, command.get("data_frame", ""))
    rows = []
    for index, lyr in enumerate(arcpy.mapping.ListLayers(mxd, "", df)):
        rows.append({
            "index": index,
            "name": lyr.name,
            "long_name": _safe_get(lyr, "longName", lyr.name),
            "visible": _safe_get(lyr, "visible", None),
            "is_group_layer": bool(_safe_get(lyr, "isGroupLayer", False)),
            "data_source": safe_layer_source(lyr)
        })
    return {
        "ok": True,
        "data_frame": df.name,
        "layers": rows,
        "saved": False
    }


@action("get_active_dataframe")
def get_active_dataframe(command):
    mxd = get_mxd()
    df = _safe_get(mxd, "activeDataFrame", None)
    if df is None:
        frames = arcpy.mapping.ListDataFrames(mxd)
        df = frames[0] if frames else None
    return {
        "ok": True,
        "data_frame": df.name if df is not None else "",
        "saved": False
    }


@action("get_symbology_state")
def get_symbology_state(command):
    mxd = get_mxd()
    pair, match_count = _single_layer(
        mxd, command.get("layer_name", ""), command.get("data_frame", ""))
    df, lyr = pair
    result = {
        "ok": True,
        "data_frame": df.name,
        "layer_name": lyr.name,
        "match_count": match_count,
        "symbology_type": _safe_get(lyr, "symbologyType", None),
        "properties": {},
        "saved": False
    }
    symbology = _safe_get(lyr, "symbology", None)
    if symbology is not None:
        for prop in (
                "valueField", "normalization", "numClasses",
                "classificationMethod", "classBreakValues", "classBreakLabels",
                "classValues", "classLabels", "noDataLabel"):
            value = _safe_get(symbology, prop, None)
            if value is not None:
                result["properties"][prop] = _json_scalar(value)
    return result



def _capture_layout_state(mxd):
    rows = []
    for index, el in enumerate(arcpy.mapping.ListLayoutElements(mxd)):
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
        rows.append(row)
    return rows


def _restore_layout_state(mxd, saved_layout):
    warnings = []
    live = list(arcpy.mapping.ListLayoutElements(mxd))
    for state in saved_layout or []:
        index = state.get("index")
        if index is None or index < 0 or index >= len(live):
            warnings.append("Layout element index missing during restore: {0}".format(index))
            continue
        el = live[index]
        live_type = _safe_get(el, "type", "") or ""
        if state.get("type") and live_type != state.get("type"):
            warnings.append("Layout element type changed at index {0}".format(index))
            continue

        # Restore text/font first because text alignment can shift X/Y.
        if "text" in state and hasattr(el, "text"):
            try:
                el.text = state.get("text", "") or ""
            except Exception as exc:
                warnings.append("Text restore failed at index {0}: {1}".format(index, exc))
        if state.get("font_size") is not None and hasattr(el, "fontSize"):
            try:
                el.fontSize = float(state.get("font_size"))
            except Exception:
                pass

        for key, attr in (
                ("width", "elementWidth"), ("height", "elementHeight"),
                ("x", "elementPositionX"), ("y", "elementPositionY")):
            if state.get(key) is None or not hasattr(el, attr):
                continue
            try:
                setattr(el, attr, float(state.get(key)))
            except Exception as exc:
                warnings.append(
                    "Layout {0} restore failed at index {1}: {2}".format(key, index, exc))
    return warnings

def _capture_snapshot():
    mxd = get_mxd()
    frames = []
    for df in arcpy.mapping.ListDataFrames(mxd):
        ext = df.extent
        frame = {
            "data_frame": df.name,
            "scale": (float(_safe_get(df, "scale", 0.0)) if _safe_get(df, "scale", None) not in (None, "") else None),
            "extent": _extent_dict(ext),
            "center": _center_dict(ext),
            "rotation": float(_safe_get(df, "rotation", 0.0) or 0.0),
            "layers": []
        }
        for index, lyr in enumerate(arcpy.mapping.ListLayers(mxd, "", df)):
            layer_state = _layer_state_for_object(df, lyr, index)
            if layer_state.get("is_feature_layer"):
                layer_state["label_state"] = _label_state_for_layer(lyr)
                layer_state["selection_state"] = _selection_state_for_layer(lyr)
            frame["layers"].append(layer_state)
        frames.append(frame)
    return {
        "version": 3,
        "frames": frames,
        "layout": _capture_layout_state(mxd)
    }


def _snapshot_summary(snapshot):
    frame_count = len(snapshot.get("frames", []))
    layer_count = 0
    for frame in snapshot.get("frames", []):
        layer_count += len(frame.get("layers", []))
    return {
        "frame_count": frame_count,
        "layer_count": layer_count,
        "layout_element_count": len(snapshot.get("layout", []))
    }


@action("snapshot_state")
def snapshot_state(command):
    snapshot_id = str(uuid.uuid4())
    snapshot = _capture_snapshot()
    _SNAPSHOTS[snapshot_id] = snapshot
    _SNAPSHOT_ORDER.append(snapshot_id)
    while len(_SNAPSHOT_ORDER) > _MAX_SNAPSHOTS:
        old_id = _SNAPSHOT_ORDER.pop(0)
        try:
            del _SNAPSHOTS[old_id]
        except Exception:
            pass
    return {
        "ok": True,
        "snapshot_id": snapshot_id,
        "summary": _snapshot_summary(snapshot),
        "restorable": [
            "dataframe_extent", "dataframe_scale", "dataframe_rotation",
            "layer_visibility", "definition_query", "transparency",
            "min_scale", "max_scale", "labels", "label_expression",
            "label_sql", "selection", "layer_name", "layer_order",
            "layout_text", "layout_position", "layout_size", "layout_font_size"
        ],
        "not_restored_by_design": ["data_source", "symbology"],
        "saved": False
    }


def _restore_frame(df, state):
    try:
        if state.get("rotation") is not None:
            df.rotation = float(state["rotation"])
    except Exception:
        pass
    ext = state.get("extent") or {}
    if all(key in ext for key in ("xmin", "ymin", "xmax", "ymax")):
        df.extent = arcpy.Extent(
            ext["xmin"], ext["ymin"], ext["xmax"], ext["ymax"])
    if state.get("scale") is not None:
        df.scale = float(state["scale"])


def _find_snapshot_layer(live_layers, state):
    index = state.get("index")
    name = state.get("name", "")
    saved_source = state.get("data_source", "") or ""

    # Prefer unique data source identity. This survives rename and reorder.
    if saved_source:
        source_matches = []
        for layer in live_layers:
            try:
                if safe_layer_source(layer) == saved_source:
                    source_matches.append(layer)
            except Exception:
                pass
        if len(source_matches) == 1:
            return source_matches[0]

    # Next, use exact index when the candidate still matches by name/source.
    if index is not None and 0 <= index < len(live_layers):
        candidate = live_layers[index]
        candidate_source = safe_layer_source(candidate)
        if candidate.name == name or (saved_source and candidate_source == saved_source):
            return candidate

    # Finally, unique current name.
    matches = [layer for layer in live_layers if layer.name == name]
    if len(matches) == 1:
        return matches[0]
    return None


def _restore_layer_basic(lyr, state):
    saved_name = state.get("name", "")
    if saved_name and lyr.name != saved_name:
        try:
            lyr.name = saved_name
        except Exception:
            pass

    if state.get("visible") is not None:
        try:
            lyr.visible = bool(state["visible"])
        except Exception:
            pass
    if state.get("transparency") is not None:
        try:
            lyr.transparency = state["transparency"]
        except Exception:
            pass
    if state.get("min_scale") is not None:
        try:
            lyr.minScale = state["min_scale"]
        except Exception:
            pass
    if state.get("max_scale") is not None:
        try:
            lyr.maxScale = state["max_scale"]
        except Exception:
            pass
    if _supports(lyr, "DEFINITIONQUERY"):
        try:
            lyr.definitionQuery = state.get("definition_query", "") or ""
        except Exception:
            pass


def _restore_labels(lyr, state):
    label_state = state.get("label_state")
    if not label_state:
        return
    if label_state.get("show_labels") is not None:
        try:
            lyr.showLabels = bool(label_state["show_labels"])
        except Exception:
            pass
    try:
        live_classes = lyr.labelClasses
    except Exception:
        live_classes = []
    for saved_class in label_state.get("classes", []):
        index = saved_class.get("index")
        if index is None or index < 0 or index >= len(live_classes):
            continue
        live_class = live_classes[index]
        try:
            live_class.expression = saved_class.get("expression", "") or ""
        except Exception:
            pass
        if saved_class.get("expression_parser") is not None:
            try:
                live_class.expressionParser = saved_class["expression_parser"]
            except Exception:
                pass
        try:
            live_class.SQLQuery = saved_class.get("sql_query", "") or ""
        except Exception:
            pass
        if saved_class.get("show_class_labels") is not None:
            try:
                live_class.showClassLabels = bool(saved_class["show_class_labels"])
            except Exception:
                pass


def _restore_selection(lyr, state):
    selection_state = state.get("selection_state")
    if not selection_state:
        return None
    oids = selection_state.get("selected_oids") or []
    try:
        lyr.setSelectionSet(oids, "NEW")
        return True
    except Exception as exc:
        return str(exc)


def _restore_top_level_layer_order(mxd, df, frame_state):
    """
    Restore flat top-level layer order safely.

    ArcPy layer references returned by ListLayers can become stale after
    MoveLayer changes the TOC. Therefore layer references are resolved again
    before every move.

    Group/nested hierarchies are deliberately not rearranged because
    ListLayers returns a flattened hierarchy and moving children blindly
    could alter group membership.
    """
    saved_layers = frame_state.get("layers", [])
    if not saved_layers:
        return []

    # Do not rearrange group/nested structures.
    for state in saved_layers:
        if state.get("is_group_layer"):
            return ["Layer-order restore skipped because group layers are present."]

        long_name = state.get("long_name", state.get("name", ""))
        if long_name and long_name != state.get("name", ""):
            return ["Layer-order restore skipped because nested layers are present."]

    if len(saved_layers) <= 1:
        return []

    def _resolve(layers, state):
        return _find_snapshot_layer(layers, state)

    def _position(layers, state):
        for pos, candidate in enumerate(layers):
            if _find_snapshot_layer([candidate], state) is not None:
                return pos
        return -1

    # Preflight: every snapshot layer must still be resolvable.
    live_layers = list(arcpy.mapping.ListLayers(mxd, "", df))
    for state in saved_layers:
        if _resolve(live_layers, state) is None:
            return [
                "Layer-order restore skipped; identity unresolved for: {0}".format(
                    state.get("name", "")
                )
            ]

    # Put the first snapshot layer at the top.
    # IMPORTANT: resolve from the current ListLayers result.
    current = list(arcpy.mapping.ListLayers(mxd, "", df))
    first_state = saved_layers[0]
    first_layer = _resolve(current, first_state)
    first_pos = _position(current, first_state)

    if first_layer is None:
        return [
            "Layer-order restore skipped; identity unresolved for: {0}".format(
                first_state.get("name", "")
            )
        ]

    if first_pos > 0:
        arcpy.mapping.MoveLayer(df, current[0], first_layer, "BEFORE")

    # Restore remaining relative order.
    # Refresh ListLayers BEFORE EACH MoveLayer so no stale layer references
    # are reused after the TOC has changed.
    for index in range(1, len(saved_layers)):
        current = list(arcpy.mapping.ListLayers(mxd, "", df))

        reference_state = saved_layers[index - 1]
        move_state = saved_layers[index]

        reference_layer = _resolve(current, reference_state)
        move_layer = _resolve(current, move_state)

        if reference_layer is None or move_layer is None:
            return [
                "Layer-order restore stopped; identity unresolved between "
                "{0} and {1}.".format(
                    reference_state.get("name", ""),
                    move_state.get("name", "")
                )
            ]

        reference_pos = _position(current, reference_state)
        move_pos = _position(current, move_state)

        # Already correct: do not issue a redundant MoveLayer call.
        if move_pos == reference_pos + 1:
            continue

        arcpy.mapping.MoveLayer(
            df,
            reference_layer,
            move_layer,
            "AFTER"
        )

    # Final verification using a completely fresh TOC snapshot.
    final_layers = list(arcpy.mapping.ListLayers(mxd, "", df))
    positions = []

    for state in saved_layers:
        pos = _position(final_layers, state)
        if pos < 0:
            return [
                "Layer-order restore verification failed; identity unresolved "
                "for: {0}".format(state.get("name", ""))
            ]
        positions.append(pos)

    # Snapshot layers must appear in exactly the requested relative order.
    if positions != sorted(positions):
        return [
            "Layer-order restore verification failed for data frame: {0}".format(
                df.name
            )
        ]

    return []

@action("restore_snapshot")
def restore_snapshot(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    snapshot_id = command.get("snapshot_id", "")
    snapshot = _SNAPSHOTS.get(snapshot_id)
    if snapshot is None:
        return {
            "ok": False,
            "error": "Snapshot not found in current ArcMap bridge session: {0}".format(snapshot_id),
            "saved": False
        }

    mxd = get_mxd()
    restored = []
    skipped = []
    selection_warnings = []
    order_warnings = []
    layout_warnings = []

    for frame_state in snapshot.get("frames", []):
        frame_name = frame_state.get("data_frame", "")
        try:
            df = get_dataframe(mxd, frame_name)
            _restore_frame(df, frame_state)
            restored.append("dataframe:{0}".format(frame_name))
        except Exception as exc:
            skipped.append({"target": "dataframe:{0}".format(frame_name), "reason": str(exc)})
            continue

        live_layers = arcpy.mapping.ListLayers(mxd, "", df)
        for layer_state in frame_state.get("layers", []):
            lyr = _find_snapshot_layer(live_layers, layer_state)
            if lyr is None:
                skipped.append({
                    "target": "layer:{0}/{1}".format(frame_name, layer_state.get("name", "")),
                    "reason": "Layer identity could not be resolved safely."
                })
                continue
            try:
                _restore_layer_basic(lyr, layer_state)
                _restore_labels(lyr, layer_state)
                selection_result = _restore_selection(lyr, layer_state)
                if selection_result not in (None, True):
                    selection_warnings.append({
                        "layer": lyr.name,
                        "warning": selection_result
                    })
                restored.append("layer:{0}/{1}".format(frame_name, lyr.name))
            except Exception as exc:
                skipped.append({
                    "target": "layer:{0}/{1}".format(frame_name, lyr.name),
                    "reason": str(exc)
                })

        try:
            order_warnings.extend(_restore_top_level_layer_order(mxd, df, frame_state))
        except Exception as exc:
            order_warnings.append(
                "Layer-order restore failed for {0}: {1}".format(frame_name, exc))

    try:
        layout_warnings.extend(_restore_layout_state(mxd, snapshot.get("layout", [])))
    except Exception as exc:
        layout_warnings.append("Layout restore failed: {0}".format(exc))

    arcpy.RefreshTOC()
    arcpy.RefreshActiveView()
    return {
        "ok": True,
        "snapshot_id": snapshot_id,
        "restored": restored,
        "skipped": skipped,
        "selection_warnings": selection_warnings,
        "order_warnings": order_warnings,
        "layout_warnings": layout_warnings,
        "not_restored_by_design": ["data_source", "symbology"],
        "saved": False
    }

