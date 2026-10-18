# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import sys
import json
import time
import shutil
import traceback

STAGE3_VERSION = "3.0.0"

STAGE3_ACTIONS = [
    "stage3_health",
    "stage3_blank_init",
    "stage3_ensure_dataframe",
    "stage3_set_page_a4",
    "stage3_create_text",
    "stage3_create_neatline",
    "stage3_create_legend",
    "stage3_create_north_arrow",
    "stage3_create_scale_bar",
    "stage3_create_featureclass",
    "stage3_create_xy_featureclass",
    "stage3_create_geometry_features",
    "stage3_add_dataset_auto",
    "stage3_ingest_folder",
    "stage3_set_extent_auto",
    "stage3_build_blank_a4",
    "stage3_build_no_data_a4",
    "stage3_save_checkpoint",
    "stage3_restore_checkpoint",
    "stage3_export_current",
]

_ORIGINAL_PROCESS_COMMAND = None


def _arcpy():
    import arcpy
    return arcpy


def _mxd():
    arcpy = _arcpy()
    return arcpy.mapping.MapDocument("CURRENT")


def _df(mxd, name=""):
    arcpy = _arcpy()
    dfs = arcpy.mapping.ListDataFrames(mxd, name or "*")
    if not dfs:
        raise RuntimeError("No data frame exists in CURRENT MXD")
    return dfs[0]


def _ok(action, **kw):
    d = {"ok": True, "action": action, "stage3_version": STAGE3_VERSION}
    d.update(kw)
    return d


def _fail(action, exc):
    return {
        "ok": False,
        "action": action,
        "stage3_version": STAGE3_VERSION,
        "error": repr(exc),
        "traceback": traceback.format_exc(),
    }


def _cmd_payload(command):
    p = dict(command or {})
    p.pop("action", None)
    p.pop("request_id", None)
    return p


def _page_size(mxd):
    ps = getattr(mxd, "pageSize", None)
    if ps is None:
        return (11.69, 8.27)
    for attrs in (("width", "height"), ("Width", "Height")):
        try:
            return (float(getattr(ps, attrs[0])), float(getattr(ps, attrs[1])))
        except Exception:
            pass
    try:
        return (float(ps[0]), float(ps[1]))
    except Exception:
        return (11.69, 8.27)


def _verify_current_process(app):
    import ctypes
    pid = ctypes.c_ulong()
    hwnd = int(app.hWnd)
    ctypes.windll.user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
    if pid.value != os.getpid():
        raise RuntimeError("WRONG_ARCMAP_INSTANCE: COM target is not the CURRENT-MXD process")
    return app

def _active_app():
    errors = []

    # ArcObjects AppRef is the supported singleton for code running inside
    # an ArcGIS Desktop application process. Using GetActiveObject with
    # "esriArcMap.Application" fails on ArcMap 10.6.1 because that ProgID
    # is not registered as an automation class.
    try:
        import win32com.client
        return _verify_current_process(
            win32com.client.Dispatch("esriFramework.AppRef")
        ), "win32com:esriFramework.AppRef"
    except Exception as exc:
        errors.append("win32com AppRef: %r" % exc)

    try:
        import comtypes.client
        return _verify_current_process(
            comtypes.client.CreateObject("esriFramework.AppRef", dynamic=True)
        ), "comtypes:esriFramework.AppRef"
    except Exception as exc:
        errors.append("comtypes AppRef: %r" % exc)

    # Historical compatibility fallback only.
    try:
        import win32com.client
        return _verify_current_process(
            win32com.client.GetActiveObject("esriArcMap.Application")
        ), "win32com:GetActiveObject"
    except Exception as exc:
        errors.append("win32com GetActiveObject: %r" % exc)

    try:
        import comtypes.client
        return _verify_current_process(
            comtypes.client.GetActiveObject("esriArcMap.Application")
        ), "comtypes:GetActiveObject"
    except Exception as exc:
        errors.append("comtypes GetActiveObject: %r" % exc)

    raise RuntimeError(
        "ArcObjects automation backend unavailable: " + " | ".join(errors)
    )


_TYPED_PROGID_MODULES = {}


def _typed_module_for_progid(progid):
    prefix = str(progid or "").split(".", 1)[0]
    module_name = {
        "esriCarto": "esriCarto.olb",
        "esriDisplay": "esriDisplay.olb",
        "esriGeometry": "esriGeometry.olb",
        "esriFramework": "esriFramework.olb",
        "esriArcMapUI": "esriArcMapUI.olb",
    }.get(prefix)
    if not module_name:
        return None, None
    cached = _TYPED_PROGID_MODULES.get(prefix)
    if cached is not None:
        return cached, str(progid).split(".", 1)[1]
    import comtypes.client
    info = _arcpy().GetInstallInfo() or {}
    install_dir = info.get("InstallDir") or info.get("InstallDir64") or ""
    if not install_dir:
        raise RuntimeError("ArcGIS InstallDir is unavailable.")
    module = comtypes.client.GetModule(
        os.path.join(install_dir, "com", module_name)
    )
    _TYPED_PROGID_MODULES[prefix] = module
    return module, str(progid).split(".", 1)[1]


