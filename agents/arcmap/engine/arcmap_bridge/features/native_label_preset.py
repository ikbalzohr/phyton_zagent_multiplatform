# -*- coding: utf-8 -*-
"""ARC-05: native label symbol preset and Maplex duplicate thinning."""
import arcpy
from core.registry import action
from core.current_map import get_mxd, find_layer
from core.safety import require_live_write
from features.native_layer_properties import _geo

# Custom named typography preset. Not claimed to be a built-in Esri style item.
PRESETS = {
    "FONT_2": {"size": 10.0, "font_name": "Arial", "bold": False},
    "MAP_TITLE": {"size": 12.0, "font_name": "Arial", "bold": True},
    "SMALL": {"size": 8.0, "font_name": "Arial", "bold": False},
}


def _label_class(lyr, index, carto):
    geo, _ = _geo(lyr)
    coll = geo.AnnotationProperties.QueryInterface(
        carto.IAnnotateLayerPropertiesCollection2)
    if index < 0 or index >= int(coll.Count):
        raise ValueError("label_class_index out of bounds")
    prop, identifier = coll.QueryItem(index)
    label_iface = prop.QueryInterface(carto.ILabelEngineLayerProperties2)
    return geo, coll, prop, identifier, label_iface


@action("native_label_preset")
def native_label_preset(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    matches = find_layer(get_mxd(), command.get("layer_name") or "",
                         command.get("data_frame") or "")
    if len(matches) != 1:
        raise RuntimeError("Exactly one existing layer must be selected")
    df, lyr = matches[0]
    preset = str(command.get("preset") or "FONT_2").upper().replace(" ", "_")
    if preset not in PRESETS:
        raise ValueError("Unknown preset: %s" % preset)
    settings = dict(PRESETS[preset])
    if command.get("size") is not None:
        settings["size"] = float(command["size"])
    if not 1 <= settings["size"] <= 72:
        raise ValueError("font size must be between 1 and 72")
    if command.get("font_name"):
        settings["font_name"] = str(command["font_name"])
    idx = int(command.get("label_class_index", 0))
    # Use the existing CURRENT ArcMap typed ArcObjects resolver.
    geo, carto = _geo(lyr)
    geo, coll, prop, label_id, label = _label_class(lyr, idx, carto)
    symbol = label.Symbol
    symbol.Size = settings["size"]
    font = symbol.Font
    if font is None:
        raise RuntimeError("Label text symbol lacks an editable font")
    font.Name = settings["font_name"]
    font.Bold = bool(settings["bold"])
    symbol.Font = font
    label.Symbol = symbol
    if command.get("remove_duplicates") is not None:
        try:
            maplex = label.OverposterLayerProperties.QueryInterface(
                carto.IMaplexOverposterLayerProperties)
        except Exception:
            raise RuntimeError("Duplicate thinning requires a Maplex label class")
        maplex.ThinDuplicateLabels = bool(command["remove_duplicates"])
        if command.get("thinning_distance") is not None:
            distance = float(command["thinning_distance"])
            if distance <= 0:
                raise ValueError("thinning_distance must be positive")
            maplex.ThinningDistance = distance
    coll.Replace(label_id, prop)
    geo.AnnotationProperties = coll
    geo.DisplayAnnotation = True
    arcpy.RefreshActiveView()
    return {"ok": True, "layer_name": lyr.name, "data_frame": df.name,
            "preset": preset, "size": settings["size"],
            "saved": False, "verified_on_arcmap": False}
