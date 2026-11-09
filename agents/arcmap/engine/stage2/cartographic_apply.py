# -*- coding: utf-8 -*-
"""Deterministic, Python 2.7-safe cartographic rules applied to a working MXD.

Unsupported ArcMap styling and graticule APIs must be reported, never asserted.
"""
from __future__ import absolute_import
import os
import math

ROLES = ("area", "road", "river", "administration", "other", "basemap")


def classify(layer, area_layer=None):
    if area_layer is not None and layer.name == area_layer.name:
        return "area"
    name = layer.name.upper()
    source = os.path.basename(layer.dataSource).upper() if layer.supports("DATASOURCE") else ""
    both = name + " " + source
    if "JALAN" in both or "ROAD" in both:
        return "road"
    if "SUNGAI" in both or "RIVER" in both:
        return "river"
    if "DESA" in both or "ADMIN" in both or "BATAS" in both:
        return "administration"
    if any(word in both for word in (".ECW", ".TIF", ".IMG", "BASEMAP", "INSET")):
        return "basemap"
    return "other"


def _find_main(mxd, frame, rule, arcpy):
    valid = []
    name_hint = rule.get("layer") or ""
    dataset_hint = rule.get("dataset") or ""
    for lyr in arcpy.mapping.ListLayers(mxd, "", frame):
        if lyr.isGroupLayer or not lyr.visible or not lyr.supports("DATASOURCE"):
            continue
        if name_hint and lyr.name != name_hint:
            continue
        if dataset_hint and os.path.basename(lyr.dataSource).lower() != dataset_hint.lower():
            continue
        # ArcPy Describe(layer).extent is in the current data-frame CRS,
        # while Describe(layer).spatialReference remains the source CRS.
        # Never project that display extent as if it were native coordinates.
        desc = arcpy.Describe(lyr)
        if getattr(desc, "shapeType", "") != "Polygon":
            continue
        try:
            native = arcpy.Describe(lyr.dataSource)
            if getattr(native, "shapeType", "") != "Polygon":
                raise ValueError("MAIN_ACTIVITY_NATIVE_GEOMETRY_INVALID")
            if not getattr(native, "spatialReference", None):
                raise ValueError("MAIN_ACTIVITY_NATIVE_CRS_UNAVAILABLE")
        except (AttributeError, RuntimeError) as exc:
            raise ValueError("MAIN_ACTIVITY_NATIVE_DATASET_UNAVAILABLE: " + str(exc))
        score = 100 if name_hint or dataset_hint else 0
        text = (lyr.name + " " + os.path.basename(lyr.dataSource)).upper()
        score += sum(1 for word in ("AREA", "IUP", "KEGIATAN", "PT", "PL") if word in text)
        score += len(getattr(desc, "fields", []) or []) / 1000.0
        valid.append((score, lyr, native))
    if not valid:
        raise ValueError("MAIN_ACTIVITY_POLYGON_NOT_FOUND_OR_INVALID")
    valid.sort(key=lambda row: row[0], reverse=True)
    if len(valid) > 1 and abs(valid[0][0] - valid[1][0]) <= 0.001:
        raise ValueError("MAIN_ACTIVITY_LAYER_AMBIGUOUS")
    return valid[0][1], valid[0][2]


def _main_bounds(desc, frame, arcpy):
    e = desc.extent
    sr = getattr(desc, "spatialReference", None)
    if sr is None or not sr.name or sr.name == "Unknown":
        raise ValueError("MAIN_ACTIVITY_SPATIAL_REFERENCE_UNKNOWN")
    if sr.name == frame.spatialReference.name:
        return (float(e.XMin), float(e.YMin), float(e.XMax), float(e.YMax))
    pts = []
    for x, y in ((e.XMin, e.YMin), (e.XMin, e.YMax),
                 (e.XMax, e.YMin), (e.XMax, e.YMax)):
        p = arcpy.PointGeometry(arcpy.Point(x, y), sr).projectAs(frame.spatialReference)
        if p is None or p.firstPoint is None:
            raise ValueError("DATASET_CRS_METADATA_INCONSISTENT: %s -> %s; "
                             "do not assume source coordinates" %
                             (sr.name, frame.spatialReference.name))
        pts.append((float(p.firstPoint.X), float(p.firstPoint.Y)))
    return (min(x for x,y in pts), min(y for x,y in pts),
            max(x for x,y in pts), max(y for x,y in pts))