def _preferred_typed_interface(progid, module):
    class_name = str(progid or "").split(".", 1)[-1]
    names = {
        "TextElement": ["ITextElement"],
        "RectangleElement": ["IFillShapeElement", "IRectangleElement"],
        "MapSurroundFrame": ["IMapSurroundFrame"],
        "Legend": ["ILegend"],
        "MarkerNorthArrow": ["IMarkerNorthArrow", "INorthArrow"],
        "NorthArrow": ["INorthArrow"],
        "AlternatingScaleBar": ["IScaleBar"],
        "ScaleBar": ["IScaleBar"],
        "Map": ["IMap"],
        "Graticule": ["IMapGrid", "IGraticule"],
        "DMSGridLabel": ["IGridLabel"],
        "SimpleRenderer": ["ISimpleRenderer"],
        "RgbColor": ["IRgbColor", "IColor"],
        "SimpleLineSymbol": ["ISimpleLineSymbol", "ILineSymbol"],
        "SimpleFillSymbol": ["ISimpleFillSymbol", "IFillSymbol"],
        "SimpleMarkerSymbol": ["ISimpleMarkerSymbol", "IMarkerSymbol"],
        "TextSymbol": ["ITextSymbol"],
        "TextSymbolClass": ["ITextSymbol"],
        "Point": ["IPoint"],
        "Envelope": ["IEnvelope"],
    }.get(class_name, [])
    for name in names:
        iface = getattr(module, name, None)
        if iface is not None:
            return iface
    return None


def _create_com(progids):
    errors = []
    for progid in progids:
        try:
            import comtypes.client
            module, class_name = _typed_module_for_progid(progid)
            coclass = getattr(module, class_name) if module is not None else None
            if coclass is not None:
                iface = _preferred_typed_interface(progid, module)
                if iface is not None:
                    return (
                        comtypes.client.CreateObject(coclass, interface=iface),
                        "comtypes-typed:%s:%s" % (progid, getattr(iface, "__name__", "iface")),
                    )
                return (
                    comtypes.client.CreateObject(coclass),
                    "comtypes-typed:%s" % progid,
                )
        except Exception as exc:
            errors.append("typed %s: %r" % (progid, exc))
        try:
            import win32com.client
            return win32com.client.Dispatch(progid), "win32com:%s" % progid
        except Exception as exc:
            errors.append("win32com %s: %r" % (progid, exc))
        try:
            import comtypes.client
            return comtypes.client.CreateObject(progid, dynamic=True), "comtypes:%s" % progid
        except Exception as exc:
            errors.append("comtypes %s: %r" % (progid, exc))
    raise RuntimeError("Could not create ArcObjects COM object. " + " | ".join(errors[-9:]))


_IID_IMXDOCUMENT = "{0522A5F1-487C-11D0-98BD-00805F7CED21}"
_IID_IPAGELAYOUT = "{DD94D76A-836D-11D0-87EC-080009EC732A}"
_IID_IPAGE = "{2AB4981F-9406-11D0-87EF-080009EC732A}"

_TYPED_ARCOBJECTS = None


def _typed_arcobjects_modules():
    global _TYPED_ARCOBJECTS
    if _TYPED_ARCOBJECTS is not None:
        return _TYPED_ARCOBJECTS

    import comtypes.client

    info = _arcpy().GetInstallInfo() or {}
    install_dir = info.get("InstallDir") or info.get("InstallDir64") or ""
    if not install_dir:
        raise RuntimeError("ArcGIS InstallDir is unavailable.")

    com_dir = os.path.join(install_dir, "com")
    paths = {
        "framework": os.path.join(com_dir, "esriFramework.olb"),
        "arcmapui": os.path.join(com_dir, "esriArcMapUI.olb"),
        "carto": os.path.join(com_dir, "esriCarto.olb"),
    }
    missing = [p for p in paths.values() if not os.path.isfile(p)]
    if missing:
        raise RuntimeError(
            "ArcObjects type libraries are missing: " + ", ".join(missing)
        )

    framework = comtypes.client.GetModule(paths["framework"])
    arcmapui = comtypes.client.GetModule(paths["arcmapui"])
    carto = comtypes.client.GetModule(paths["carto"])
    _TYPED_ARCOBJECTS = (
        comtypes.client, framework, arcmapui, carto
    )
    return _TYPED_ARCOBJECTS


def _layout_container():
    errors = []

    # Layout elements must be manipulated while the active view is PAGE_LAYOUT.
    # ArcObjects samples cast IMxDocument.ActiveView to IGraphicsContainer;
    # leaving ArcMap in data view can make AddElement fail with E_INVALIDARG.
    try:
        current = _mxd()
        if str(getattr(current, "activeView", "") or "").upper() != "PAGE_LAYOUT":
            current.activeView = "PAGE_LAYOUT"
            try:
                _arcpy().RefreshActiveView()
            except Exception:
                pass
    except Exception as exc:
        errors.append("activate PAGE_LAYOUT: %r" % exc)

    # Preferred ArcMap 10.6 path: typed comtypes interfaces generated from the
    # installed ArcObjects type libraries. IApplication.Document exposes only
    # IDocument by default; PageLayout belongs to IMxDocument.
    try:
        client, framework, arcmapui, carto = _typed_arcobjects_modules()
        app = client.CreateObject(
            "esriFramework.AppRef",
            interface=framework.IApplication
        )
        app = _verify_current_process(app)
        doc = app.Document.QueryInterface(arcmapui.IMxDocument)
        pl = doc.PageLayout.QueryInterface(carto.IPageLayout)
        return (
            app,
            doc,
            pl,
            "comtypes:esriFramework.AppRef+IApplication+IMxDocument+IPageLayout",
        )
    except Exception as exc:
        errors.append("typed comtypes layout: %r" % exc)

    # Compatibility fallback for installations where the dynamic automation
    # wrapper already exposes the IMxDocument surface.
    try:
        app, backend = _active_app()
        doc = app.Document
        pl = doc.PageLayout
        return app, doc, pl, backend + "+dynamic-PageLayout"
    except Exception as exc:
        errors.append("dynamic layout fallback: %r" % exc)

    raise RuntimeError(
        "ArcObjects PageLayout backend unavailable: " + " | ".join(errors)
    )


