# -*- coding: utf-8 -*-
import os
import struct
import tempfile
import hashlib
import arcpy
from core.registry import action
from core.current_map import get_mxd, get_dataframe
from core.bridge_state import context
from core.safety import require_export
from core.path_guard import guard_manual_write

def verify_output(path, kind):
    size = os.path.getsize(path)
    if size < 16:
        raise RuntimeError("EXPORT_INVALID: output is empty/truncated.")
    with open(path, "rb") as stream:
        head = stream.read(32)
        stream.seek(max(0, size - 1024))
        tail = stream.read()
    dimensions = None
    if kind == "png":
        if head[:8] != b"\x89PNG\r\n\x1a\n" or b"IEND" not in tail:
            raise RuntimeError("EXPORT_INVALID: incomplete PNG.")
        dimensions = list(struct.unpack(">II", head[16:24]))
        if min(dimensions) < 1:
            raise RuntimeError("EXPORT_INVALID: invalid PNG dimensions.")
    elif kind == "pdf" and (not head.startswith(b"%PDF-") or b"%%EOF" not in tail):
        raise RuntimeError("EXPORT_INVALID: incomplete PDF.")
    elif kind == "jpeg" and (head[:2] != b"\xff\xd8" or not tail.rstrip().endswith(b"\xff\xd9")):
        raise RuntimeError("EXPORT_INVALID: incomplete JPEG.")
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"bytes": size, "sha256": digest.hexdigest(), "dimensions": dimensions, "format": kind}

def _prepare(path, overwrite):
    if not path:
        raise RuntimeError("output_path is required")
    blocked = guard_manual_write(path, "output_path")
    if blocked:
        return blocked
    folder = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(folder):
        os.makedirs(folder)
    if os.path.exists(path) and not overwrite:
        raise RuntimeError("Output exists and overwrite=False: {0}".format(path))
    return None

def _export(command, kind):
    blocked = require_export()
    if blocked:
        return blocked
    path = command.get("output_path", "")
    blocked = _prepare(path, bool(command.get("overwrite", False)))
    if blocked:
        return blocked
    resolution = int(command.get("resolution", 400))
    if not 1 <= resolution <= 2400:
        raise ValueError("Resolution must be between 1 and 2400 DPI.")
    mxd = get_mxd()
    before = context(mxd)
    fd, temporary = tempfile.mkstemp(prefix=".zagent-export-", suffix="." + kind,
                                     dir=os.path.dirname(os.path.abspath(path)))
    os.close(fd)
    os.remove(temporary)
    try:
        if kind == "pdf":
            arcpy.mapping.ExportToPDF(mxd, temporary, resolution=resolution)
        elif kind == "png":
            dataframe = command.get("data_frame", "")
            if dataframe:
                arcpy.mapping.ExportToPNG(mxd, temporary, get_dataframe(mxd, dataframe),
                    df_export_width=1600, df_export_height=1200, resolution=resolution)
            else:
                arcpy.mapping.ExportToPNG(mxd, temporary, resolution=resolution)
        else:
            arcpy.mapping.ExportToJPEG(mxd, temporary, resolution=resolution,
                                      jpeg_quality=int(command.get("jpeg_quality", 90)))
        verified = verify_output(temporary, kind)
        if context(get_mxd()) != before:
            raise RuntimeError("CURRENT_MXD_CHANGED during export.")
        if os.path.exists(path):
            if not command.get("overwrite", False):
                raise RuntimeError("Output appeared during export; refusing overwrite.")
            import ctypes
            if not ctypes.windll.kernel32.MoveFileExW(
                    unicode(temporary), unicode(os.path.abspath(path)), 1):
                raise RuntimeError("Could not atomically replace output.")
        else:
            os.rename(temporary, path)
        verified.update(ok=True, output_path=path, resolution=resolution,
                        context=before, saved=False)
        return verified
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)

@action("export_pdf")
def export_pdf(command):
    return _export(command, "pdf")

@action("export_png")
def export_png(command):
    return _export(command, "png")

@action("export_jpeg")
def export_jpeg(command):
    return _export(command, "jpeg")
