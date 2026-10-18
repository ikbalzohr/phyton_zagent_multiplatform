# -*- coding: utf-8 -*-
from __future__ import print_function

import math
import os
import time
import uuid

import arcpy

from core.registry import action
from core.current_map import get_mxd
from core.safety import require_live_write

try:
    from stage3 import bridge as stage3_bridge
except Exception:
    stage3_bridge = None


def _find_df(mxd, name=""):
    dfs = arcpy.mapping.ListDataFrames(mxd, name or "")
    if not dfs:
        dfs = arcpy.mapping.ListDataFrames(mxd)
    if not dfs:
        raise RuntimeError("CURRENT MXD has no data frame")
    return dfs[0]


def _find_layer(mxd, df, name):
    if not name:
        return None
    for lyr in arcpy.mapping.ListLayers(mxd, "", df):
        if lyr.name == name or getattr(lyr, "longName", "") == name:
            return lyr
    rows = arcpy.mapping.ListLayers(mxd, name, df)
    return rows[0] if rows else None


def _same_path(left, right):
    try:
        return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(os.path.abspath(str(right)))
    except Exception:
        return False


def _find_layer_by_source(mxd, df, path):
    if not path:
        return None
    for lyr in arcpy.mapping.ListLayers(mxd, "", df):
        try:
            if lyr.supports("DATASOURCE") and _same_path(lyr.dataSource, path):
                return lyr
        except Exception:
            pass
    return None


def _safe_make_layer(path, temp_name):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".lyr":
        return arcpy.mapping.Layer(path)
    try:
        direct = arcpy.mapping.Layer(path)
        return direct
    except Exception:
        pass
    desc = arcpy.Describe(path)
    dtype = str(getattr(desc, "dataType", "") or "").lower()
    if "raster" in dtype or ext in (".ecw", ".tif", ".tiff", ".img", ".sid", ".jpg", ".jpeg", ".png"):
        result = arcpy.MakeRasterLayer_management(path, temp_name)
    else:
        result = arcpy.MakeFeatureLayer_management(path, temp_name)
    out = result.getOutput(0)
    # ArcGIS 10.6 may already return arcpy._mapping.Layer. Do not wrap twice.
    try:
        if isinstance(out, arcpy.mapping.Layer):
            return out
    except TypeError:
        if out.__class__.__module__.startswith("arcpy") and out.__class__.__name__ == "Layer":
            return out
    except Exception:
        pass
    return arcpy.mapping.Layer(out)


def _ensure_layer(mxd, df, row):
    name = str(row.get("layer_name") or os.path.splitext(os.path.basename(str(row.get("path") or "")))[0])
    path = str(row.get("path") or "")
    existing = _find_layer(mxd, df, name) or _find_layer_by_source(mxd, df, path)
    if existing is not None:
        try:
            existing.name = name
        except Exception:
            pass
        existing.visible = bool(row.get("visible", True))
        return existing, False
    if not path or not os.path.exists(path):
        if row.get("required"):
            raise RuntimeError("Required dataset missing: %s" % path)
        return None, False
    lyr = _safe_make_layer(path, "zagent_cart_%s" % uuid.uuid4().hex[:8])
    try:
        lyr.name = name
    except Exception:
        pass
    arcpy.mapping.AddLayer(df, lyr, "TOP")
    added = _find_layer(mxd, df, name) or lyr
    added.visible = bool(row.get("visible", True))
    return added, True


def _rgb(rgb, transparency=None):
    if stage3_bridge is None:
        return None
    color, _ = stage3_bridge._create_com(["esriDisplay.RgbColor"])
    values = list(rgb or [0, 0, 0])
    while len(values) < 3:
        values.append(0)
    for attr, value in (("Red", values[0]), ("Green", values[1]), ("Blue", values[2])):
        try:
            setattr(color, attr, int(value))
        except Exception:
            pass
    if transparency is not None:
        try:
            alpha = int(round(255.0 * (1.0 - max(0.0, min(100.0, float(transparency))) / 100.0)))
            color.Transparency = alpha
        except Exception:
            pass
    return color


def _set_symbol_style(lyr, style):
    warnings = []
    if not style:
        return warnings
    try:
        if getattr(lyr, "isRasterLayer", False):
            if "transparency" in style:
                lyr.transparency = int(style.get("transparency"))
            return warnings

        shape_type = ""
        try:
            shape_type = str(getattr(arcpy.Describe(lyr), "shapeType", "") or "")
        except Exception:
            pass

        ao = getattr(lyr, "_arc_object", None)
        line_rgb = style.get("line_rgb") or [0, 0, 0]
        fill_rgb = style.get("fill_rgb") or [255, 255, 255]
        line_width = float(style.get("line_width_pt") or 0.8)
        fill_transparency = style.get("fill_transparency")
        symbol = None

        if stage3_bridge is not None and ao is not None:
            try:
                line, _ = stage3_bridge._create_com(["esriDisplay.SimpleLineSymbol"])
                line.Color = _rgb(line_rgb)
                try:
                    line.Width = line_width
                except Exception:
                    pass

                if shape_type.lower() in ("polygon", "multipatch"):
                    fill, _ = stage3_bridge._create_com(["esriDisplay.SimpleFillSymbol"])
                    fill.Color = _rgb(fill_rgb, fill_transparency)
                    try:
                        fill.Outline = line
                    except Exception:
                        pass
                    symbol = fill
                elif shape_type.lower() in ("polyline", "line"):
                    symbol = line
                elif shape_type.lower() in ("point", "multipoint"):
                    marker, _ = stage3_bridge._create_com(["esriDisplay.SimpleMarkerSymbol"])
                    marker.Color = _rgb(fill_rgb)
                    try:
                        marker.Outline = True
                        marker.OutlineColor = _rgb(line_rgb)
                        marker.OutlineSize = max(0.4, line_width)
                    except Exception:
                        pass
                    symbol = marker

                if symbol is not None:
                    renderer, _ = stage3_bridge._create_com(["esriCarto.SimpleRenderer"])
                    renderer.Symbol = symbol
                    ao.Renderer = renderer
            except Exception as exc:
                warnings.append("deterministic renderer fallback for %s: %s" % (lyr.name, exc))

        if symbol is None:
            # Fallback to the renderer already attached to the layer.
            try:
                renderer = getattr(ao, "Renderer", None) if ao is not None else None
                symbol = getattr(renderer, "Symbol", None) if renderer is not None else None
                if symbol is not None:
                    if shape_type.lower() in ("polygon", "multipatch"):
                        try:
                            symbol.Color = _rgb(fill_rgb, fill_transparency)
                            symbol.Outline.Color = _rgb(line_rgb)
                            symbol.Outline.Width = line_width
                        except Exception:
                            pass
                    else:
                        try:
                            symbol.Color = _rgb(line_rgb)
                            symbol.Width = line_width
                        except Exception:
                            pass
                    renderer.Symbol = symbol
            except Exception as exc:
                warnings.append("renderer symbol unavailable for %s: %s" % (lyr.name, exc))
    except Exception as exc:
        warnings.append("symbology style failed for %s: %s" % (lyr.name, exc))

    if "transparency" in style:
        try:
            lyr.transparency = int(style.get("transparency"))
        except Exception:
            warnings.append("layer transparency unsupported for %s" % lyr.name)
    return warnings


def _apply_symbology(mxd, df, plan):
    warnings = []
    for row in plan or []:
        lyr = _find_layer(mxd, df, row.get("layer_name"))
        if lyr is None:
            warnings.append("symbology target missing: %s" % row.get("layer_name"))
            continue
        warnings.extend(_set_symbol_style(lyr, row.get("style") or {}))
    return warnings