def _make_point(x, y):
    pt, backend = _create_com(["esriGeometry.Point"])
    try:
        pt.PutCoords(float(x), float(y))
    except Exception:
        pt.X = float(x)
        pt.Y = float(y)
    return pt, backend


def _make_envelope(xmin, ymin, xmax, ymax):
    env, backend = _create_com(["esriGeometry.Envelope"])
    try:
        env.PutCoords(float(xmin), float(ymin), float(xmax), float(ymax))
    except Exception:
        env.XMin = float(xmin)
        env.YMin = float(ymin)
        env.XMax = float(xmax)
        env.YMax = float(ymax)
    return env, backend


def _add_layout_element(element):
    app, doc, pl, backend = _layout_container()
    errors = []

    # ArcObjects layout coclasses often return their specialized default
    # interface (ITextElement, IRectangleElement, IMapSurroundFrame, ...).
    # IGraphicsContainer.AddElement requires IElement explicitly.
    element_for_add = element
    carto = None
    ielement_status = "UNKNOWN"
    try:
        client, framework, arcmapui, carto = _typed_arcobjects_modules()
        try:
            element_for_add = element.QueryInterface(carto.IElement)
            ielement_status = "PASS"
        except Exception as exc:
            ielement_status = "FAIL:%r" % exc
            element_for_add = element
    except Exception as exc:
        errors.append("typed modules: %r" % exc)

    # Preferred path: PageLayout coclass -> IGraphicsContainer.
    if carto is not None:
        for candidate_name, candidate in (
            ("doc.ActiveView", getattr(doc, "ActiveView", None)),
            ("doc.PageLayout", getattr(doc, "PageLayout", None)),
            ("pl", pl),
        ):
            if candidate is None:
                continue
            try:
                gc = candidate.QueryInterface(carto.IGraphicsContainer)
            except Exception as exc:
                errors.append("%s QI IGraphicsContainer: %r" % (candidate_name, exc))
                continue
            added = False
            for zorder in (0, -1, 1):
                try:
                    gc.AddElement(element_for_add, zorder)
                    return backend + ":%s:IGraphicsContainer:z=%s" % (candidate_name, zorder)
                except Exception as exc:
                    errors.append("%s AddElement(z=%s): %r" % (candidate_name, zorder, exc))

    # Compatibility fallback for dynamic wrappers that expose AddElement.
    for obj in (
        getattr(pl, "GraphicsContainer", None),
        getattr(doc, "PageLayout", None),
        pl,
    ):
        if obj is None:
            continue
        try:
            obj.AddElement(element_for_add, 0)
            return backend + ":dynamic-AddElement"
        except Exception as exc:
            errors.append("dynamic AddElement: %r" % exc)

    errors.append("IElement_QI=%s" % ielement_status)
    try:
        errors.append("element_type=%s" % type(element_for_add))
        errors.append("element_iid=%s" % getattr(element_for_add, "_iid_", None))
        if carto is not None:
            errors.append("expected_iid=%s" % getattr(carto.IElement, "_iid_", None))
            sigs = []
            for method in getattr(carto.IGraphicsContainer, "_methods_", []):
                if getattr(method, "name", "") == "AddElement":
                    sigs.append(repr(method))
            errors.append("AddElement_sig=%s" % sigs)
    except Exception as exc:
        errors.append("interface_diag:%r" % exc)
    try:
        g = getattr(element_for_add, "Geometry", None)
        errors.append("element_geometry_present=%s" % bool(g is not None))
    except Exception as exc:
        errors.append("element_geometry_read: %r" % exc)
    raise RuntimeError("Could not add layout element: " + " | ".join(errors[-12:]))


def _set_element_name(element, name):
    if not name:
        return False
    targets = [element]
    try:
        client, framework, arcmapui, carto = _typed_arcobjects_modules()
        for iface_name in ("IElementProperties3", "IElementProperties2", "IElementProperties"):
            iface = getattr(carto, iface_name, None)
            if iface is None:
                continue
            try:
                targets.insert(0, element.QueryInterface(iface))
                break
            except Exception:
                pass
    except Exception:
        pass
    for target in targets:
        for attr in ("Name", "name"):
            try:
                setattr(target, attr, str(name))
                return True
            except Exception:
                pass
    return False


def _set_element_geometry(element, geom):
    targets = [element]
    geom_value = geom
    try:
        client, framework, arcmapui, carto = _typed_arcobjects_modules()
        targets.insert(0, element.QueryInterface(carto.IElement))
    except Exception:
        pass
    try:
        geometry_mod, _ = _typed_module_for_progid("esriGeometry.Point")
        if geometry_mod is not None:
            geom_value = geom.QueryInterface(geometry_mod.IGeometry)
    except Exception:
        geom_value = geom
    for target in targets:
        for attr in ("Geometry", "geometry"):
            try:
                setattr(target, attr, geom_value)
                return True
            except Exception:
                pass
    return False


def _set_arcpy_layout_name(element_type, name, x=None, y=None, text=None):
    if not name:
        return False
    arcpy = _arcpy()
    mxd = _mxd()
    candidates = []
    try:
        candidates = arcpy.mapping.ListLayoutElements(mxd, element_type)
    except Exception:
        return False

    ranked = []
    for elem in candidates:
        score = 0.0
        try:
            current = str(getattr(elem, "name", "") or "")
            if current == name:
                return True
        except Exception:
            pass
        if text is not None:
            try:
                if str(getattr(elem, "text", "") or "") == str(text):
                    score += 1000.0
            except Exception:
                pass
        if x is not None and y is not None:
            try:
                dx = abs(float(getattr(elem, "elementPositionX")) - float(x))
                dy = abs(float(getattr(elem, "elementPositionY")) - float(y))
                score += max(0.0, 100.0 - (dx + dy) * 100.0)
            except Exception:
                pass
        ranked.append((score, elem))

    if not ranked:
        return False
    ranked.sort(key=lambda item: item[0], reverse=True)
    elem = ranked[0][1]
    for attr in ("name", "elementName"):
        try:
            setattr(elem, attr, str(name))
            try:
                if str(getattr(elem, attr) or "") == str(name):
                    return True
            except Exception:
                return True
        except Exception:
            pass
    return False


