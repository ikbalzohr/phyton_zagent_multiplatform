# -*- coding: utf-8 -*-
"""ArcMap 10.6 / Python 2.7 headless print-ready vertical slice.

Never uses MapDocument('CURRENT'), never saves the input MXD. This module
reuses Stage2 layout, QA and export functions. A successful export is not
equivalent to independent visual-print acceptance.
"""
from __future__ import absolute_import, print_function
import hashlib
import os
import shutil
import uuid
from stage2 import engine


def _sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        while True:
            part = stream.read(1024 * 1024)
            if not part:
                break
            h.update(part)
    return h.hexdigest()


def _within(path, root):
    path = os.path.normcase(os.path.abspath(path))
    root = os.path.normcase(os.path.abspath(root))
    rel = os.path.relpath(path, root)
    return rel != os.pardir and not rel.startswith(os.pardir + os.sep)


def _local_dataset(data_root, source):
    """Match exact file basenames only. Never silently use an original path."""
    base = os.path.basename(source)
    extension = os.path.splitext(base)[1].lower()
    if extension == '.shp':
        candidate = os.path.join(data_root, 'SHP', base)
        kind = 'SHAPEFILE_WORKSPACE'
        dataset_name = os.path.splitext(base)[0]
    elif extension in ('.ecw', '.tif', '.tiff', '.img', '.sid'):
        candidate = os.path.join(data_root, 'Basemap', base)
        kind = 'RASTER_WORKSPACE'
        dataset_name = base
    else:
        return None
    if not _within(candidate, data_root):
        raise ValueError('DATASET_ESCAPES_ROOT')
    if not os.path.isfile(candidate):
        return None
    return (candidate, kind, dataset_name)


def _page_mm(mxd):
    w = float(mxd.pageSize.width)
    h = float(mxd.pageSize.height)
    # ArcMap pageSize is expressed in the document's native page units.
    # Determine unit only if a known A4 page fits both dimensions.
    for factor in (1.0, 10.0, 25.4):
        if abs(w * factor - 297.0) <= 1.6 and abs(h * factor - 210.0) <= 1.6:
            return {'width_mm': round(w * factor, 3),
                    'height_mm': round(h * factor, 3),
                    'native_width': w, 'native_height': h,
                    'mm_per_native_unit': factor, 'orientation': 'landscape'}
    raise ValueError('NOT_A4_LANDSCAPE: native_page=%s,%s' % (w, h))