def _configure_maplex_best_effort(mxd, df, label_plan):
    result = {
        "requested": True,
        "enabled": False,
        "configured_layers": [],
        "warnings": [],
    }
    try:
        map_obj = getattr(df, "_arc_object", None)
        if map_obj is not None:
            # ArcGIS Desktop exposes different COM surfaces depending on
            # licensing/extension state. Set only properties that actually
            # exist; otherwise retain the standard label engine.
            for attr, value in (
                ("UseMaplexLabelEngine", True),
                ("MaplexEnabled", True),
                ("UseMaplex", True),
            ):
                try:
                    setattr(map_obj, attr, value)
                    result["enabled"] = True
                    break
                except Exception:
                    pass
    except Exception as exc:
        result["warnings"].append("maplex map activation failed: %s" % exc)

    for row in label_plan or []:
        lyr = _find_layer(mxd, df, row.get("layer_name"))
        if lyr is None or not lyr.supports("LABELCLASSES"):
            continue
        classes = lyr.labelClasses
        if not classes:
            continue
        lc = classes[0]
        obj = getattr(lc, "_arc_object", None)
        configured = False
        if obj is not None:
            property_sets = [
                ("CanOverlap", bool(row.get("allow_overlap", False))),
                ("AllowOverlap", bool(row.get("allow_overlap", False))),
                ("RemoveDuplicates", bool(row.get("remove_duplicates", True))),
                ("RemoveDuplicateLabels", bool(row.get("remove_duplicates", True))),
                ("Priority", int(row.get("priority") or 50)),
                ("FeatureWeight", int(row.get("priority") or 50)),
            ]
            for attr, value in property_sets:
                try:
                    setattr(obj, attr, value)
                    configured = True
                except Exception:
                    pass
            # Polygon labels should prefer an interior placement and line labels
            # should follow geometry where the COM class supports it.
            try:
                shape_type = str(getattr(arcpy.Describe(lyr), "shapeType", "") or "").lower()
            except Exception:
                shape_type = ""
            if shape_type == "polygon":
                for attr, value in (
                    ("PlacementMethod", 0),
                    ("PlaceOnlyInsidePolygon", True),
                    ("AvoidPolygonHoles", True),
                ):
                    try:
                        setattr(obj, attr, value)
                        configured = True
                    except Exception:
                        pass
            elif shape_type in ("polyline", "line"):
                for attr, value in (
                    ("FollowFeature", True),
                    ("Curved", True),
                    ("LinePlacementMethod", 0),
                ):
                    try:
                        setattr(obj, attr, value)
                        configured = True
                    except Exception:
                        pass
        if configured:
            result["configured_layers"].append(lyr.name)

    if result["configured_layers"]:
        result["enabled"] = True
    return result


def _set_label_symbol_best_effort(label_class, row):
    warnings = []
    try:
        obj = getattr(label_class, "_arc_object", None)
        text_symbol = None
        for attr in ("Symbol", "TextSymbol"):
            try:
                text_symbol = getattr(obj, attr)
                if text_symbol is not None:
                    break
            except Exception:
                pass
        if text_symbol is None:
            return ["label symbol automation unavailable"]
        try:
            text_symbol.Size = float(row.get("font_size_pt") or 8.5)
        except Exception:
            pass
        if row.get("text_rgb") is not None:
            try:
                text_symbol.Color = _rgb(row.get("text_rgb"))
            except Exception:
                warnings.append("label color unavailable")
        halo_size = float(row.get("halo_pt") or 0)
        if halo_size > 0:
            halo_color = row.get("halo_rgb") or [0, 0, 0]
            try:
                text_symbol.HaloSize = halo_size
            except Exception:
                pass
            try:
                text_symbol.HaloColor = _rgb(halo_color)
            except Exception:
                pass
            try:
                halo_line, _ = stage3_bridge._create_com(["esriDisplay.SimpleLineSymbol"])
                halo_line.Color = _rgb(halo_color)
                halo_line.Width = halo_size
                for attr in ("HaloSymbol", "Halo"):
                    try:
                        setattr(text_symbol, attr, halo_line)
                        break
                    except Exception:
                        pass
            except Exception:
                pass
        try:
            obj.Symbol = text_symbol
        except Exception:
            pass
    except Exception as exc:
        warnings.append("label symbol style failed: %s" % exc)
    return warnings