def _find_layout(name):
    arcpy = _arcpy()
    mxd = _mxd()
    for typ in ("TEXT_ELEMENT", "GRAPHIC_ELEMENT", "LEGEND_ELEMENT", "MAPSURROUND_ELEMENT"):
        try:
            els = arcpy.mapping.ListLayoutElements(mxd, typ, name)
            if els:
                return els[0]
        except Exception:
            pass
        # Some ArcObjects-created elements expose an empty ArcPy name even
        # though their IElementProperties.Name was set. Search all elements as
        # a compatibility fallback.
        try:
            for elem in arcpy.mapping.ListLayoutElements(mxd, typ):
                for attr in ("name", "elementName"):
                    try:
                        if str(getattr(elem, attr) or "") == str(name):
                            return elem
                    except Exception:
                        pass
        except Exception:
            pass
    return None


def _create_text_impl(text, name, x_frac, y_frac, font_size, bold, anchor):
    arcpy = _arcpy()
    mxd = _mxd()
    existing = _find_layout(name)
    w, h = _page_size(mxd)
    x, y = w * float(x_frac), h * float(y_frac)
    if existing is not None:
        existing.text = text
        existing.elementPositionX = x
        existing.elementPositionY = y
        try:
            existing.fontSize = float(font_size)
        except Exception:
            pass
        return {"created": False, "updated": True, "backend": "arcpy.mapping", "name": name}

    elem, b1 = _create_com(["esriCarto.TextElement"])
    sym, b2 = _create_com(["esriDisplay.TextSymbol", "esriDisplay.TextSymbolClass"])
    try:
        sym.Size = float(font_size)
    except Exception:
        pass
    try:
        sym.Font.Bold = bool(bold)
    except Exception:
        pass
    try:
        elem.Symbol = sym
    except Exception:
        try:
            elem.TextSymbol = sym
        except Exception:
            pass
    elem.Text = text
    _set_element_name(elem, name)
    pt, _ = _make_point(x, y)
    if not _set_element_geometry(elem, pt):
        raise RuntimeError("Could not assign Point geometry to IElement")
    backend = _add_layout_element(elem)
    named = _set_arcpy_layout_name(
        "TEXT_ELEMENT", name, x=x, y=y, text=text
    )
    try:
        arcpy.RefreshActiveView()
    except Exception:
        pass
    return {
        "created": True,
        "backend": backend,
        "name": name,
        "x": x,
        "y": y,
        "name_persisted": bool(named),
    }


def _create_neatline_impl(name, margin_frac, line_width):
    mxd = _mxd()
    w, h = _page_size(mxd)
    m = min(w, h) * float(margin_frac)
    elem, _ = _create_com(["esriCarto.RectangleElement"])
    _set_element_name(elem, name)
    env, _ = _make_envelope(m, m, w - m, h - m)
    if not _set_element_geometry(elem, env):
        raise RuntimeError("Could not assign Envelope geometry to IElement")
    backend = _add_layout_element(elem)
    named = _set_arcpy_layout_name("GRAPHIC_ELEMENT", name)
    return {
        "created": True,
        "backend": backend,
        "name": name,
        "name_persisted": bool(named),
    }


def _create_surround(kind, name, x_frac, y_frac, width_frac, height_frac, title="", units=""):
    mxd = _mxd()
    w, h = _page_size(mxd)
    xmin = w * float(x_frac)
    ymin = h * float(y_frac)
    xmax = xmin + w * float(width_frac)
    ymax = ymin + h * float(height_frac)
    app, doc, pl, backend = _layout_container()
    df = _df(mxd)
    progids = {
        "legend": ["esriCarto.Legend"],
        "north_arrow": ["esriCarto.MarkerNorthArrow", "esriCarto.NorthArrow"],
        "scale_bar": ["esriCarto.AlternatingScaleBar", "esriCarto.ScaleBar"],
    }[kind]
    surround, sb = _create_com(progids)
    try:
        surround.Name = name
    except Exception:
        pass
    if title and kind == "legend":
        try:
            surround.Title = title
        except Exception:
            pass
    if units and kind == "scale_bar":
        for attr in ("UnitLabel", "Units"):
            try:
                setattr(surround, attr, units)
            except Exception:
                pass

    frame, fb = _create_com(["esriCarto.MapSurroundFrame"])
    try:
        frame.MapSurround = surround
    except Exception:
        pass
    try:
        # Late-binding may expose MapFrame through active view focus map.
        frame.MapFrame = pl.FindFrame(df.name)
    except Exception:
        pass
    _set_element_name(frame, name)
    env, _ = _make_envelope(xmin, ymin, xmax, ymax)
    _set_element_geometry(frame, env)
    used = _add_layout_element(frame)
    element_type = "LEGEND_ELEMENT" if kind == "legend" else "MAPSURROUND_ELEMENT"
    named = _set_arcpy_layout_name(element_type, name)
    return {
        "created": True,
        "backend": used,
        "name": name,
        "kind": kind,
        "name_persisted": bool(named),
    }


