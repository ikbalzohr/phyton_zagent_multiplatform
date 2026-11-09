# -*- coding: utf-8 -*-
"""Preserve the ArcMap Add Data default renderer for three-band RGB rasters.

ArcMap 10.6 uses a native raster renderer when arcpy.mapping.Layer(path) is
added to a data frame. A separate MakeRasterLayer/UpdateLayer symbology pass
is unnecessary and can fail with TypeError on ArcPy Layer return objects.
"""
from __future__ import absolute_import
import os


def raster_band_count(source, arcpy):
    count = int(arcpy.Raster(source).bandCount)
    if count < 1:
        raise ValueError('RASTER_BAND_COUNT_INVALID: ' + source)
    return count


def request_rgb_composite(mxd, arcpy):
    """Validate default Add Data raster layers without replacing their renderer.

    This intentionally makes no calls to MakeRasterLayer, UpdateLayer,
    raster processing, or layer creation. Native RGB component assignments
    are subject to independent ArcMap UI/ArcObjects inspection.
    """
    present = []
    for frame in arcpy.mapping.ListDataFrames(mxd):
        for layer in list(arcpy.mapping.ListLayers(mxd, '', frame)):
            if layer.isGroupLayer or not layer.visible:
                continue
            if not getattr(layer, 'isRasterLayer', False):
                continue
            source = layer.dataSource
            bands = raster_band_count(source, arcpy)
            if bands != 3:
                raise ValueError('RGB_NEEDS_VALIDATED_BAND_MAPPING: %s bands=%s' %
                                 (source, bands))
            if getattr(layer, 'isBroken', False):
                raise ValueError('RGB_BASEMAP_SOURCE_BROKEN: ' + source)
            present.append({
                'frame': frame.name,
                'layer': layer.name,
                'source': source,
                'band_count': bands,
                'strategy': 'PRESERVE_ARCMAP_ADD_DATA_DEFAULT',
                'renderer_readback': 'PENDING_ARCMAP_VISUAL_QA'
            })
    return present
