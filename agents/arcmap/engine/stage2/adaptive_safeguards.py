# -*- coding: utf-8 -*-
"""Output and inset safeguards for ArcMap 10.x Python 2.7 workers."""
from __future__ import absolute_import
import os


def unused_output_stem(stem, project_root, limit=9999):
    """Choose a matching MXD/PDF/PNG basename without replacing an existing MXD."""
    if not stem or os.path.basename(stem) != stem or stem in ('.', '..'):
        raise ValueError('INVALID_OUTPUT_STEM')
    if not os.path.isdir(project_root):
        raise ValueError('PROJECT_ROOT_NOT_FOUND')
    for number in range(1, limit + 1):
        name = stem if number == 1 else '%s_v%s' % (stem, number)
        if not os.path.lexists(os.path.join(project_root, name + '.mxd')):
            return name
    raise ValueError('NO_FREE_PROJECT_MXD_NAME')


def is_inset_raster(layer):
    if not layer.supports('DATASOURCE'):
        return False
    source = os.path.basename(layer.dataSource).upper()
    return (source.startswith('INSET_') and
            source.endswith(('.ECW', '.TIF', '.TIFF', '.IMG', '.SID')))


def keep_only_inset_basemaps(mxd, main_frame, arcpy):
    """Remove *working-copy* inset overlays and reject ambiguous raster selection."""
    report = []
    frames = [f for f in arcpy.mapping.ListDataFrames(mxd)
              if f.name != main_frame]
    if len(frames) != 2:
        raise ValueError('TWO_INSET_FRAMES_REQUIRED')
    selected_sources = set()
    for frame in frames:
        layers = list(arcpy.mapping.ListLayers(mxd, '', frame))
        if any(layer.isGroupLayer for layer in layers):
            raise ValueError('INSET_GROUP_LAYER_NEEDS_UNGROUPING: ' + frame.name)
        candidates = [l for l in layers if is_inset_raster(l)]
        if len(candidates) != 1:
            raise ValueError('INSET_BASEMAP_NOT_UNIQUE: %s count=%s' %
                             (frame.name, len(candidates)))
        keep = candidates[0]
        source = os.path.normcase(os.path.abspath(keep.dataSource))
        if source in selected_sources:
            raise ValueError('INSET_BASEMAP_REUSED: %s' % source)
        selected_sources.add(source)
        removed = []
        for layer in layers:
            if layer is not keep:
                removed.append(layer.name)
                arcpy.mapping.RemoveLayer(frame, layer)
        keep.visible = True
        report.append({'frame': frame.name, 'basemap': keep.name,
                       'source': keep.dataSource, 'removed_overlays': removed})
        remaining = [l for l in arcpy.mapping.ListLayers(mxd, '', frame)
                     if not l.isGroupLayer]
        if len(remaining) != 1 or not is_inset_raster(remaining[0]):
            raise ValueError('INSET_LAYER_QA_FAILED: ' + frame.name)
    return report
