# -*- coding: utf-8 -*-
"""Bootstrap a genuinely empty user MXD using a sanitized, data-free A4 scaffold.

ArcPy 10.6 cannot create new data frames or map surrounds from an existing
disk MXD. The packaged scaffold supplies only ArcObjects layout primitives;
all user datasets, labels, identity, scales and CRS are determined afresh.
Never writes to the user's input MXD or GIS datasets.
"""
from __future__ import absolute_import
import os
import shutil

from stage2 import engine

RASTERS = ('.ecw', '.tif', '.tiff', '.img', '.sid')
SEED = os.path.join(os.path.dirname(__file__), 'assets',
                    'blank_a4_landscape.mxd')


def is_blank(mxd, arcpy, main_name='Layers'):
    frames = list(arcpy.mapping.ListDataFrames(mxd))
    return (len(frames) == 1 and frames[0].name == main_name and
            not list(arcpy.mapping.ListLayers(mxd, '', frames[0])))


def _files(folder, extensions):
    if not os.path.isdir(folder):
        return []
    return sorted(os.path.join(folder, name)
                  for name in os.listdir(folder)
                  if os.path.splitext(name)[1].lower() in extensions
                  and os.path.isfile(os.path.join(folder, name)))


def _project_polygon(data_root, arcpy):
    choices = []
    for path in _files(os.path.join(data_root, 'SHP'), ('.shp',)):
        desc = arcpy.Describe(path)
        shape = getattr(desc, 'shapeType', None)
        if not shape:
            # ArcGIS 10.6 sometimes exposes a plain DescribeData proxy
            # for a valid tiny SHP on its first metadata read.
            shape = getattr(arcpy.Describe(path), 'shapeType', None)
        if not shape:
            import struct
            with open(path, 'rb') as fd:
                header = fd.read(36)
            if len(header) >= 36 and struct.unpack('>i', header[:4])[0] == 9994:
                shape = {5: 'Polygon', 15: 'Polygon', 25: 'Polygon'}.get(
                    struct.unpack('<i', header[32:36])[0])
        if str(shape or '').lower() != 'polygon':
            continue
        name = os.path.basename(path).upper()
        score = sum(1 for key in ('INDUSTRI', 'KEGIATAN', 'LOKASI',
                                  'PROJECT', 'PROYEK', 'IUP', 'WIUP',
                                  'USAHA', '_PL') if key in name)
        choices.append((score, path))
    if not choices:
        raise ValueError('PROJECT_ACTIVITY_POLYGON_REQUIRED')
    choices.sort(key=lambda row: (-row[0], row[1].lower()))
    if len(choices) > 1 and choices[0][0] == choices[1][0]:
        raise ValueError('PROJECT_ACTIVITY_POLYGON_AMBIGUOUS: ' +
                         ', '.join(x[1] for x in choices if x[0] == choices[0][0]))
    return choices[0][1]


def _bounds_in_sr(path, sr, arcpy):
    native = arcpy.Describe(path)
    own = native.spatialReference
    if own is None or own.name == 'Unknown' or sr.name == 'Unknown':
        raise ValueError('DATASET_CRS_UNKNOWN: ' + path)
    e = native.extent
    points = [(e.XMin, e.YMin), (e.XMin, e.YMax),
              (e.XMax, e.YMin), (e.XMax, e.YMax)]
    if own.name != sr.name:
        converted = []
        for x, y in points:
            geom = arcpy.PointGeometry(arcpy.Point(x, y), own).projectAs(sr)
            if geom is None or geom.firstPoint is None:
                raise ValueError('ON_THE_FLY_CRS_PROJECTION_FAILED: ' + path)
            converted.append((geom.firstPoint.X, geom.firstPoint.Y))
        points = converted
    return (min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points))