def _spatial_ref(value):
    arcpy = _arcpy()
    if not value:
        return None
    s = str(value).strip()
    if s.upper().startswith("EPSG:"):
        return arcpy.SpatialReference(int(s.split(":", 1)[1]))
    if s.isdigit():
        return arcpy.SpatialReference(int(s))
    if os.path.exists(s):
        sr = arcpy.SpatialReference()
        sr.loadFromString(open(s, "r").read())
        return sr
    try:
        return arcpy.SpatialReference(s)
    except Exception:
        return None


def _discover(data_root, recursive=True, max_items=500):
    arcpy = _arcpy()
    out = []
    root = os.path.abspath(data_root)
    if not os.path.isdir(root):
        return out
    raster_ext = set([".tif", ".tiff", ".img", ".jpg", ".jpeg", ".png", ".bmp", ".bil", ".sid"])
    layer_ext = set([".shp", ".lyr"])
    for current, dirs, files in os.walk(root):
        for fn in files:
            p = os.path.join(current, fn)
            ext = os.path.splitext(fn)[1].lower()
            if ext in raster_ext:
                out.append({"path": p, "type": "raster"})
            elif ext in layer_ext:
                out.append({"path": p, "type": "layer"})
            if len(out) >= int(max_items):
                return out
        for d in list(dirs):
            if d.lower().endswith(".gdb"):
                gdb = os.path.join(current, d)
                old_ws = arcpy.env.workspace
                try:
                    arcpy.env.workspace = gdb
                    for fc in (arcpy.ListFeatureClasses() or []):
                        out.append({"path": os.path.join(gdb, fc), "type": "featureclass"})
                        if len(out) >= int(max_items):
                            return out
                    for ds in (arcpy.ListDatasets(feature_type="feature") or []):
                        for fc in (arcpy.ListFeatureClasses(feature_dataset=ds) or []):
                            out.append({"path": os.path.join(gdb, ds, fc), "type": "featureclass"})
                            if len(out) >= int(max_items):
                                return out
                    for r in (arcpy.ListRasters() or []):
                        out.append({"path": os.path.join(gdb, r), "type": "raster"})
                        if len(out) >= int(max_items):
                            return out
                finally:
                    arcpy.env.workspace = old_ws
                dirs.remove(d)
        if not recursive:
            break
    return out


def _add_dataset(path, dataframe_name="", layer_name="", position="TOP"):
    arcpy = _arcpy()
    mxd = _mxd()
    df = _df(mxd, dataframe_name)
    lyr = arcpy.mapping.Layer(path)
    if layer_name:
        try:
            lyr.name = layer_name
        except Exception:
            pass
    arcpy.mapping.AddLayer(df, lyr, position.upper())
    return lyr.name


def _clear_layers(mxd):
    arcpy = _arcpy()
    removed = []
    for df in arcpy.mapping.ListDataFrames(mxd):
        layers = list(arcpy.mapping.ListLayers(mxd, "", df))
        for lyr in reversed(layers):
            try:
                arcpy.mapping.RemoveLayer(df, lyr)
                removed.append(lyr.name)
            except Exception:
                pass
    return removed


def _set_extent_all(padding_percent=5.0, dataframe_name=""):
    arcpy = _arcpy()
    mxd = _mxd()
    df = _df(mxd, dataframe_name)
    layers = arcpy.mapping.ListLayers(mxd, "", df)
    exts = []
    for lyr in layers:
        try:
            if not lyr.visible:
                continue
        except Exception:
            pass
        try:
            e = lyr.getExtent()
            if e and e.XMin is not None:
                exts.append(e)
        except Exception:
            pass
    if not exts:
        return {"changed": False, "reason": "no_layer_extents"}
    xmin = min([e.XMin for e in exts]); ymin = min([e.YMin for e in exts])
    xmax = max([e.XMax for e in exts]); ymax = max([e.YMax for e in exts])
    dx = max((xmax - xmin) * float(padding_percent) / 100.0, 0.000001)
    dy = max((ymax - ymin) * float(padding_percent) / 100.0, 0.000001)
    env = arcpy.Extent(xmin - dx, ymin - dy, xmax + dx, ymax + dy)
    df.extent = env
    return {"changed": True, "extent": [env.XMin, env.YMin, env.XMax, env.YMax]}


def _export(path, fmt="PDF", resolution=400):
    arcpy = _arcpy()
    mxd = _mxd()
    fmt = str(fmt).upper()
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    if fmt == "PDF":
        arcpy.mapping.ExportToPDF(mxd, path, resolution=int(resolution))
    elif fmt == "PNG":
        arcpy.mapping.ExportToPNG(mxd, path, resolution=int(resolution))
    elif fmt in ("JPG", "JPEG"):
        arcpy.mapping.ExportToJPEG(mxd, path, resolution=int(resolution))
    elif fmt in ("TIF", "TIFF"):
        arcpy.mapping.ExportToTIFF(mxd, path, resolution=int(resolution))
    else:
        raise ValueError("Unsupported format: %s" % fmt)
    return path