def _normalize_template_layout(mxd):
    """Tidy source-template text and page border on the disposable MXD only."""
    arcpy = engine._arcpy()
    elements = list(arcpy.mapping.ListLayoutElements(mxd))
    changes = []
    keys = [e for e in elements if e.type == 'TEXT_ELEMENT'
            and 'Coordinate System' in (e.text or '')
            and 'Projection' in (e.text or '')]
    values = [e for e in elements if e.type == 'TEXT_ELEMENT'
              and ': WGS 1984 UTM Zone 51N' in (e.text or '')
              and ': Transverse' in (e.text or '')]
    if keys or values:
        if len(keys) != 1 or len(values) != 1:
            raise ValueError('CRS_COLUMN_AMBIGUOUS')
        key, value = keys[0], values[0]
        minimum_x = float(key.elementPositionX) + float(key.elementWidth) + 0.35
        if float(value.elementPositionX) < minimum_x:
            if minimum_x + float(value.elementWidth) > float(mxd.pageSize.width) - 0.3:
                raise ValueError('CRS_COLUMN_NO_ROOM')
            value.elementPositionX = minimum_x
            changes.append('CRS_VALUE_COLUMN_SEPARATED')
    for element in elements:
        if element.type == 'TEXT_ELEMENT' and 'Transverse Mecrator' in (element.text or ''):
            element.text = element.text.replace('Transverse Mecrator', 'Transverse Mercator')
            changes.append('CRS_PROJECTION_TYPO_CORRECTED')
    width = float(mxd.pageSize.width)
    height = float(mxd.pageSize.height)
    outer = [e for e in elements if e.type == 'GRAPHIC_ELEMENT'
             and float(e.elementWidth) > width * 0.96
             and float(e.elementHeight) > height * 0.96]
    if len(outer) > 1:
        raise ValueError('PAGE_BORDER_NOT_UNIQUE')
    if outer:
        e = outer[0]
        if (float(e.elementPositionX) < 0.49 or
                float(e.elementPositionY) < 0.49 or
                width-float(e.elementPositionX)-float(e.elementWidth) < 0.49 or
                height-float(e.elementPositionY)-float(e.elementHeight) < 0.49):
            e.elementPositionX = 0.5
            e.elementPositionY = 0.5
            e.elementWidth = width - 1.0
            e.elementHeight = height - 1.0
            changes.append('PAGE_BORDER_5MM_SAFE_MARGIN')
    # Graticule labels extend beyond the main data-frame neatline.
    # Preserve actual scale while reserving space for printed edge labels.
    main_boxes = [e for e in elements if e.type == 'DATAFRAME_ELEMENT'
                  and e.name == 'Layers'
                  and float(e.elementWidth) > width * 0.5
                  and float(e.elementHeight) > height * 0.5]
    if len(main_boxes) > 1:
        raise ValueError('MAIN_LAYOUT_FRAME_NOT_UNIQUE')
    if main_boxes:
        box = main_boxes[0]
        right = float(box.elementPositionX) + float(box.elementWidth)
        bottom = float(box.elementPositionY)
        top = bottom + float(box.elementHeight)
        px = 10.0 / _page_mm(mxd)['mm_per_native_unit']
        new_x = max(float(box.elementPositionX), 1.55 * px)
        new_y = max(bottom, 1.25 * px)
        new_top = min(top, height - 1.45 * px)
        if new_top - new_y < 17.0 * px or right - new_x < 17.5 * px:
            raise ValueError('MAIN_FRAME_PRINT_CLEARANCE_NO_ROOM')
        if (new_x != float(box.elementPositionX) or
                new_y != bottom or new_top != top):
            box.elementPositionX = new_x
            box.elementPositionY = new_y
            box.elementWidth = right - new_x
            box.elementHeight = new_top - new_y
            changes.append('MAIN_FRAME_GRID_LABEL_CLEARANCE')
    return changes