def _dominant(values):
    counts = {}
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        counts[text] = counts.get(text, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return (ranked[0][0] if ranked else None), ranked


def _infer_admin_from_layers(mxd, df, program):
    field_candidates = {
        "desa": ["DESA", "DESA_KELUR", "DESA_KEL", "KELURAHAN", "NAMA_DESA", "NAMOBJ"],
        "kecamatan": ["KECAMATAN", "KEC", "NAMA_KEC", "WADMKC"],
        "kabupaten": ["KAB_KOTA", "KABUPATEN", "KAB", "NAMA_KAB", "WADMKK"],
        "provinsi": ["PROVINSI", "PROPINSI", "PROV", "NAMA_PROV", "WADMPR"],
    }
    collected = dict((key, []) for key in field_candidates)
    sources = dict((key, set()) for key in field_candidates)
    inspected = []

    for row in program.get("layers") or []:
        if row.get("role") not in ("admin_polygon", "project_boundary"):
            continue
        lyr = _find_layer(mxd, df, row.get("layer_name"))
        if lyr is None or not getattr(lyr, "isFeatureLayer", False):
            continue
        try:
            fields = [field.name for field in arcpy.ListFields(lyr)]
        except Exception:
            continue
        lookup = dict((str(name).upper(), name) for name in fields)
        selected = {}
        cursor_fields = []
        for level, candidates in field_candidates.items():
            for candidate in candidates:
                actual = lookup.get(candidate.upper())
                if actual:
                    selected[level] = actual
                    if actual not in cursor_fields:
                        cursor_fields.append(actual)
                    break
        if not cursor_fields:
            continue
        inspected.append({"layer": lyr.name, "fields": selected})
        try:
            index = dict((name, idx) for idx, name in enumerate(cursor_fields))
            count = 0
            with arcpy.da.SearchCursor(lyr, cursor_fields) as cursor:
                for values in cursor:
                    count += 1
                    for level, field_name in selected.items():
                        value = values[index[field_name]]
                        if value not in (None, ""):
                            collected[level].append(value)
                            sources[level].add(lyr.name)
                    if count >= 1000:
                        break
        except Exception:
            continue

    location = {}
    conflicts = {}
    source_map = {}
    for level, values in collected.items():
        value, ranked = _dominant(values)
        if value:
            location[level] = value
            source_map[level] = sorted(sources[level])
        if len(ranked) > 1:
            conflicts[level] = [
                {"value": item[0], "count": item[1]}
                for item in ranked[:10]
            ]
    return {
        "location": location,
        "sources": source_map,
        "conflicts": conflicts,
        "inspected_layers": inspected,
    }


def _merge_runtime_admin_title(layout, program, inference):
    metadata = program.get("metadata") or {}
    title_meta = metadata.get("title") or {}
    explicit = dict(title_meta.get("administrative_location") or {})
    inferred = (inference or {}).get("location") or {}
    admin = dict(inferred)
    admin.update(dict((k, v) for k, v in explicit.items() if v not in (None, "")))

    raw_title = str(title_meta.get("raw_title") or "PETA ADMINISTRASI").upper()
    project_name = str(title_meta.get("project_name") or "").upper()
    year = title_meta.get("year")
    lines = [raw_title]
    if project_name:
        lines.append(project_name)
    prefixes = (
        ("desa", "DESA"),
        ("kecamatan", "KECAMATAN"),
        ("kabupaten", "KABUPATEN"),
        ("provinsi", "PROVINSI"),
    )
    for key, prefix in prefixes:
        value = admin.get(key)
        if value:
            lines.append("%s %s" % (prefix, str(value).upper()))
    if year:
        lines.append("TAHUN %s" % year)
    layout.setdefault("title", {})["lines"] = lines
    metadata["runtime_administrative_location"] = admin
    metadata["runtime_administrative_inference"] = inference
    program["metadata"] = metadata
    return lines


def _runtime_label_plan(mxd, df, program):
    candidates = {
        "admin_polygon": ["DESA", "DESA_KELUR", "DESA_KEL", "NAMA_DESA", "NAMOBJ", "NAME"],
        "project_boundary": ["NAMA", "NAME", "NAMOBJ"],
    }
    out = []
    for layer_row in program.get("layers") or []:
        role = layer_row.get("role")
        if role not in candidates:
            continue
        lyr = _find_layer(mxd, df, layer_row.get("layer_name"))
        if lyr is None or not getattr(lyr, "isFeatureLayer", False):
            continue
        try:
            fields = [f.name for f in arcpy.ListFields(lyr)]
        except Exception:
            fields = []
        lookup = dict((str(x).upper(), x) for x in fields)
        field = None
        for name in candidates[role]:
            if name.upper() in lookup:
                field = lookup[name.upper()]
                break
        if field:
            out.append({
                "role": role,
                "layer_name": lyr.name,
                "field": field,
                "expression": "[%s]" % field,
                "font_size_pt": 8.5,
                "text_rgb": [255, 230, 0],
                "halo_rgb": [0, 0, 0],
                "halo_pt": 1.2,
                "remove_duplicates": True,
                "allow_overlap": False,
                "priority": 80,
            })
    return out


def _apply_labels(mxd, df, plan):
    warnings = []
    for row in plan or []:
        lyr = _find_layer(mxd, df, row.get("layer_name"))
        if lyr is None or not lyr.supports("LABELCLASSES"):
            continue
        classes = lyr.labelClasses
        if not classes:
            continue
        lc = classes[0]
        try:
            lc.expression = row.get("expression") or ""
            try:
                lc.expressionParser = "VBScript"
            except Exception:
                pass
            lc.showClassLabels = True
            lyr.showLabels = True
            warnings.extend(_set_label_symbol_best_effort(lc, row))
        except Exception as exc:
            warnings.append("labels failed for %s: %s" % (lyr.name, exc))
    return warnings


def _page_size(mxd):
    p = mxd.pageSize
    return float(p.width), float(p.height)


def _norm_box(box, page_w, page_h):
    box = box or {}
    return {
        "x": float(box.get("x") or 0) * page_w,
        "y": float(box.get("y") or 0) * page_h,
        "w": float(box.get("w") or 0) * page_w,
        "h": float(box.get("h") or 0) * page_h,
    }


def _set_page_size(paper):
    if stage3_bridge is None:
        return {"ok": False, "warning": "stage3 bridge unavailable"}
    width = float((paper or {}).get("width_cm") or 29.7)
    height = float((paper or {}).get("height_cm") or 21.0)
    orientation = str((paper or {}).get("orientation") or "landscape").lower()
    if orientation == "portrait" and width > height:
        width, height = height, width
    if orientation == "landscape" and height > width:
        width, height = height, width
    try:
        app, doc, pl, backend = stage3_bridge._layout_container()
        page = pl.Page
        page.PutCustomSize(width, height)
        return {"ok": True, "width": width, "height": height, "backend": backend}
    except Exception as exc:
        return {"ok": False, "warning": "page size could not be changed: %s" % exc}


def _set_page_background(rgb):
    if stage3_bridge is None or rgb is None:
        return False
    try:
        app, doc, pl, backend = stage3_bridge._layout_container()
        page = pl.Page
        color = _rgb(rgb)
        for attr in ("BackgroundColor", "Color"):
            try:
                setattr(page, attr, color)
                return True
            except Exception:
                pass
    except Exception:
        pass
    return False


def _set_dataframe_box(mxd, df_name, box):
    page_w, page_h = _page_size(mxd)
    target = _norm_box(box, page_w, page_h)
    elements = arcpy.mapping.ListLayoutElements(mxd, "DATAFRAME_ELEMENT", df_name or "")
    if not elements:
        elements = arcpy.mapping.ListLayoutElements(mxd, "DATAFRAME_ELEMENT")
    if not elements:
        raise RuntimeError("Data frame layout element not found")
    e = elements[0]
    e.elementPositionX = target["x"]
    e.elementPositionY = target["y"]
    e.elementWidth = target["w"]
    e.elementHeight = target["h"]
    return target


def _create_rectangle(name, box, fill_rgb=None, line_rgb=None, line_width=0.8):
    if stage3_bridge is None:
        return {"ok": False, "name": name, "error": "stage3 bridge unavailable"}
    mxd = get_mxd()
    page_w, page_h = _page_size(mxd)
    b = _norm_box(box, page_w, page_h)
    try:
        existing = arcpy.mapping.ListLayoutElements(mxd, "GRAPHIC_ELEMENT", name)
        if existing:
            elem = existing[0]
            env, _ = stage3_bridge._make_envelope(b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"])
            stage3_bridge._set_element_geometry(elem, env)
            return {"ok": True, "name": name, "created": False, "updated": True}
        elem, _ = stage3_bridge._create_com(["esriCarto.RectangleElement"])
        stage3_bridge._set_element_name(elem, name)
        env, _ = stage3_bridge._make_envelope(
            b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]
        )
        if not stage3_bridge._set_element_geometry(elem, env):
            raise RuntimeError("Could not assign rectangle geometry")
        try:
            fill, _ = stage3_bridge._create_com(["esriDisplay.SimpleFillSymbol"])
            if fill_rgb is not None:
                fill.Color = _rgb(fill_rgb)
            else:
                # Section/neatline graphics must never cover map content.
                fill.Color = _rgb([255, 255, 255], 100)
            line, _ = stage3_bridge._create_com(["esriDisplay.SimpleLineSymbol"])
            if line_rgb is not None:
                line.Color = _rgb(line_rgb)
            try:
                line.Width = float(line_width)
            except Exception:
                pass
            try:
                fill.Outline = line
            except Exception:
                pass
            try:
                elem.Symbol = fill
            except Exception:
                pass
        except Exception:
            pass
        backend = stage3_bridge._add_layout_element(elem)
        named = stage3_bridge._set_arcpy_layout_name(
            "GRAPHIC_ELEMENT",
            name,
            x=b["x"],
            y=b["y"],
        )
        return {
            "ok": True,
            "name": name,
            "backend": backend,
            "name_persisted": bool(named),
        }
    except Exception as exc:
        return {"ok": False, "name": name, "error": str(exc)}


def _style_text_element(name, align="CENTER", font_name="Arial"):
    mxd = get_mxd()
    rows = arcpy.mapping.ListLayoutElements(mxd, "TEXT_ELEMENT", name)
    if not rows:
        return
    elem = rows[0]
    try:
        elem.fontName = str(font_name or "Arial")
    except Exception:
        pass
    try:
        obj = getattr(elem, "_arc_object", None)
        symbol = getattr(obj, "Symbol", None) if obj is not None else None
        if symbol is not None:
            alignment = {"LEFT": 0, "CENTER": 1, "RIGHT": 2}.get(str(align).upper(), 1)
            for attr in ("HorizontalAlignment", "HorzAlignment"):
                try:
                    setattr(symbol, attr, alignment)
                    break
                except Exception:
                    pass
            try:
                obj.Symbol = symbol
            except Exception:
                pass
    except Exception:
        pass


def _create_text(name, text, box, font_size=8.0, bold=False, align="CENTER", font_name="Arial"):
    if stage3_bridge is None:
        return {"ok": False, "name": name, "error": "stage3 bridge unavailable"}
    b = box or {}
    align_u = str(align or "CENTER").upper()
    if align_u == "LEFT":
        x_frac = float(b.get("x") or 0) + float(b.get("w") or 0) * 0.04
    elif align_u == "RIGHT":
        x_frac = float(b.get("x") or 0) + float(b.get("w") or 0) * 0.96
    else:
        x_frac = float(b.get("x") or 0) + float(b.get("w") or 0) / 2.0
    y_frac = float(b.get("y") or 0) + float(b.get("h") or 0) / 2.0
    try:
        result = dict({"ok": True}, **stage3_bridge._create_text_impl(
            str(text or " "),
            name,
            x_frac,
            y_frac,
            float(font_size),
            bool(bold),
            align_u
        ))
        _style_text_element(name, align=align_u, font_name=font_name)
        return result
    except Exception as exc:
        return {"ok": False, "name": name, "error": str(exc)}


def _surround(kind, name, box, title="", units=""):
    if stage3_bridge is None:
        return {"ok": False, "name": name, "error": "stage3 bridge unavailable"}
    mxd = get_mxd()
    try:
        types = ["LEGEND_ELEMENT"] if kind == "legend" else ["MAPSURROUND_ELEMENT"]
        for etype in types:
            existing = arcpy.mapping.ListLayoutElements(mxd, etype, name)
            if existing:
                e = existing[0]
                page_w, page_h = _page_size(mxd)
                b = _norm_box(box, page_w, page_h)
                e.elementPositionX = b["x"]
                e.elementPositionY = b["y"]
                e.elementWidth = b["w"]
                e.elementHeight = b["h"]
                if kind == "legend" and title:
                    try:
                        e.title = title
                    except Exception:
                        pass
                return {"ok": True, "name": name, "kind": kind, "created": False, "updated": True}
        b = box or {}
        return dict({"ok": True}, **stage3_bridge._create_surround(
            kind,
            name,
            float(b.get("x") or 0),
            float(b.get("y") or 0),
            float(b.get("w") or 0),
            float(b.get("h") or 0),
            title=title,
            units=units,
        ))
    except Exception as exc:
        return {"ok": False, "name": name, "error": str(exc)}


def _create_panel(layout):
    results = []
    page_neatline = layout.get("page_neatline_box") or {"x": 0.006, "y": 0.008, "w": 0.988, "h": 0.984}
    main_map = layout.get("main_map_box") or {}
    panel = layout.get("side_panel_box") or {}
    results.append(_create_rectangle(
        "ZAGENT_PAGE_NEATLINE",
        page_neatline,
        fill_rgb=None,
        line_rgb=[0, 0, 0],
        line_width=1.0,
    ))
    results.append(_create_rectangle(
        "ZAGENT_MAIN_MAP_NEATLINE",
        main_map,
        fill_rgb=None,
        line_rgb=[0, 0, 0],
        line_width=1.0,
    ))
    results.append(_create_rectangle("ZAGENT_SIDE_PANEL", panel, fill_rgb=[255, 255, 255], line_rgb=[0, 0, 0], line_width=1.0))
    sections = layout.get("section_boxes") or {}
    for section_id, box in sections.items():
        results.append(_create_rectangle(
            "ZAGENT_SECTION_%s" % str(section_id).upper(),
            box,
            fill_rgb=None,
            line_rgb=[0, 0, 0],
            line_width=0.7,
        ))
    return results


def _configure_title(layout):
    title = layout.get("title") or {}
    lines = title.get("lines") or []
    text = "\n".join([str(x) for x in lines])
    return _create_text(
        "ZAGENT_TITLE_BLOCK",
        text,
        title.get("box") or {},
        font_size=float(title.get("font_size_pt") or 15.0),
        bold=True,
    )


def _spatial_reference_values(df):
    values = {}
    try:
        sr = getattr(df, "spatialReference", None)
        if sr is None:
            return values
        values["coordinate_system"] = str(getattr(sr, "name", "") or "")
        values["projection"] = str(
            getattr(sr, "projectionName", "")
            or getattr(sr, "projectionCode", "")
            or ""
        )
        values["datum"] = str(
            getattr(sr, "datumName", "")
            or getattr(sr, "GCSName", "")
            or ""
        )
        values["units"] = str(
            getattr(sr, "linearUnitName", "")
            or getattr(sr, "angularUnitName", "")
            or ""
        )
        try:
            values["factory_code"] = int(getattr(sr, "factoryCode", 0) or 0)
        except Exception:
            pass
    except Exception:
        pass
    return values


def _configure_crs(layout, df=None):
    block = layout.get("crs_block") or {}
    values = dict(block.get("values") or {})
    if df is not None:
        actual = _spatial_reference_values(df)
        for key, value in actual.items():
            if value not in (None, ""):
                values[key] = value
        block["values"] = values
    rows = [
        "Coordinate System : %s" % str(values.get("coordinate_system") or ""),
        "Projection        : %s" % str(values.get("projection") or ""),
        "Datum             : %s" % str(values.get("datum") or ""),
        "Units             : %s" % str(values.get("units") or ""),
    ]
    return _create_text("ZAGENT_CRS_BLOCK", "\n".join(rows), block.get("box") or {}, font_size=7.4, bold=False, align="LEFT")


def _configure_provenance(layout):
    block = layout.get("provenance_block") or {}
    items = block.get("items") or []
    rows = ["Sumber Data dan Riwayat Peta:"]
    for idx, item in enumerate(items):
        label = str(item.get("label") or "")
        year = item.get("year")
        rows.append("%d. %s%s" % (idx + 1, label, (" %s" % year) if year else ""))
    return _create_text("ZAGENT_PROVENANCE_BLOCK", "\n".join(rows), block.get("box") or {}, font_size=7.2, bold=False, align="LEFT")


def _nice_ground_length(scale):
    try:
        target = float(scale or 0) * 0.055
        if target <= 0:
            return 0.0
        exponent = math.floor(math.log10(target))
        base = 10.0 ** exponent
        normalized = target / base
        selected = 1.0
        for candidate in (1.0, 2.0, 2.5, 5.0, 10.0):
            if candidate <= normalized:
                selected = candidate
            else:
                break
        return selected * base
    except Exception:
        return 0.0


def _configure_scale_bar_properties(mxd, scale, spec=None):
    spec = spec or {}
    rows = arcpy.mapping.ListLayoutElements(mxd, "MAPSURROUND_ELEMENT", "ZAGENT_SCALE_BAR")
    if not rows:
        return {"ok": False, "warning": "scale bar element not found"}
    elem = rows[0]
    divisions = int(spec.get("segments") or 4)
    subdivisions = int(spec.get("subdivisions") or 2)
    total = float(spec.get("total_ground_length") or _nice_ground_length(scale))
    division = total / float(max(1, divisions)) if total else 0.0
    try:
        ao = getattr(elem, "_arc_object", None)
        surround = None
        for attr in ("MapSurround", "Surround"):
            try:
                surround = getattr(ao, attr)
                if surround is not None:
                    break
            except Exception:
                pass
        if surround is None:
            surround = ao
        for attr, value in (
            ("Divisions", divisions),
            ("NumDivisions", divisions),
            ("Subdivisions", subdivisions),
            ("NumSubdivisions", subdivisions),
            ("Division", division),
            ("DivisionValue", division),
        ):
            try:
                setattr(surround, attr, value)
            except Exception:
                pass
        return {
            "ok": True,
            "divisions": divisions,
            "subdivisions": subdivisions,
            "total_ground_length": total,
            "division_ground_length": division,
        }
    except Exception as exc:
        return {"ok": False, "warning": str(exc)}


def _configure_orientation_scale(layout, scale):
    box = (layout.get("orientation_scale") or {}).get("box") or {}
    x = float(box.get("x") or 0)
    y = float(box.get("y") or 0)
    w = float(box.get("w") or 0)
    h = float(box.get("h") or 0)
    results = []
    results.append(_surround(
        "north_arrow",
        "ZAGENT_NORTH_ARROW",
        {"x": x + 0.03 * w, "y": y + 0.12 * h, "w": 0.24 * w, "h": 0.70 * h},
    ))
    results.append(_surround(
        "scale_bar",
        "ZAGENT_SCALE_BAR",
        {"x": x + 0.38 * w, "y": y + 0.08 * h, "w": 0.54 * w, "h": 0.32 * h},
        units="Meter",
    ))
    results.append(_configure_scale_bar_properties(
        get_mxd(),
        scale,
        ((layout.get("orientation_scale") or {}).get("scale_bar") or {}),
    ))
    scale_text = "Skala 1 : %s" % ("{0:,.0f}".format(float(scale)).replace(",", ".") if scale else "-")
    results.append(_create_text(
        "ZAGENT_SCALE_TEXT",
        scale_text,
        {"x": x + 0.34 * w, "y": y + 0.48 * h, "w": 0.60 * w, "h": 0.34 * h},
        font_size=8.2,
        bold=False,
    ))
    return results


def _configure_legend(mxd, layout):
    box = (layout.get("legend") or {}).get("box") or {}
    title = (layout.get("legend") or {}).get("title") or "LEGENDA"
    result = _surround("legend", "ZAGENT_LEGEND", box, title=title)
    try:
        arcpy.RefreshActiveView()
        legends = arcpy.mapping.ListLayoutElements(mxd, "LEGEND_ELEMENT", "ZAGENT_LEGEND")
        if legends:
            legend = legends[0]
            wanted = set(
                str(x.get("layer_name"))
                for x in ((layout.get("legend") or {}).get("items") or [])
                if x.get("layer_name")
            )
            ordered = [
                str(x.get("layer_name"))
                for x in ((layout.get("legend") or {}).get("items") or [])
                if x.get("layer_name")
            ]
            if wanted:
                for lyr in list(legend.listLegendItemLayers())[::-1]:
                    if lyr.name not in wanted:
                        try:
                            legend.removeItem(lyr)
                        except Exception:
                            pass
            # Highest-priority semantic item should appear first in legend.
            try:
                present = dict((lyr.name, lyr) for lyr in legend.listLegendItemLayers())
                previous = None
                for name in ordered:
                    lyr = present.get(name)
                    if lyr is None:
                        continue
                    if previous is not None:
                        try:
                            legend.moveItem(previous, lyr, "AFTER")
                        except Exception:
                            pass
                    previous = lyr
            except Exception:
                pass
            try:
                legend.adjustColumnCount(1)
            except Exception:
                pass
    except Exception:
        pass
    return result


def _ensure_dataframe_frame(mxd, name, box):
    existing = arcpy.mapping.ListDataFrames(mxd, name)
    if existing:
        try:
            _set_dataframe_box(mxd, name, box)
        except Exception:
            pass
        return existing[0], False, None
    if stage3_bridge is None:
        return None, False, "stage3 bridge unavailable"
    try:
        app, doc, pl, backend = stage3_bridge._layout_container()
        map_obj, _ = stage3_bridge._create_com(["esriCarto.Map"])
        frame, _ = stage3_bridge._create_com(["esriCarto.MapFrame"])
        map_iface = map_obj
        frame_iface = frame
        try:
            client, framework, arcmapui, carto = stage3_bridge._typed_arcobjects_modules()
            map_iface = map_obj.QueryInterface(carto.IMap)
            frame_iface = frame.QueryInterface(carto.IMapFrame)
        except Exception:
            pass
        try:
            map_iface.Name = name
        except Exception:
            try:
                map_obj.Name = name
            except Exception:
                pass
        maps = doc.Maps
        maps.Add(map_iface)
        frame_iface.Map = map_iface
        stage3_bridge._set_element_name(frame, name)
        page_w, page_h = _page_size(mxd)
        b = _norm_box(box, page_w, page_h)
        env, _ = stage3_bridge._make_envelope(b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"])
        stage3_bridge._set_element_geometry(frame, env)
        stage3_bridge._add_layout_element(frame)
        arcpy.RefreshActiveView()
        rows = arcpy.mapping.ListDataFrames(mxd, name)
        return (rows[0] if rows else None), True, None
    except Exception as exc:
        return None, False, str(exc)


def _inset_boxes(container, count):
    x = float(container.get("x") or 0)
    y = float(container.get("y") or 0)
    w = float(container.get("w") or 0)
    h = float(container.get("h") or 0)
    count = max(1, int(count or 1))
    gap = w * 0.04
    cell_w = (w - gap * (count - 1)) / float(count)
    boxes = []
    for idx in range(count):
        boxes.append({
            "x": x + idx * (cell_w + gap),
            "y": y + 0.06 * h,
            "w": cell_w,
            "h": 0.76 * h,
        })
    return boxes


def _add_extent_indicator(main_df, inset_df, name, highlight):
    try:
        mxd = get_mxd()
        existing = _find_layer(mxd, inset_df, name)
        if existing is not None:
            return True

        extent = main_df.extent
        sr = main_df.spatialReference
        arr = arcpy.Array([
            arcpy.Point(extent.XMin, extent.YMin),
            arcpy.Point(extent.XMax, extent.YMin),
            arcpy.Point(extent.XMax, extent.YMax),
            arcpy.Point(extent.XMin, extent.YMax),
            arcpy.Point(extent.XMin, extent.YMin),
        ])
        geom = arcpy.Polygon(arr, sr)
        try:
            target_sr = inset_df.spatialReference
            if target_sr and sr and target_sr.name != sr.name:
                geom = geom.projectAs(target_sr)
        except Exception:
            pass

        # Extent indicators are part of the saved MXD contract, so they must
        # not use the ArcPy in_memory workspace. Persist one deterministic
        # shapefile per inset under the project-local .zagent workspace.
        document_path = str(getattr(mxd, "filePath", "") or "")
        if not document_path:
            raise RuntimeError("CURRENT MXD filePath unavailable for persistent extent indicator")
        project_root = os.path.dirname(os.path.abspath(document_path))
        indicator_root = os.path.join(
            project_root, ".zagent", "cartography", "extent_indicators"
        )
        if not os.path.isdir(indicator_root):
            os.makedirs(indicator_root)

        inset_token = "".join(
            ch if (ch.isalnum() or ch in ("_", "-")) else "_"
            for ch in str(getattr(inset_df, "name", "") or "INSET")
        )
        fc_name = "MAIN_MAP_EXTENT_%s.shp" % inset_token
        fc = os.path.join(indicator_root, fc_name)

        try:
            if arcpy.Exists(fc):
                arcpy.Delete_management(fc)
        except Exception:
            pass

        previous_add_outputs = getattr(arcpy.env, "addOutputsToMap", True)
        try:
            arcpy.env.addOutputsToMap = False
            arcpy.CreateFeatureclass_management(
                indicator_root,
                fc_name,
                "POLYGON",
                spatial_reference=geom.spatialReference,
            )
        finally:
            try:
                arcpy.env.addOutputsToMap = previous_add_outputs
            except Exception:
                pass

        with arcpy.da.InsertCursor(fc, ["SHAPE@"]) as cursor:
            cursor.insertRow([geom])

        lyr = arcpy.mapping.Layer(fc)
        lyr.name = name
        arcpy.mapping.AddLayer(inset_df, lyr, "TOP")
        row = {
            "line_rgb": (highlight or {}).get("highlight_rgb") or [255, 255, 0],
            "line_width_pt": (highlight or {}).get("highlight_width_pt") or 1.8,
            "fill_rgb": [255, 255, 0],
            "fill_transparency": 100,
        }
        _set_symbol_style(_find_layer(get_mxd(), inset_df, name), row)
        return True
    except Exception:
        return False


def _configure_insets(mxd, main_df, layout, inset_spec):
    items = (inset_spec or {}).get("items") or []
    container = layout.get("insets_box") or {}
    boxes = _inset_boxes(container, max(1, len(items)))
    results = []
    for idx, item in enumerate(items):
        if idx >= len(boxes):
            break
        name = str(item.get("name") or "INSET_%02d" % (idx + 1))
        box = boxes[idx]
        df, created, error = _ensure_dataframe_frame(mxd, name, box)
        row = {"name": name, "created": created, "error": error, "path": item.get("path")}
        if df is not None and item.get("path") and os.path.exists(str(item.get("path"))):
            try:
                added = _find_layer(mxd, df, "BASEMAP_%s" % name)
                if added is None:
                    lyr = _safe_make_layer(str(item.get("path")), "zagent_inset_%s" % idx)
                    try:
                        lyr.name = "BASEMAP_%s" % name
                    except Exception:
                        pass
                    arcpy.mapping.AddLayer(df, lyr, "BOTTOM")
                    added = _find_layer(mxd, df, "BASEMAP_%s" % name)
                if added is not None:
                    try:
                        df.extent = added.getExtent(True)
                        df.scale = df.scale * 1.04
                    except Exception:
                        pass
                row["extent_indicator"] = _add_extent_indicator(
                    main_df,
                    df,
                    "MAIN_MAP_EXTENT",
                    (inset_spec or {}).get("highlight") or {},
                )
                try:
                    scale_text = "INSET PETA\nSKALA 1 : %s" % (
                        "{0:,.0f}".format(float(df.scale)).replace(",", ".")
                    )
                    title_box = {
                        "x": box["x"],
                        "y": box["y"] + box["h"] + 0.006,
                        "w": box["w"],
                        "h": max(0.025, box["h"] * 0.15),
                    }
                    row["title_element"] = _create_text(
                        "ZAGENT_INSET_TITLE_%02d" % (idx + 1),
                        scale_text,
                        title_box,
                        font_size=6.5,
                        bold=False,
                    )
                except Exception as exc:
                    row["title_warning"] = str(exc)
            except Exception as exc:
                row["error"] = str(exc)
        results.append(row)
    return results


def _runtime_grid_interval(df, grid_cfg):
    try:
        extent = df.extent
        span = max(abs(float(extent.XMax) - float(extent.XMin)), abs(float(extent.YMax) - float(extent.YMin)))
        if span <= 0:
            return None
        raw = span / float(max(4, min(8, int((grid_cfg or {}).get("max_lines_per_axis") or 6))))
        sr = getattr(df, "spatialReference", None)
        is_geographic = str(getattr(sr, "type", "") or "").lower() == "geographic"
        if is_geographic:
            candidates = [
                1.0/3600.0, 2.0/3600.0, 5.0/3600.0, 10.0/3600.0,
                15.0/3600.0, 30.0/3600.0, 1.0/60.0, 2.0/60.0,
                5.0/60.0, 10.0/60.0, 15.0/60.0, 30.0/60.0,
                1.0, 2.0, 5.0,
            ]
            return min(candidates, key=lambda value: abs(value - raw))
        exponent = math.floor(math.log10(raw))
        base = 10.0 ** exponent
        normalized = raw / base
        for candidate in (1.0, 2.0, 2.5, 5.0, 10.0):
            if normalized <= candidate:
                return candidate * base
        return 10.0 * base
    except Exception:
        return None


def _map_grid_exists(grids, name):
    try:
        count = int(getattr(grids, "MapGridCount"))
    except Exception:
        count = 0
    for index in range(count):
        grid = None
        for accessor in ("get_MapGrid", "MapGrid"):
            try:
                value = getattr(grids, accessor)
                grid = value(index) if callable(value) else value[index]
                break
            except Exception:
                pass
        if grid is not None:
            try:
                if str(getattr(grid, "Name", "") or "") == name:
                    return True
            except Exception:
                pass
    return False


def _configure_grid(df, grid_cfg):
    if not (grid_cfg or {}).get("enabled"):
        return {"ok": True, "enabled": False}
    interval = (grid_cfg or {}).get("interval") or _runtime_grid_interval(df, grid_cfg)
    if not interval or stage3_bridge is None:
        return {"ok": False, "enabled": True, "warning": "grid interval/backend unavailable"}
    try:
        app, doc, pl, backend = stage3_bridge._layout_container()
        diagnostics = []
        client, framework, arcmapui, carto = stage3_bridge._typed_arcobjects_modules()

        # ArcObjects canonical path: the active PageLayout view is an
        # IGraphicsContainer; FindFrame expects the actual IMap, not a frame
        # name. The returned MapFrame implements IMapGrids.
        active_view = doc.ActiveView
        graphics = active_view.QueryInterface(carto.IGraphicsContainer)
        map_obj = doc.FocusMap
        try:
            map_iface = map_obj.QueryInterface(carto.IMap)
        except Exception:
            map_iface = map_obj
        frame = graphics.FindFrame(map_iface)

        # Fallback to the ArcPy data-frame layout element only if the canonical
        # ArcObjects lookup is unavailable on this installation.
        if frame is None:
            frame_elements = arcpy.mapping.ListLayoutElements(
                get_mxd(), "DATAFRAME_ELEMENT", df.name
            )
            if not frame_elements:
                frame_elements = arcpy.mapping.ListLayoutElements(
                    get_mxd(), "DATAFRAME_ELEMENT"
                )
            if frame_elements:
                frame = getattr(frame_elements[0], "_arc_object", None)
        if frame is None:
            raise RuntimeError("MapFrame unavailable for grid")

        grid, _ = stage3_bridge._create_com(["esriCarto.Graticule"])
        try:
            grid.Name = "ZAGENT_GRATICULE"
        except Exception:
            pass
        try:
            dms, _ = stage3_bridge._create_com(["esriCarto.DMSGridLabel"])
            for attr, value in (
                ("ShowTopLabels", True),
                ("ShowBottomLabels", True),
                ("ShowLeftLabels", True),
                ("ShowRightLabels", True),
                ("ShowLabels", True),
                ("LabelSides", 15),
            ):
                try:
                    setattr(dms, attr, value)
                except Exception:
                    pass
            for attr in ("LabelFormat", "GridLabel"):
                try:
                    setattr(grid, attr, dms)
                    break
                except Exception:
                    pass
        except Exception:
            pass
        try:
            line, _ = stage3_bridge._create_com(["esriDisplay.SimpleLineSymbol"])
            line.Color = _rgb([100, 100, 100], 45)
            line.Width = 0.25
            for attr in ("LineSymbol", "GridLineSymbol"):
                try:
                    setattr(grid, attr, line)
                    break
                except Exception:
                    pass
        except Exception:
            pass
        for attr in ("XIntervalSize", "XInterval", "IntervalX"):
            try:
                setattr(grid, attr, float(interval))
                break
            except Exception:
                pass
        for attr in ("YIntervalSize", "YInterval", "IntervalY"):
            try:
                setattr(grid, attr, float(interval))
                break
            except Exception:
                pass
        added = False
        try:
            grids = frame.QueryInterface(carto.IMapGrids)
            try:
                grid_iface = grid.QueryInterface(carto.IMapGrid)
            except Exception:
                grid_iface = grid
            if _map_grid_exists(grids, "ZAGENT_GRATICULE"):
                added = True
            else:
                grids.AddMapGrid(grid_iface)
                added = True
        except Exception as exc:
            diagnostics.append("typed IMapGrids/AddMapGrid: %s" % exc)
            # ArcPy layout-element fallback for older wrapper combinations.
            try:
                frame_elements = arcpy.mapping.ListLayoutElements(
                    get_mxd(), "DATAFRAME_ELEMENT", df.name
                )
                if not frame_elements:
                    frame_elements = arcpy.mapping.ListLayoutElements(
                        get_mxd(), "DATAFRAME_ELEMENT"
                    )
                frame_ao = (
                    getattr(frame_elements[0], "_arc_object", None)
                    if frame_elements else None
                )
                if frame_ao is not None:
                    grids = frame_ao.QueryInterface(carto.IMapGrids)
                    try:
                        grid_iface = grid.QueryInterface(carto.IMapGrid)
                    except Exception:
                        grid_iface = grid
                    if _map_grid_exists(grids, "ZAGENT_GRATICULE"):
                        added = True
                    else:
                        grids.AddMapGrid(grid_iface)
                        added = True
            except Exception as fallback_exc:
                diagnostics.append(
                    "arcpy-frame IMapGrids/AddMapGrid: %s" % fallback_exc
                )
        result = {
            "ok": added,
            "enabled": True,
            "interval": interval,
            "backend": backend,
        }
        if diagnostics:
            result["diagnostics"] = diagnostics
        return result
    except Exception as exc:
        return {"ok": False, "enabled": True, "interval": interval, "warning": str(exc)}


def _apply_scale_extent(mxd, df, program):
    scale_grid = program.get("scale_grid") or {}
    scale = scale_grid.get("scale")
    boundary_name = None
    for row in program.get("layers") or []:
        if row.get("role") == "project_boundary":
            boundary_name = row.get("layer_name")
            break
    if boundary_name:
        lyr = _find_layer(mxd, df, boundary_name)
        if lyr is not None:
            try:
                df.extent = lyr.getExtent(True)
                df.scale = df.scale * 1.15
            except Exception:
                pass
    if scale:
        try:
            df.scale = float(scale)
        except Exception:
            pass
    return getattr(df, "scale", None)


def _apply_layer_order(mxd, df, names):
    ordered = [str(x) for x in (names or []) if x]
    current = arcpy.mapping.ListLayers(mxd, "", df)
    lookup = dict((lyr.name, lyr) for lyr in current)
    # Input order is bottom -> top. Move from bottom upward.
    anchor = None
    for name in ordered:
        lyr = lookup.get(name)
        if lyr is None:
            continue
        if anchor is None:
            anchor = lyr
            continue
        try:
            arcpy.mapping.MoveLayer(df, anchor, lyr, "BEFORE")
        except Exception:
            pass
        anchor = lyr


def _boxes_overlap(a, b):
    if not a or not b:
        return False
    ax1, ay1 = float(a.get("x") or 0), float(a.get("y") or 0)
    ax2, ay2 = ax1 + float(a.get("w") or 0), ay1 + float(a.get("h") or 0)
    bx1, by1 = float(b.get("x") or 0), float(b.get("y") or 0)
    bx2, by2 = bx1 + float(b.get("w") or 0), by1 + float(b.get("h") or 0)
    return not (ax2 <= bx1 or bx2 <= ax1 or ay2 <= by1 or by2 <= ay1)


def _normalized_layout_box(mxd, element_type, name):
    try:
        rows = arcpy.mapping.ListLayoutElements(mxd, element_type, name or "")
        if not rows:
            return None
        e = rows[0]
        page_w, page_h = _page_size(mxd)
        if page_w <= 0 or page_h <= 0:
            return None
        return {
            "x": float(e.elementPositionX) / page_w,
            "y": float(e.elementPositionY) / page_h,
            "w": float(e.elementWidth) / page_w,
            "h": float(e.elementHeight) / page_h,
        }
    except Exception:
        return None


def _grid_exists_for_df(df):
    if stage3_bridge is None:
        return False
    try:
        app, doc, pl, backend = stage3_bridge._layout_container()
        frame = pl.FindFrame(df.name)
        client, framework, arcmapui, carto = stage3_bridge._typed_arcobjects_modules()
        grids = frame.QueryInterface(carto.IMapGrids)
        return int(getattr(grids, "MapGridCount")) > 0
    except Exception:
        return False


def _metrics(mxd, df, program, layout_results, inset_results, grid_result):
    layout = program.get("layout") or {}
    broken = []
    try:
        broken = [getattr(x, "name", str(x)) for x in arcpy.mapping.ListBrokenDataSources(mxd)]
    except Exception:
        pass
    legend_present = bool(arcpy.mapping.ListLayoutElements(mxd, "LEGEND_ELEMENT", "ZAGENT_LEGEND"))
    north_present = bool(arcpy.mapping.ListLayoutElements(mxd, "MAPSURROUND_ELEMENT", "ZAGENT_NORTH_ARROW"))
    scale_present = bool(arcpy.mapping.ListLayoutElements(mxd, "MAPSURROUND_ELEMENT", "ZAGENT_SCALE_BAR"))
    crs_present = bool(arcpy.mapping.ListLayoutElements(mxd, "TEXT_ELEMENT", "ZAGENT_CRS_BLOCK"))
    project_visible = True
    for row in program.get("layers") or []:
        if row.get("role") == "project_boundary":
            lyr = _find_layer(mxd, df, row.get("layer_name"))
            project_visible = bool(lyr is not None and lyr.visible)
            break
    main_box = _normalized_layout_box(mxd, "DATAFRAME_ELEMENT", df.name) or layout.get("main_map_box") or {}
    side_box = _normalized_layout_box(mxd, "GRAPHIC_ELEMENT", "ZAGENT_SIDE_PANEL") or layout.get("side_panel_box") or {}
    overlap_count = 1 if _boxes_overlap(main_box, side_box) else 0
    legend_overflow = False
    try:
        legends = arcpy.mapping.ListLayoutElements(mxd, "LEGEND_ELEMENT", "ZAGENT_LEGEND")
        if legends:
            legend_overflow = bool(legends[0].isOverflowing)
    except Exception:
        pass
    return {
        "main_map_box": main_box,
        "side_panel_box": side_box,
        "legend_present": legend_present,
        "north_arrow_present": north_present,
        "scale_bar_present": scale_present,
        "crs_block_present": crs_present,
        "grid_present": bool((grid_result or {}).get("ok")) or _grid_exists_for_df(df),
        "inset_count": len([
            x for x in arcpy.mapping.ListDataFrames(mxd)
            if str(getattr(x, "name", "") or "").upper().startswith("INSET_")
        ]),
        "legend_overflow": legend_overflow,
        "layout_overlap_count": overlap_count,
        "broken_data_sources": broken,
        "project_boundary_visible": project_visible,
        "scale": getattr(df, "scale", None),
        "layout_operation_count": len(layout_results or []),
    }


def _apply_repairs(mxd, df, program):
    results = []
    layout = program.get("layout") or {}
    for op in program.get("repair_operations") or []:
        action_name = op.get("action")
        if action_name == "zoom_main_map":
            try:
                df.scale = df.scale * float(op.get("factor") or 0.9)
                results.append({"action": action_name, "ok": True, "scale": df.scale})
            except Exception as exc:
                results.append({"action": action_name, "ok": False, "error": str(exc)})
        elif action_name == "strengthen_role_style":
            role = op.get("role")
            touched = []
            for row in program.get("symbology") or []:
                if row.get("role") == role:
                    style = dict(row.get("style") or {})
                    style["line_width_pt"] = float(style.get("line_width_pt") or 1.0) + float(op.get("line_width_delta") or 0.5)
                    lyr = _find_layer(mxd, df, row.get("layer_name"))
                    if lyr is not None:
                        _set_symbol_style(lyr, style)
                        touched.append(lyr.name)
            results.append({"action": action_name, "ok": True, "layers": touched})
        elif action_name == "resize_legend":
            try:
                legends = arcpy.mapping.ListLayoutElements(mxd, "LEGEND_ELEMENT", "ZAGENT_LEGEND")
                if not legends:
                    raise RuntimeError("legend not found")
                factor = float(op.get("factor") or 1.15)
                max_factor = float(op.get("max_factor") or 1.45)
                factor = min(factor, max_factor)
                legends[0].elementHeight = legends[0].elementHeight * factor
                results.append({"action": action_name, "ok": True, "factor": factor})
            except Exception as exc:
                results.append({"action": action_name, "ok": False, "error": str(exc)})
        elif action_name == "reduce_legend_font":
            try:
                legends = arcpy.mapping.ListLayoutElements(mxd, "LEGEND_ELEMENT", "ZAGENT_LEGEND")
                if not legends:
                    raise RuntimeError("legend not found")
                legend = legends[0]
                # ArcMap 10.6 exposes limited legend font mutation through arcpy.
                # Increasing width/columns is the deterministic overflow remedy.
                legend.elementWidth = legend.elementWidth * 1.08
                try:
                    legend.adjustColumnCount(2)
                except Exception:
                    pass
                results.append({"action": action_name, "ok": True, "strategy": "expand_width_and_columns"})
            except Exception as exc:
                results.append({"action": action_name, "ok": False, "error": str(exc)})
        elif action_name == "reduce_label_font":
            try:
                plan = program.get("labels") or _runtime_label_plan(mxd, df, program)
                delta = float(op.get("delta_pt") or -0.5)
                minimum = float(op.get("min_pt") or 6.5)
                adjusted = []
                for row in plan:
                    item = dict(row)
                    item["font_size_pt"] = max(minimum, float(item.get("font_size_pt") or 8.5) + delta)
                    adjusted.append(item)
                warnings = _apply_labels(mxd, df, adjusted)
                results.append({"action": action_name, "ok": True, "warnings": warnings})
            except Exception as exc:
                results.append({"action": action_name, "ok": False, "error": str(exc)})
        elif action_name in ("expand_main_map", "shrink_main_map"):
            try:
                box = dict(layout.get("main_map_box") or {})
                delta = float(op.get("delta_ratio") or 0.02)
                if action_name == "shrink_main_map":
                    delta = -abs(delta)
                else:
                    delta = abs(delta)
                max_right = float((layout.get("side_panel_box") or {}).get("x") or 0.985) - 0.01
                box["w"] = max(0.45, min(max_right - float(box.get("x") or 0), float(box.get("w") or 0) + delta))
                layout["main_map_box"] = box
                program["layout"] = layout
                actual = _set_dataframe_box(mxd, df.name, box)
                results.append({"action": action_name, "ok": True, "box": box, "actual": actual})
            except Exception as exc:
                results.append({"action": action_name, "ok": False, "error": str(exc)})
        elif action_name == "snap_layout_to_reference":
            try:
                reference = ((program.get("specification") or {}).get("reference_target") or program.get("reference_target") or {})
                regions = reference.get("regions") or {}
                if regions.get("main_map"):
                    layout["main_map_box"] = dict(regions["main_map"])
                    _set_dataframe_box(mxd, df.name, layout["main_map_box"])
                if regions.get("side_panel"):
                    layout["side_panel_box"] = dict(regions["side_panel"])
                program["layout"] = layout
                rows = _create_panel(layout)
                rows.append(_configure_title(layout))
                rows.extend(_configure_orientation_scale(layout, getattr(df, "scale", None)))
                rows.append(_configure_legend(mxd, layout))
                rows.append(_configure_crs(layout, df))
                rows.append(_configure_provenance(layout))
                results.append({"action": action_name, "ok": True, "operations": rows})
            except Exception as exc:
                results.append({"action": action_name, "ok": False, "error": str(exc)})
        elif action_name == "reflow_side_panel":
            try:
                rows = _create_panel(layout)
                rows.append(_configure_title(layout))
                rows.extend(_configure_orientation_scale(layout, getattr(df, "scale", None)))
                rows.append(_configure_legend(mxd, layout))
                rows.append(_configure_crs(layout, df))
                rows.append(_configure_provenance(layout))
                results.append({"action": action_name, "ok": True, "operations": rows})
            except Exception as exc:
                results.append({"action": action_name, "ok": False, "error": str(exc)})
        elif action_name == "rebuild_insets":
            try:
                rows = _configure_insets(mxd, df, layout, program.get("insets") or {})
                results.append({"action": action_name, "ok": True, "insets": rows})
            except Exception as exc:
                results.append({"action": action_name, "ok": False, "error": str(exc)})
        elif action_name == "rebuild_grid":
            result = _configure_grid(df, ((program.get("scale_grid") or {}).get("grid") or {}))
            results.append({"action": action_name, "ok": bool(result.get("ok")), "grid": result})
        elif action_name == "recreate_required_element":
            code = str(op.get("code") or "")
            try:
                created = None
                if code == "LEGEND_MISSING":
                    created = _configure_legend(mxd, layout)
                elif code == "NORTH_ARROW_MISSING":
                    created = _configure_orientation_scale(layout, getattr(df, "scale", None))[0]
                elif code == "SCALE_BAR_MISSING":
                    created = _configure_orientation_scale(layout, getattr(df, "scale", None))[1]
                elif code == "CRS_BLOCK_MISSING":
                    created = _configure_crs(layout)
                else:
                    created = {"ok": False, "warning": "unsupported required element code"}
                results.append({"action": action_name, "ok": bool((created or {}).get("ok")), "created": created})
            except Exception as exc:
                results.append({"action": action_name, "ok": False, "error": str(exc)})
        elif action_name == "increase_label_priority_filter":
            # ArcPy does not expose the full Maplex priority graph. Keep only
            # authoritative/high-priority label roles when collisions persist.
            try:
                threshold = int(op.get("delta") or 10)
                plan = program.get("labels") or _runtime_label_plan(mxd, df, program)
                filtered = [x for x in plan if int(x.get("priority") or 0) >= threshold]
                warnings = _apply_labels(mxd, df, filtered)
                results.append({"action": action_name, "ok": True, "retained": len(filtered), "warnings": warnings})
            except Exception as exc:
                results.append({"action": action_name, "ok": False, "error": str(exc)})
    return results


@action("apply_cartographic_program")
def apply_cartographic_program(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    program = command.get("program") or {}
    if not isinstance(program, dict):
        return {"ok": False, "error": "program must be an object", "saved": False}

    mxd = get_mxd()
    results = {
        "layers": [],
        "layout": [],
        "insets": [],
        "warnings": [],
        "repairs": [],
    }
    try:
        main_df = _find_df(mxd, str(program.get("data_frame") or ""))
        if str(program.get("mode") or "").lower() == "repair_only":
            results["repairs"] = _apply_repairs(mxd, main_df, program)
            try:
                arcpy.RefreshTOC()
                arcpy.RefreshActiveView()
            except Exception:
                pass
            grid_state = {"ok": bool((program.get("repair_context") or {}).get("grid_present"))}
            inset_state = [
                {"name": "existing_inset_%s" % i}
                for i in range(int((program.get("repair_context") or {}).get("inset_count") or 0))
            ]
            metrics = _metrics(mxd, main_df, program, [], inset_state, grid_state)
            return {
                "ok": True,
                "program_type": program.get("program_type"),
                "mode": "repair_only",
                "metrics": metrics,
                "results": results,
                "saved": False,
            }

        page_result = _set_page_size(((program.get("layout") or {}).get("paper") or {}))
        if not page_result.get("ok"):
            results["warnings"].append(page_result.get("warning"))
        _set_page_background((program.get("layout") or {}).get("page_background_rgb"))

        for row in program.get("layers") or []:
            if row.get("role") == "inset":
                continue
            lyr, created = _ensure_layer(mxd, main_df, row)
            results["layers"].append({
                "layer_name": row.get("layer_name"),
                "created": bool(created),
                "present": bool(lyr is not None),
                "role": row.get("role"),
            })

        _apply_layer_order(mxd, main_df, program.get("layer_order") or [])
        results["warnings"].extend(_apply_symbology(mxd, main_df, program.get("symbology") or []))
        label_plan = program.get("labels") or _runtime_label_plan(mxd, main_df, program)
        results["runtime_label_plan"] = label_plan
        results["maplex"] = _configure_maplex_best_effort(mxd, main_df, label_plan)
        results["warnings"].extend(results["maplex"].get("warnings") or [])
        results["warnings"].extend(_apply_labels(mxd, main_df, label_plan))

        scale = _apply_scale_extent(mxd, main_df, program)
        layout = program.get("layout") or {}
        runtime_admin = _infer_admin_from_layers(mxd, main_df, program)
        results["administrative_inference"] = runtime_admin
        results["title_lines"] = _merge_runtime_admin_title(layout, program, runtime_admin)
        main_box = layout.get("main_map_box") or {}
        _set_dataframe_box(mxd, main_df.name, main_box)

        results["layout"].extend(_create_panel(layout))
        results["layout"].append(_configure_title(layout))
        results["layout"].extend(_configure_orientation_scale(layout, scale))
        results["layout"].append(_configure_legend(mxd, layout))
        results["layout"].append(_configure_crs(layout, main_df))
        results["layout"].append(_configure_provenance(layout))

        results["insets"] = _configure_insets(mxd, main_df, layout, program.get("insets") or {})
        grid_result = _configure_grid(main_df, ((program.get("scale_grid") or {}).get("grid") or {}))
        results["grid"] = grid_result
        if not grid_result.get("ok") and grid_result.get("warning"):
            results["warnings"].append(grid_result.get("warning"))

        results["repairs"] = _apply_repairs(mxd, main_df, program)

        try:
            arcpy.RefreshTOC()
            arcpy.RefreshActiveView()
        except Exception:
            pass

        metrics = _metrics(mxd, main_df, program, results["layout"], results["insets"], grid_result)
        return {
            "ok": True,
            "program_type": program.get("program_type"),
            "metrics": metrics,
            "results": results,
            "saved": False,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "results": results,
            "saved": False,
        }