def _save_copy(path):
    mxd = _mxd()
    parent = os.path.dirname(os.path.abspath(path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    mxd.saveACopy(path)
    return path


def _ensure_df(name="Layers", spatial_reference="", activate=True):
    arcpy = _arcpy()
    mxd = _mxd()
    dfs = arcpy.mapping.ListDataFrames(mxd)
    if not dfs:
        raise RuntimeError("CURRENT MXD contains no DataFrame. ArcMap normally creates one; create/open a blank ArcMap document first.")
    df = dfs[0]
    if name:
        try:
            df.name = name
        except Exception:
            pass
    sr = _spatial_ref(spatial_reference)
    if sr:
        try:
            df.spatialReference = sr
        except Exception:
            pass
    return df


def _set_page_a4(orientation="landscape", units="centimeters"):
    # ArcPy does not expose writable page size in Desktop 10.x. Use ArcObjects late binding.
    app, doc, pl, backend = _layout_container()
    orient = str(orientation).lower()
    width_cm, height_cm = ((29.7, 21.0) if orient.startswith("land") else (21.0, 29.7))
    errors = []
    page = getattr(pl, "Page", None)
    if page is None:
        raise RuntimeError("IPageLayout.Page is unavailable.")
    try:
        client, framework, arcmapui, carto = _typed_arcobjects_modules()
        page = page.QueryInterface(carto.IPage)
        backend = backend + "+IPage"
    except Exception:
        # Compatibility fallback when Page already exposes PutCustomSize.
        pass
    for method, args in (
        ("PutCustomSize", (width_cm, height_cm)),
        ("SetCustomSize", (width_cm, height_cm)),
    ):
        try:
            getattr(page, method)(*args)
            return {"changed": True, "backend": backend, "width_cm": width_cm, "height_cm": height_cm, "method": method}
        except Exception as exc:
            errors.append("%s: %r" % (method, exc))
    # Keep going; layout can still be generated on the current page size.
    return {"changed": False, "backend": backend, "requested": [width_cm, height_cm], "warning": "A4 page-size COM method unavailable", "errors": errors}


def _create_featureclass(workspace, name, geometry_type, spatial_reference="", fields=None):
    arcpy = _arcpy()
    if not os.path.isdir(workspace) and not workspace.lower().endswith(".gdb"):
        os.makedirs(workspace)
    sr = _spatial_ref(spatial_reference)
    out = arcpy.CreateFeatureclass_management(workspace, name, geometry_type.upper(), spatial_reference=sr).getOutput(0)
    for fld in fields or []:
        arcpy.AddField_management(out, fld.get("name"), fld.get("type", "TEXT"),
                                  fld.get("precision"), fld.get("scale"), fld.get("length"), fld.get("alias"))
    return out


def _create_xy(csv_path, out_featureclass, x_field, y_field, spatial_reference="EPSG:4326", z_field=""):
    arcpy = _arcpy()
    sr = _spatial_ref(spatial_reference)
    tmp = "zagent_stage3_xy_%d" % int(time.time() * 1000)
    if z_field:
        arcpy.MakeXYEventLayer_management(csv_path, x_field, y_field, tmp, sr, z_field)
    else:
        arcpy.MakeXYEventLayer_management(csv_path, x_field, y_field, tmp, sr)
    arcpy.CopyFeatures_management(tmp, out_featureclass)
    try:
        arcpy.Delete_management(tmp)
    except Exception:
        pass
    return out_featureclass


def _create_geometry(out_fc, geometry_type, features, spatial_reference="EPSG:4326"):
    arcpy = _arcpy()
    sr = _spatial_ref(spatial_reference)
    parent, name = os.path.split(out_fc)
    if not arcpy.Exists(out_fc):
        _create_featureclass(parent, name, geometry_type, spatial_reference)
    geom_type = geometry_type.upper()
    cursor = arcpy.da.InsertCursor(out_fc, ["SHAPE@"])
    try:
        for feat in features:
            coords = feat.get("coordinates")
            if geom_type == "POINT":
                geom = arcpy.PointGeometry(arcpy.Point(float(coords[0]), float(coords[1])), sr)
            elif geom_type == "POLYLINE":
                arr = arcpy.Array([arcpy.Point(float(x), float(y)) for x, y in coords])
                geom = arcpy.Polyline(arr, sr)
            elif geom_type == "POLYGON":
                arr = arcpy.Array([arcpy.Point(float(x), float(y)) for x, y in coords])
                geom = arcpy.Polygon(arr, sr)
            else:
                raise ValueError("geometry_type must be POINT/POLYLINE/POLYGON")
            cursor.insertRow([geom])
    finally:
        del cursor
    return out_fc


def _checkpoint(snapshot_root, label):
    mxd = _mxd()
    if not os.path.isdir(snapshot_root):
        os.makedirs(snapshot_root)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    safe = "".join([c if c.isalnum() or c in "-_" else "_" for c in label])
    path = os.path.join(snapshot_root, "%s_%s.mxd" % (stamp, safe))
    mxd.saveACopy(path)
    return path


def _restore(checkpoint_mxd, target_mxd=""):
    if not os.path.isfile(checkpoint_mxd):
        raise IOError("Checkpoint not found: %s" % checkpoint_mxd)
    if not target_mxd:
        mxd = _mxd()
        target_mxd = getattr(mxd, "filePath", "")
    if not target_mxd:
        raise RuntimeError("target_mxd required because CURRENT document has no filePath")
    parent = os.path.dirname(target_mxd)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent)
    shutil.copy2(checkpoint_mxd, target_mxd)
    return target_mxd


def _build_common(output_dir, base_name, orientation, title, data_root="", spatial_reference="", scale=0.0,
                  include_legend=True, include_north_arrow=True, include_scale_bar=True,
                  save_mxd=True, export_pdf=True, export_png=True, subtitle=""):
    arcpy = _arcpy()
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)
    mxd = _mxd()
    _clear_layers(mxd)
    df = _ensure_df("Layers", spatial_reference, True)
    page = _set_page_a4(orientation)

    added = []
    discovered = []
    if data_root:
        discovered = _discover(data_root, True, 500)
        for item in discovered:
            try:
                added.append(_add_dataset(item["path"], "", "", "TOP"))
            except Exception:
                pass
        if added:
            _set_extent_all(5.0, "")
    if scale and float(scale) > 0:
        try:
            df.scale = float(scale)
        except Exception:
            pass

    layout_results = []
    try:
        layout_results.append(_create_text_impl(title, "MAP_TITLE", 0.50, 0.96, 16.0, True, "CENTER"))
    except Exception as exc:
        layout_results.append({"ok": False, "element": "title", "error": repr(exc)})
    if subtitle:
        try:
            layout_results.append(_create_text_impl(subtitle, "MAP_SUBTITLE", 0.50, 0.92, 9.0, False, "CENTER"))
        except Exception as exc:
            layout_results.append({"ok": False, "element": "subtitle", "error": repr(exc)})
    try:
        layout_results.append(_create_neatline_impl("ZAGENT_NEATLINE", 0.018, 1.0))
    except Exception as exc:
        layout_results.append({"ok": False, "element": "neatline", "error": repr(exc)})
    if include_legend and added:
        try:
            layout_results.append(_create_surround("legend", "ZAGENT_LEGEND", 0.77, 0.16, 0.21, 0.48, "LEGENDA", ""))
        except Exception as exc:
            layout_results.append({"ok": False, "element": "legend", "error": repr(exc)})
    if include_north_arrow:
        try:
            layout_results.append(_create_surround("north_arrow", "ZAGENT_NORTH_ARROW", 0.90, 0.78, 0.07, 0.12, "", ""))
        except Exception as exc:
            layout_results.append({"ok": False, "element": "north_arrow", "error": repr(exc)})
    if include_scale_bar and added:
        try:
            layout_results.append(_create_surround("scale_bar", "ZAGENT_SCALE_BAR", 0.34, 0.055, 0.30, 0.06, "", "meters"))
        except Exception as exc:
            layout_results.append({"ok": False, "element": "scale_bar", "error": repr(exc)})

    outputs = {}
    if save_mxd:
        outputs["mxd"] = _save_copy(os.path.join(output_dir, base_name + ".mxd"))
    if export_pdf:
        outputs["pdf"] = _export(os.path.join(output_dir, base_name + ".pdf"), "PDF", 400)
    if export_png:
        outputs["png"] = _export(os.path.join(output_dir, base_name + ".png"), "PNG", 400)
    try:
        arcpy.RefreshTOC(); arcpy.RefreshActiveView()
    except Exception:
        pass
    return {
        "page": page,
        "discovered_count": len(discovered),
        "added_layers": added,
        "layout": layout_results,
        "outputs": outputs,
    }