def _layout_qa(mxd, main_name, expected_scale, expected_crs, minimum_font_pt=6.0):
    arcpy = engine._arcpy()
    frames = list(arcpy.mapping.ListDataFrames(mxd))
    main = [d for d in frames if d.name == main_name]
    if len(main) != 1:
        raise ValueError('MAIN_FRAME_NOT_UNIQUE')
    main = main[0]
    if len(frames) < 3:
        raise ValueError('TWO_INSET_FRAMES_REQUIRED')
    if abs(float(main.scale) - float(expected_scale)) > 0.01:
        raise ValueError('SCALE_MISMATCH')
    if expected_crs and main.spatialReference.name != expected_crs:
        raise ValueError('CRS_MISMATCH')
    page = _page_mm(mxd)
    width = page['native_width']
    height = page['native_height']
    elements = list(arcpy.mapping.ListLayoutElements(mxd))
    outside = []
    low_font = []
    texts = []
    for index, element in enumerate(elements):
        x = float(element.elementPositionX)
        y = float(element.elementPositionY)
        w = float(element.elementWidth)
        h = float(element.elementHeight)
        if x < -0.01 or y < -0.01 or x+w > width+0.01 or y+h > height+0.01:
            outside.append({'index': index, 'name': element.name})
        if element.type == 'TEXT_ELEMENT':
            txt = element.text or ''
            texts.append(txt)
            if float(element.fontSize) < minimum_font_pt:
                low_font.append({'index': index, 'font_pt': float(element.fontSize)})
    if outside:
        raise ValueError('ELEMENTS_OUTSIDE_PAGE: ' + repr(outside))
    if low_font:
        raise ValueError('FONT_TOO_SMALL: ' + repr(low_font))
    keys = [e for e in elements if e.type == 'TEXT_ELEMENT'
            and 'Coordinate System' in (e.text or '') and 'Projection' in (e.text or '')]
    values = [e for e in elements if e.type == 'TEXT_ELEMENT'
              and ': WGS 1984 UTM Zone 51N' in (e.text or '')]
    if keys or values:
        if len(keys) != 1 or len(values) != 1:
            raise ValueError('CRS_COLUMN_AMBIGUOUS')
        if (float(values[0].elementPositionX) - float(keys[0].elementPositionX)
                - float(keys[0].elementWidth) < 0.24):
            raise ValueError('CRS_TEXT_COLUMNS_OVERLAP')
    for e in elements:
        if (e.type == 'GRAPHIC_ELEMENT' and float(e.elementWidth) > width * 0.9
                and float(e.elementHeight) > height * 0.9):
            if min(float(e.elementPositionX), float(e.elementPositionY),
                   width-float(e.elementPositionX)-float(e.elementWidth),
                   height-float(e.elementPositionY)-float(e.elementHeight)) < 0.49:
                raise ValueError('PRINTER_SAFE_MARGIN_NOT_MET')
    text_blob = '\n'.join(texts).upper()
    for required in ('PETA ADMINISTRASI', 'PT BUOL AGRI LESTARI',
                     'SUMBER DATA', 'WGS 1984 UTM'):
        if required not in text_blob:
            raise ValueError('REQUIRED_TEXT_MISSING: ' + required)
    named = set(e.name for e in elements)
    mapped_frames = set(e.name for e in elements if e.type == 'DATAFRAME_ELEMENT')
    if not set(d.name for d in frames).issubset(mapped_frames):
        raise ValueError('INSET_DATAFRAME_ELEMENT_MISSING')
    for required in ('Legend', 'North Arrow', 'Double Alternating Scale Bar'):
        if required not in named:
            raise ValueError('SURROUND_MISSING: ' + required)
    legend_items = []
    for element in elements:
        if element.type == 'LEGEND_ELEMENT' and element.name == 'Legend':
            if element.isOverflowing:
                raise ValueError('LEGEND_OVERFLOW')
            legend_items = [item.name for item in element.listLegendItemLayers()]
    visible_main = set(layer.name for layer in arcpy.mapping.ListLayers(mxd, '', main)
                       if not layer.isGroupLayer and layer.visible)
    if not legend_items or not set(legend_items).issubset(visible_main):
        raise ValueError('LEGEND_OUT_OF_SYNC')
    broken = arcpy.mapping.ListBrokenDataSources(mxd)
    if broken:
        raise ValueError('BROKEN_DATA_SOURCE: ' + repr([b.name for b in broken]))
    return {'page': page, 'main_frame': main_name, 'scale': float(main.scale),
            'crs': main.spatialReference.name,
            'frames': [{'name': d.name, 'scale': float(d.scale)} for d in frames],
            'element_count': len(elements), 'legend_items': legend_items,
            'outside_page': outside, 'small_fonts': low_font,
            'broken_sources': [], 'grid': 'NOT_INDEPENDENTLY_VERIFIED',
            'label_collision': 'NOT_INDEPENDENTLY_VERIFIED'}