def _main_raster(data_root, polygon, arcpy):
    candidates = []
    all_rasters = _files(os.path.join(data_root, 'Basemap'), RASTERS)
    for path in all_rasters:
        if os.path.basename(path).upper().startswith('INSET_'):
            continue
        raster = arcpy.Raster(path)
        if int(raster.bandCount) < 3:
            continue
        sr = arcpy.Describe(path).spatialReference
        bounds = _bounds_in_sr(polygon, sr, arcpy)
        e = arcpy.Describe(path).extent
        eps = max(e.XMax-e.XMin, e.YMax-e.YMin) * 0.00001
        contains = (e.XMin-eps <= bounds[0] and e.YMin-eps <= bounds[1] and
                    e.XMax+eps >= bounds[2] and e.YMax+eps >= bounds[3])
        if contains:
            resolution = abs(float(raster.meanCellWidth) *
                             float(raster.meanCellHeight))
            candidates.append((resolution, path))
    if not candidates:
        raise ValueError('MAIN_RGB_BASEMAP_NOT_COVERING_ACTIVITY: ' +
                         ', '.join(os.path.basename(p) for p in all_rasters))
    candidates.sort(key=lambda row: (row[0], row[1].lower()))
    if len(candidates) > 1 and abs(candidates[0][0]-candidates[1][0]) <= max(1e-15, candidates[0][0]*1e-5):
        raise ValueError('MAIN_RGB_BASEMAP_RESOLUTION_AMBIGUOUS')
    return candidates[0][1]


def _inset_sources(data_root):
    sources = {}
    rasters = _files(os.path.join(data_root, 'Basemap'), RASTERS)
    for token in ('BUOL', 'SULTENG'):
        matched = [p for p in rasters if
                   os.path.basename(p).upper().startswith('INSET_' + token)]
        if len(matched) != 1:
            raise ValueError('INSET_BASEMAP_REQUIRED_UNIQUE_%s: %s' %
                             (token, ', '.join(matched)))
        sources[token] = matched[0]
    return sources


def _add(mxd, df, path, name, arcpy, position='TOP'):
    try:
        layer = arcpy.mapping.Layer(path)
    except Exception:
        tmp = arcpy.MakeRasterLayer_management(path, 'zagent_blank_layer')
        layer = tmp.getOutput(0)
    layer.name = name
    arcpy.mapping.AddLayer(df, layer, position)
    matches = [x for x in arcpy.mapping.ListLayers(mxd, '', df)
               if x.name == name]
    if len(matches) != 1:
        raise RuntimeError('CREATED_LAYER_NOT_UNIQUE: ' + name)
    matches[0].visible = True
    return matches[0]


def _set_text(mxd, title, project, scale, source, sr, insets, arcpy):
    rows = list(arcpy.mapping.ListLayoutElements(mxd, 'TEXT_ELEMENT'))
    if len(rows) != 9:
        raise ValueError('INTERNAL_SCAFFOLD_TEXT_SIGNATURE_CHANGED')
    rows[0].text = 'LOKASI KEGIATAN'
    for i, frame_name in ((1, 'INSET_BUOL'), (2, 'INSET_SULTENG')):
        df = [f for f in arcpy.mapping.ListDataFrames(mxd)
              if f.name == frame_name][0]
        rows[i].text = ('INSET PETA\nSKALA 1 : ' +
                        format(int(round(float(df.scale))), ',').replace(',', '.'))
    rows[3].text = ('Sumber Data dan Riwayat Peta:\n'
                    '1. SHP: %s\n2. Basemap: %s\n'
                    '3. Inset: %s; %s' %
                    (os.path.basename(project), os.path.basename(source),
                     os.path.basename(insets['BUOL']),
                     os.path.basename(insets['SULTENG'])))
    rows[4].text = title + '\nLOKASI KEGIATAN'
    rows[5].text = (': %s\n: %s\n: %s\n: %s' %
                    (sr.name.replace('_', ' '),
                     getattr(sr, 'projectionName', '') or '-',
                     getattr(sr, 'datumName', '') or
                     getattr(sr, 'GCSName', '') or '-',
                     getattr(sr, 'linearUnitName', '') or
                     getattr(sr, 'angularUnitName', '') or '-'))
    rows[6].text = 'Coordinate System\nProjection\nDatum\nUnits'
    rows[7].text = ('Skala 1 : %s\n( Untuk ukuran kertas A4 )' %
                    format(int(round(float(scale))), ',').replace(',', '.'))
    rows[8].text = 'PETA ADMINISTRASI'
    for i, item in enumerate(rows):
        minimum = 14.0 if i == 8 else 7.0
        if float(item.fontSize) < minimum:
            item.fontSize = minimum
        try:
            item.fontName = 'Arial'
        except Exception:
            pass


