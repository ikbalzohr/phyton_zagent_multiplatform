# -*- coding: utf-8 -*-
"""ARC-06: attach an ArcGIS MapServer to CURRENT MXD without exporting SHP.

The ArcGIS Server 'View in ArcMap' layer descriptor is a temporary .lyr,
not a feature download. Authenticated/HTTP endpoints fail closed.
"""
from __future__ import print_function
import os
import re
import tempfile
import urllib
import urllib2
import urlparse
import arcpy

from core.registry import action
from core.current_map import get_mxd, get_dataframe
from core.safety import require_live_write

_MAPSERVER = re.compile(r"^/[^?#]*/MapServer/?$", re.I)


def normalize_service_url(value):
    parsed = urlparse.urlsplit(str(value or "").strip())
    if (parsed.scheme.lower() != "https" or not parsed.hostname or
            parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Only credential-free HTTPS MapServer service URLs are supported")
    if not _MAPSERVER.match(parsed.path):
        raise ValueError("URL must point to a MapServer root, not a sublayer or REST query")
    host = parsed.hostname.lower()
    if host in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Localhost services are not allowed")
    return urlparse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def layer_descriptor(url, limit=8388608):
    target = url + "?f=lyr"
    response = urllib2.urlopen(urllib2.Request(target, headers={
        "User-Agent": "ZagentArcMap/3.0",
        "Accept": "application/octet-stream"
    }), timeout=20)
    try:
        if urlparse.urlsplit(response.geturl()).scheme.lower() != "https":
            raise RuntimeError("Insecure redirect refused")
        content = response.read(limit + 1)
    finally:
        response.close()
    if not content or len(content) > limit:
        raise RuntimeError("MapServer layer descriptor is empty or too large")
    if content.lstrip()[:1] in (b"<", b"{", b"["): 
        raise RuntimeError("Server did not return a binary ArcMap .lyr descriptor")
    return content


@action("connect_gis_mapserver")
def connect_gis_mapserver(command):
    blocked = require_live_write()
    if blocked:
        return blocked
    service = normalize_service_url(command.get("service_url"))
    descriptor = layer_descriptor(service)
    name = str(command.get("layer_name") or "").strip()
    if name and (len(name) > 128 or any(ord(ch) < 32 for ch in name)):
        raise ValueError("Invalid layer_name")
    mxd = get_mxd()
    df = get_dataframe(mxd, command.get("data_frame") or "")
    for lyr in arcpy.mapping.ListLayers(mxd, "", df):
        if name and lyr.name == name:
            raise RuntimeError("Layer name already in CURRENT dataframe")
    handle, path = tempfile.mkstemp(suffix=".lyr", prefix="zagent_mapserver_")
    try:
        stream = os.fdopen(handle, "wb")
        try:
            stream.write(descriptor)
        finally:
            stream.close()
        layer = arcpy.mapping.Layer(path)
        if name:
            layer.name = name
        arcpy.mapping.AddLayer(df, layer, "TOP")
        arcpy.RefreshTOC()
        arcpy.RefreshActiveView()
    finally:
        if os.path.isfile(path):
            os.unlink(path)
    return {"ok": True, "service_url": service, "data_frame": df.name,
            "layer_name": name or layer.name, "saved": False,
            "shapefile_downloaded": False, "verified_on_arcmap": False}