def build(template_mxd, data_root, output_root, scale=70000,
          dpi=400, main_frame='Layers',
          expected_crs='WGS_1984_UTM_Zone_51N'):
    """Produce isolated working MXD + PDF + PNG and a truthful QA report."""
    if not all(isinstance(p, engine.string_types) and os.path.isabs(p)
               for p in (template_mxd, data_root, output_root)):
        raise ValueError('ABSOLUTE_DISK_PATHS_REQUIRED')
    if template_mxd.upper() == 'CURRENT' or not template_mxd.lower().endswith('.mxd'):
        raise ValueError('DISK_MXD_REQUIRED')
    if not os.path.isfile(template_mxd) or not os.path.isdir(data_root):
        raise ValueError('INPUTS_NOT_FOUND')
    if int(dpi) < 150 or int(dpi) > 600:
        raise ValueError('DPI_OUT_OF_RANGE')
    if not 1000 <= float(scale) <= 100000000:
        raise ValueError('SCALE_OUT_OF_RANGE')

    before = _sha256(template_mxd)
    job_id = 'print_ready_m1_' + uuid.uuid4().hex[:12]
    job_dir = os.path.join(output_root, job_id)
    if _within(template_mxd, job_dir) or _within(job_dir, os.path.dirname(template_mxd)) and ('Contoh Layout' in job_dir):
        raise ValueError('OUTPUT_OVERLAPS_PROTECTED_INPUT')
    if not os.path.isdir(output_root):
        os.makedirs(output_root)
    os.mkdir(job_dir)
    working = os.path.join(job_dir, 'working.mxd')
    shutil.copy2(template_mxd, working)
    arcpy = engine._arcpy()
    replaced = []
    removed_hidden = []
    mxd = engine.open_mxd(working)
    try:
        for frame in arcpy.mapping.ListDataFrames(mxd):
            for layer in list(arcpy.mapping.ListLayers(mxd, '', frame)):
                if layer.isGroupLayer:
                    continue
                if not layer.supports('DATASOURCE'):
                    if layer.visible:
                        raise ValueError('VISIBLE_LAYER_WITHOUT_DATASOURCE: ' + layer.name)
                    continue
                source = layer.dataSource
                local = _local_dataset(data_root, source)
                if local is None:
                    if layer.visible:
                        raise ValueError('VISIBLE_SOURCE_NOT_IN_TEST_DATA: ' + source)
                    arcpy.mapping.RemoveLayer(frame, layer)
                    removed_hidden.append({'frame': frame.name, 'layer': layer.name,
                                           'previous_source': source})
                    continue
                target, workspace_type, dataset_name = local
                layer.replaceDataSource(os.path.dirname(target), workspace_type,
                                        dataset_name, True)
                actual = layer.dataSource
                if layer.isBroken or os.path.normcase(os.path.abspath(actual)) != os.path.normcase(os.path.abspath(target)):
                    raise ValueError('SOURCE_REBIND_FAILED: %s -> %s (actual=%s)' %
                                     (source, target, actual))
                replaced.append({'frame': frame.name, 'layer': layer.name,
                                 'source': target})
        main = [d for d in arcpy.mapping.ListDataFrames(mxd) if d.name == main_frame]
        if len(main) != 1:
            raise ValueError('MAIN_FRAME_NOT_UNIQUE')
        main[0].scale = float(scale)
        layout_adjustments = _normalize_template_layout(mxd)
        main[0].scale = float(scale)  # Resizing a frame can change scale.
        mxd.save()  # Working copy only.
        qa = _layout_qa(mxd, main_frame, scale, expected_crs)
        exported = engine.export_map(
            mxd, job_dir, 'PETA A4 BUOL AGRI LESTARI - ADMINISTRASI',
            {'resolution': int(dpi), 'formats': ['PDF', 'PNG']},
            allow_custom_export=True)
    finally:
        del mxd
    if _sha256(template_mxd) != before:
        raise RuntimeError('ORIGINAL_MXD_HASH_CHANGED')
    files = {}
    for kind, path in exported.items():
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise ValueError('EXPORT_MISSING: ' + kind)
        files[kind] = {'path': path, 'size_bytes': os.path.getsize(path),
                       'sha256': _sha256(path)}
    report = {'ok': True, 'print_ready_accepted': False, 'job_id': job_id,
              'execution_mode': 'headless', 'working_mxd': working,
              'original_mxd': template_mxd, 'original_sha256': before,
              'original_unchanged': True, 'layout_adjustments': layout_adjustments,
              'source_bindings': replaced,
              'removed_unmatched_hidden_layers': removed_hidden,
              'qa': qa, 'exports': files, 'dpi_requested': int(dpi),
              'pending': ['PDF page-box and raster dimensions independent validation',
                          'visual proof of grid, labels and typography']}
    engine.write_json(os.path.join(job_dir, 'print_ready_report.json'), report)
    return report