def _bounds_inside(extent, bounds, padding=0.0):
    x0,y0,x1,y1 = bounds
    px = (x1-x0)*padding
    py = (y1-y0)*padding
    return (extent.XMin <= x0-px+1 and extent.YMin <= y0-py+1 and
            extent.XMax >= x1+px-1 and extent.YMax >= y1+py-1)


def _choose_scale(mxd, frame, bounds, rule, arcpy):
    scale_rule = rule["scale"]
    if scale_rule["mode"] == "fixed":
        selected = float(scale_rule["requested"])
        frame.scale = selected
        if not _bounds_inside(frame.extent, bounds):
            raise ValueError("FIXED_SCALE_CROPS_ACTIVITY_AREA")
        return selected, {"mode": "fixed", "reason": "explicit job override"}

    from stage2.print_ready import _page_mm
    page = _page_mm(mxd)
    elements = [e for e in arcpy.mapping.ListLayoutElements(mxd, "DATAFRAME_ELEMENT")
                if e.name == frame.name]
    if len(elements) != 1:
        raise ValueError("MAIN_FRAME_LAYOUT_ELEMENT_AMBIGUOUS")
    e = elements[0]
    mmw = float(e.elementWidth) * page["mm_per_native_unit"]
    mmh = float(e.elementHeight) * page["mm_per_native_unit"]
    if mmw < 30 or mmh < 30:
        raise ValueError("MAIN_FRAME_TOO_SMALL")
    meters = float(getattr(frame.spatialReference, "metersPerUnit", 1.0))
    if getattr(frame.spatialReference, "type", "") != "Projected" or meters <= 0:
        raise ValueError("AUTOSCALE_PROJECTED_CRS_REQUIRED")
    x0,y0,x1,y1 = bounds
    pad = float(scale_rule["padding_fraction"])
    required = max((x1-x0)*(1+2*pad)*meters*1000/mmw,
                   (y1-y0)*(1+2*pad)*meters*1000/mmh)
    denoms = scale_rule["denominators"]
    candidates = [float(v) for v in denoms if v >= required]
    if not candidates:
        raise ValueError("AUTOSCALE_AREA_EXCEEDS_MAX_SUPPORTED_SCALE")
    selected = min(candidates)
    cx,cy = (x0+x1)/2.0,(y0+y1)/2.0
    mapw = selected*mmw/1000/meters
    maph = selected*mmh/1000/meters
    frame.extent = arcpy.Extent(cx-mapw/2,cy-maph/2,cx+mapw/2,cy+maph/2)
    frame.scale = selected
    if not _bounds_inside(frame.extent, bounds, pad*0.97):
        raise ValueError("AUTOSCALE_AREA_NOT_FULLY_VISIBLE")
    return selected, {"mode": "auto", "minimum_needed": round(required,2),
                      "padding_fraction": pad,
                      "area_bounds": [round(v,3) for v in bounds],
                      "reason": "smallest preferred denominator enclosing activity polygon"}


def _rewrite_main_scale_label(text, old_main_scale, selected_scale):
    """Change only the original main-frame scale; preserve inset scale labels."""
    import re
    pat = re.compile(r"(?i)(Skala\s+1\s*:\s*)([0-9][0-9.,]*)")
    def sub(match):
        original = int(re.sub(r"[.,]", "", match.group(2)))
        if abs(original - float(old_main_scale)) > 0.5:
            return match.group(0)
        label = format(int(selected_scale), ",").replace(",", ".")
        return match.group(1) + label
    return pat.sub(sub, text)


def _insets_context(mxd, main, bounds, arcpy):
    changes=[]
    cx,cy=(bounds[0]+bounds[2])/2,(bounds[1]+bounds[3])/2
    origin=arcpy.PointGeometry(arcpy.Point(cx,cy),main.spatialReference)
    for frame in arcpy.mapping.ListDataFrames(mxd):
        if frame.name==main.name:
            continue
        p=origin.projectAs(frame.spatialReference).firstPoint
        e=frame.extent
        if not (e.XMin<=p.X<=e.XMax and e.YMin<=p.Y<=e.YMax):
            width,height=e.XMax-e.XMin,e.YMax-e.YMin
            original_scale=frame.scale
            frame.extent=arcpy.Extent(p.X-width/2,p.Y-height/2,
                                      p.X+width/2,p.Y+height/2)
            frame.scale=original_scale
            changes.append({"frame":frame.name, "action":"recenter_on_activity",
                            "scale":float(frame.scale)})
        else:
            changes.append({"frame":frame.name,"action":"location_within_context",
                            "scale":float(frame.scale)})
    if len(changes)!=2:
        raise ValueError("TWO_INSETS_REQUIRED_FOR_RULES")
    return changes


