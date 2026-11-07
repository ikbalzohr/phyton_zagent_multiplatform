# -*- coding: utf-8 -*-
from __future__ import print_function
import arcpy

def get_mxd():
    try:
        return arcpy.mapping.MapDocument("CURRENT")
    except Exception as exc:
        raise RuntimeError("CURRENT_MXD_UNAVAILABLE: {0}".format(exc))

def get_dataframe(mxd, name=""):
    frames = arcpy.mapping.ListDataFrames(mxd)
    if not frames:
        raise RuntimeError("No data frame exists in CURRENT MXD.")
    if not name:
        try:
            active = mxd.activeDataFrame
            if active is not None:
                return active
        except Exception as exc:
            raise RuntimeError("ACTIVE_DATAFRAME_UNAVAILABLE: {0}".format(exc))
        raise RuntimeError("No active data frame in CURRENT MXD.")
    for df in frames:
        if df.name == name:
            return df
    raise RuntimeError("Data frame not found: {0}".format(name))

def find_layer(mxd, layer_name, data_frame=""):
    matches = []
    for df in arcpy.mapping.ListDataFrames(mxd):
        if data_frame and df.name != data_frame:
            continue
        for lyr in arcpy.mapping.ListLayers(mxd, "", df):
            if lyr.name == layer_name:
                matches.append((df, lyr))
    return matches

def resolve_unique_layer(mxd, layer_name, data_frame=""):
    """Return one (data frame, layer) pair; never select the first duplicate."""
    if not layer_name:
        raise RuntimeError(u"LAYER_NAME_REQUIRED: layer_name is required")
    if data_frame:
        frames = [df for df in arcpy.mapping.ListDataFrames(mxd) if df.name == data_frame]
        if len(frames) > 1:
            raise RuntimeError(u"DATA_FRAME_AMBIGUOUS: {0} ({1} matches)".format(data_frame, len(frames)))
    matches = find_layer(mxd, layer_name, data_frame)
    if not matches:
        raise RuntimeError(u"LAYER_NOT_FOUND: {0}".format(layer_name))
    if len(matches) != 1:
        raise RuntimeError(u"LAYER_AMBIGUOUS: {0} ({1} matches)".format(layer_name, len(matches)))
    return matches[0]

def safe_layer_source(layer):
    try:
        return layer.dataSource
    except Exception:
        return ""