def bootstrap(working, data_root, main_name='Layers', rule_snapshot=None,
              source_mxd=None):
    """Replace only disposable 'working.mxd' if the user input is blank."""
    arcpy = engine._arcpy()
    original = engine.open_mxd(working)
    try:
        if not is_blank(original, arcpy, main_name):
            return {'used': False}
        crs = arcpy.mapping.ListDataFrames(original)[0].spatialReference
        if not crs or crs.name == 'Unknown':
            raise ValueError('BLANK_MXD_CRS_NOT_DEFINED')
        input_crs = crs.name
        input_wkt = crs.exportToString()
    finally:
        del original

    if not os.path.isfile(SEED):
        raise RuntimeError('BLANK_LAYOUT_SCAFFOLD_NOT_DEPLOYED')
    project = _project_polygon(data_root, arcpy)
    raster = _main_raster(data_root, project, arcpy)
    insets = _inset_sources(data_root)
    shutil.copy2(SEED, working)
    mxd = engine.open_mxd(working)
    try:
        dfs = dict((f.name, f) for f in arcpy.mapping.ListDataFrames(mxd))
        if set(dfs) != set([main_name, 'INSET_BUOL', 'INSET_SULTENG']):
            raise ValueError('INTERNAL_SCAFFOLD_FRAMES_INVALID')
        main = dfs[main_name]
        sr = arcpy.SpatialReference()
        sr.loadFromString(input_wkt)
        main.spatialReference = sr
        for token, name in (('BUOL', 'INSET_BUOL'),
                            ('SULTENG', 'INSET_SULTENG')):
            df = dfs[name]
            df.spatialReference = arcpy.Describe(insets[token]).spatialReference

        for legend in arcpy.mapping.ListLayoutElements(mxd, 'LEGEND_ELEMENT'):
            legend.autoAdd = True

        base = _add(mxd, main, raster, 'BASEMAP_RGB', arcpy, 'BOTTOM')
        area = _add(mxd, main, project, 'LOKASI KEGIATAN', arcpy, 'TOP')
        main.extent = area.getExtent(True)
        main.scale = float(main.scale) * 1.18
        for token, name in (('BUOL', 'INSET_BUOL'),
                            ('SULTENG', 'INSET_SULTENG')):
            df = dfs[name]
            layer = _add(mxd, df, insets[token],
                         'BASEMAP_INSET_' + token, arcpy)
            df.extent = layer.getExtent(True)
            df.scale = float(df.scale) * 1.04

        # Equal map-frame widths; do not change the inset raster proportions.
        for name, x in (('INSET_BUOL', 22.06), ('INSET_SULTENG', 25.65)):
            els = [e for e in arcpy.mapping.ListLayoutElements(
                   mxd, 'DATAFRAME_ELEMENT') if e.name == name]
            if len(els) != 1:
                raise ValueError('INSET_LAYOUT_FRAME_NOT_UNIQUE: ' + name)
            els[0].elementPositionX = x
            els[0].elementPositionY = 1.50
            els[0].elementWidth = 3.12
            els[0].elementHeight = 3.00

        basename = os.path.splitext(os.path.basename(source_mxd or data_root))[0]
        title = basename.upper().replace('PETA A4 ', '').replace(' - ADMINISTRASI', '')
        _set_text(mxd, title, project, main.scale, raster, sr, insets, arcpy)
        for legend in arcpy.mapping.ListLayoutElements(mxd, 'LEGEND_ELEMENT'):
            legend.title = 'LEGENDA'
            for item in list(legend.listLegendItemLayers()):
                if item.name != area.name:
                    legend.removeItem(item)
            if not legend.listLegendItemLayers():
                raise ValueError('BLANK_LEGEND_NO_ACTIVITY_ITEM')
        mxd.save()
        result = {'used': True, 'input_crs': input_crs,
                  'main_project_layer': project, 'main_basemap': raster,
                  'inset_basemaps': insets, 'construction': 'sanitized_internal_a4_scaffold',
                  'layers_generated': ['BASEMAP_RGB', 'LOKASI KEGIATAN',
                                       'BASEMAP_INSET_BUOL', 'BASEMAP_INSET_SULTENG']}
        return result
    finally:
        del mxd