def handle_stage3(command):
    action = command.get("action", "")
    p = _cmd_payload(command)
    try:
        if action == "stage3_health":
            mxd = _mxd()
            com_ok = True; com_backend = ""
            try:
                app, com_backend = _active_app()
            except Exception as exc:
                com_ok = False; com_backend = repr(exc)
            return _ok(action,
                       arcgis_version=_arcpy().GetInstallInfo().get("Version", ""),
                       python=sys.version,
                       mxd=getattr(mxd, "filePath", ""),
                       page_size=_page_size(mxd),
                       arcobjects_layout_backend=com_ok,
                       arcobjects_backend_detail=com_backend,
                       action_count=len(STAGE3_ACTIONS),
                       actions=STAGE3_ACTIONS)

        if action == "stage3_blank_init":
            mxd = _mxd()
            removed = _clear_layers(mxd) if p.get("clear_layers", True) else []
            df = _ensure_df(p.get("dataframe_name", "Layers"), "", True)
            if p.get("document_title"):
                try:
                    mxd.title = p.get("document_title")
                except Exception:
                    pass
            return _ok(action, removed_layers=removed, dataframe=df.name, saved=False)

        if action == "stage3_ensure_dataframe":
            df = _ensure_df(p.get("name", "Layers"), p.get("spatial_reference", ""), p.get("activate", True))
            return _ok(action, dataframe=df.name, spatial_reference=getattr(df.spatialReference, "name", ""))

        if action == "stage3_set_page_a4":
            return _ok(action, result=_set_page_a4(p.get("orientation", "landscape"), p.get("units", "centimeters")))

        if action == "stage3_create_text":
            r = _create_text_impl(p.get("text", ""), p.get("name", "ZAGENT_TEXT"), p.get("x_frac", 0.5), p.get("y_frac", 0.95), p.get("font_size", 14.0), p.get("bold", False), p.get("anchor", "CENTER"))
            return _ok(action, result=r)

        if action == "stage3_create_neatline":
            return _ok(action, result=_create_neatline_impl(p.get("name", "ZAGENT_NEATLINE"), p.get("margin_frac", 0.02), p.get("line_width", 1.0)))

        if action == "stage3_create_legend":
            return _ok(action, result=_create_surround("legend", p.get("name", "ZAGENT_LEGEND"), p.get("x_frac", 0.78), p.get("y_frac", 0.20), p.get("width_frac", 0.20), p.get("height_frac", 0.42), p.get("title", "LEGENDA"), ""))

        if action == "stage3_create_north_arrow":
            s = p.get("size_frac", 0.08)
            return _ok(action, result=_create_surround("north_arrow", p.get("name", "ZAGENT_NORTH_ARROW"), p.get("x_frac", 0.92), p.get("y_frac", 0.82), s, s, "", ""))

        if action == "stage3_create_scale_bar":
            return _ok(action, result=_create_surround("scale_bar", p.get("name", "ZAGENT_SCALE_BAR"), p.get("x_frac", 0.38), p.get("y_frac", 0.06), p.get("width_frac", 0.26), 0.06, "", p.get("units", "meters")))

        if action == "stage3_create_featureclass":
            out = _create_featureclass(p["workspace"], p["name"], p["geometry_type"], p.get("spatial_reference", ""), p.get("fields") or [])
            return _ok(action, output=out)

        if action == "stage3_create_xy_featureclass":
            out = _create_xy(p["csv_path"], p["out_featureclass"], p["x_field"], p["y_field"], p.get("spatial_reference", "EPSG:4326"), p.get("z_field", ""))
            return _ok(action, output=out)

        if action == "stage3_create_geometry_features":
            out = _create_geometry(p["out_featureclass"], p["geometry_type"], p.get("features") or [], p.get("spatial_reference", "EPSG:4326"))
            return _ok(action, output=out, inserted=len(p.get("features") or []))

        if action == "stage3_add_dataset_auto":
            name = _add_dataset(p["path"], p.get("dataframe_name", ""), p.get("layer_name", ""), p.get("position", "TOP"))
            return _ok(action, layer=name)

        if action == "stage3_ingest_folder":
            items = _discover(p["data_root"], p.get("recursive", True), p.get("max_items", 500))
            added = []
            if p.get("add_to_map", True):
                for item in items:
                    try:
                        added.append(_add_dataset(item["path"], p.get("dataframe_name", ""), "", "TOP"))
                    except Exception:
                        pass
            return _ok(action, discovered=items, discovered_count=len(items), added_layers=added)

        if action == "stage3_set_extent_auto":
            return _ok(action, result=_set_extent_all(p.get("padding_percent", 5.0), p.get("dataframe_name", "")))

        if action == "stage3_build_blank_a4":
            r = _build_common(p["output_dir"], p.get("base_name", "ZAGENT_STAGE3_MAP"), p.get("orientation", "landscape"), p.get("title", "PETA"),
                              p.get("data_root", ""), p.get("spatial_reference", ""), p.get("scale", 0.0),
                              p.get("include_legend", True), p.get("include_north_arrow", True), p.get("include_scale_bar", True),
                              p.get("save_mxd", True), p.get("export_pdf", True), p.get("export_png", True), "")
            return _ok(action, result=r)

        if action == "stage3_build_no_data_a4":
            r = _build_common(p["output_dir"], p.get("base_name", "ZAGENT_STAGE3_EMPTY_MAP"), p.get("orientation", "landscape"), p.get("title", "PETA"),
                              "", "", 0.0, False, p.get("include_north_arrow", True), False,
                              p.get("save_mxd", True), p.get("export_pdf", True), p.get("export_png", True), p.get("subtitle", ""))
            return _ok(action, result=r)

        if action == "stage3_save_checkpoint":
            path = _checkpoint(p["snapshot_root"], p.get("label", "checkpoint"))
            return _ok(action, checkpoint=path)

        if action == "stage3_restore_checkpoint":
            target = _restore(p["checkpoint_mxd"], p.get("target_mxd", ""))
            return _ok(action, restored_to=target, note="Close/reopen target MXD if CURRENT document is already open")

        if action == "stage3_export_current":
            path = _export(p["output_path"], p.get("format", "PDF"), p.get("resolution", 400))
            return _ok(action, output=path)

        raise ValueError("Unknown Stage3 action: %s" % action)
    except Exception as exc:
        return _fail(action, exc)