def apply_rules(mxd, rule_snapshot, main_frame="Layers"):
    from stage2 import engine
    arcpy=engine._arcpy()
    rules=rule_snapshot["rules"]
    frames=[f for f in arcpy.mapping.ListDataFrames(mxd) if f.name==main_frame]
    if len(frames)!=1:
        raise ValueError("MAIN_FRAME_NOT_UNIQUE")
    main=frames[0]
    area, desc=_find_main(mxd,main,rules["area"],arcpy)
    bounds=_main_bounds(desc,main,arcpy)
    initial_main_scale = float(main.scale)
    selected,scale_decision=_choose_scale(mxd,main,bounds,rules,arcpy)
    if not _bounds_inside(main.extent,bounds):
        raise ValueError("ACTIVITY_AREA_CROPPED")
    adjustments=[]
    errors=[]
    for element in arcpy.mapping.ListLayoutElements(mxd,"TEXT_ELEMENT"):
        content=element.text or ""
        is_title="PETA ADMINISTRASI" in content.upper()
        minimum=rules["typography"]["title_min_pt"] if is_title else rules["typography"]["important_min_pt"]
        if element.fontSize<minimum:
            element.fontSize=minimum
            adjustments.append({"element":element.name,"action":"font_minimum","pt":minimum})
        if getattr(element,"fontName","").lower()!="arial":
            element.fontName="Arial"
            adjustments.append({"element":element.name,"action":"font_to_arial"})
        if "SKALA" in content.upper():
            replaced = _rewrite_main_scale_label(content, initial_main_scale, selected)
            if replaced != content:
                element.text = replaced
                adjustments.append({"element":element.name,
                                    "action":"main_scale_label_update",
                                    "old_scale":initial_main_scale,
                                    "new_scale":selected})

    layers=[lyr for lyr in arcpy.mapping.ListLayers(mxd,"",main)
            if not lyr.isGroupLayer and lyr.visible]
    priorities={"administration":{"area":0,"road":1,"river":2,"administration":3,
                                   "other":4,"basemap":5},
                "environment":{"area":0,"river":1,"road":2,"administration":3,
                               "other":4,"basemap":5},
                "mining":{"area":0,"road":1,"river":2,"administration":3,
                          "other":4,"basemap":5}}
    weights=priorities[rules["layers"]["preset"]]
    ordering=sorted(layers,key=lambda l:weights[classify(l,area)])
    if [v.name for v in ordering]!=[v.name for v in layers]:
        for i in range(1,len(ordering)):
            arcpy.mapping.MoveLayer(main,ordering[i-1],ordering[i],"AFTER")
        adjustments.append({"action":"layer_draw_order",
                            "order":[v.name for v in ordering]})

    legends=arcpy.mapping.ListLayoutElements(mxd,"LEGEND_ELEMENT")
    legend_info=[]
    warnings=[]
    if len(legends)!=1:
        warnings.append("LEGEND_ELEMENT_NOT_UNIQUE")
    else:
        actual=[classify(x,area) for x in legends[0].listLegendItemLayers()]
        desired=[r for r in rules["legend"]["order"] if r in actual]
        legend_info=[{"role":role,"source_layer":layer.name}
                     for role,layer in zip(actual,legends[0].listLegendItemLayers())]
        if actual!=desired:
            warnings.append("LEGEND_ORDER_NEEDS_ARCMAP_LAYOUT_REVIEW")
        if "administration" not in actual and any(classify(l,area)=="administration" for l in layers):
            warnings.append("ADMINISTRATION_VISIBLE_BUT_NOT_IN_LEGEND")
    inset_state=_insets_context(mxd,main,bounds,arcpy)
    warnings.extend([
        "ARCMAP_10_6_SYMBOL_COLOR_NOT_PROGRAMMATICALLY_VALIDATED",
        "AUTOMATIC_LABEL_COLLISIONS_AND_LEADER_LINES_REQUIRE_VISUAL_REVIEW",
        "TEMPLATE_GRID_INTERVAL_REQUIRES_VISUAL_VERIFICATION",
        "INSET_LOCATION_MARKERS_REQUIRE_VISUAL_VERIFICATION",
    ])
    return {"main_layer":area.name,"main_source":area.dataSource,
            "selected_scale":selected,"scale_decision":scale_decision,
            "draw_order":[l.name for l in ordering],
            "legend_items":legend_info,"insets":inset_state,
            "adjustments":adjustments,"warnings":warnings}