# ---------------------------------------------------------------------------
# Explicit Stage 3 registry integration for the modular ArcMap bridge.
# The live dispatcher uses core.registry.ACTIONS; it does not expose the old
# process_command symbol.  Registering here mirrors Stage 2 and is reliable
# across ArcMap 10.6.1 / Python 2.7.
# ---------------------------------------------------------------------------
def _make_registry_handler(action_name):
    def _handler(command):
        cmd = dict(command or {})
        cmd["action"] = action_name
        return handle_stage3(cmd)
    try:
        _handler.__name__ = str(action_name)
    except Exception:
        pass
    return _handler


def install_into_registry(reg):
    if not isinstance(reg, dict):
        raise TypeError("Stage3 registry must be a dict")

    installed = []
    for action_name in STAGE3_ACTIONS:
        reg[action_name] = _make_registry_handler(action_name)
        installed.append(action_name)

    # Augment the existing ping so live diagnostics report the real registry
    # size and Stage 3 state.  Do not add a new action for this wrapper.
    original_ping = reg.get("ping")
    if callable(original_ping) and not getattr(original_ping, "_zagent_stage3_ping_wrapped", False):
        def _ping(command):
            result = original_ping(command)
            if not isinstance(result, dict):
                result = {"ok": True, "result": result}
            result["bridge_action_count"] = len(reg)
            result["stage3_bridge_loaded"] = True
            result["stage3_bridge_action_count"] = len(STAGE3_ACTIONS)
            result["stage3_bridge_actions"] = list(STAGE3_ACTIONS)
            return result
        _ping._zagent_stage3_ping_wrapped = True
        _ping._zagent_stage3_original = original_ping
        reg["ping"] = _ping

    return sorted(installed)

def install_process_command(original):
    global _ORIGINAL_PROCESS_COMMAND
    _ORIGINAL_PROCESS_COMMAND = original
    if getattr(original, "_zagent_stage3_wrapped", False):
        return original

    def wrapped(command):
        action = ""
        try:
            action = (command or {}).get("action", "")
        except Exception:
            pass
        if action in STAGE3_ACTIONS or str(action).startswith("stage3_"):
            return handle_stage3(command)
        result = original(command)
        if action == "ping" and isinstance(result, dict):
            try:
                old_count = int(result.get("bridge_action_count", 0) or 0)
                if old_count < 98 + len(STAGE3_ACTIONS):
                    result["bridge_action_count"] = old_count + len(STAGE3_ACTIONS)
                result["stage3_bridge_loaded"] = True
                result["stage3_bridge_action_count"] = len(STAGE3_ACTIONS)
                result["stage3_bridge_actions"] = list(STAGE3_ACTIONS)
            except Exception:
                pass
        return result
    wrapped._zagent_stage3_wrapped = True
    wrapped._zagent_stage3_original = original
    return wrapped
