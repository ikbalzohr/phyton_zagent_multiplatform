from __future__ import annotations

import os
from pathlib import Path

DATASET_EXTENSIONS = {
    ".shp": "SHP",
    ".lyr": "LYR",
    ".ecw": "ECW",
    ".tif": "TIF",
    ".tiff": "TIFF",
    ".img": "IMG",
    ".sid": "SID",
    ".jpg": "JPG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".bmp": "BMP",
    ".csv": "CSV",
    ".dbf": "DBF",
}

DEFAULT_SKIP_DIRS = {
    "hasil peta",
    "work",
    "_jobs",
    "_snapshots",
    ".zagent",
    "__pycache__",
}


def _shape_sidecars(path):
    base = os.path.splitext(path)[0]
    sidecars = {}
    for ext in (".dbf", ".shx", ".prj", ".cpg", ".sbn", ".sbx", ".shp.xml"):
        candidate = base + ext
        if os.path.exists(candidate):
            sidecars[ext.lstrip(".").replace(".", "_")] = candidate
    return sidecars


def discover_project_datasets(root, skip_dirs=None, max_items=5000):
    root = os.path.abspath(str(root or ""))
    if not root or not os.path.isdir(root):
        return {
            "ok": False,
            "root": root,
            "items": [],
            "count": 0,
            "warnings": ["data_root_not_found"],
        }
    skip = set(x.lower() for x in (skip_dirs or DEFAULT_SKIP_DIRS))
    items = []
    warnings = []
    for current, dirs, files in os.walk(root):
        dirs[:] = [
            d for d in dirs
            if d.lower() not in skip and not d.lower().endswith(".gdb")
        ]
        for filename in files:
            ext = Path(filename).suffix.lower()
            if ext not in DATASET_EXTENSIONS:
                continue
            # DBF is only emitted as a standalone table when no sibling SHP exists.
            full = os.path.join(current, filename)
            if ext == ".dbf" and os.path.exists(os.path.splitext(full)[0] + ".shp"):
                continue
            row = {
                "path": full,
                "relative": os.path.relpath(full, root),
                "name": filename,
                "kind": DATASET_EXTENSIONS[ext],
                "extension": ext,
                "size_bytes": os.path.getsize(full),
                "source": "filesystem_discovery",
            }
            if ext == ".shp":
                row["sidecars"] = _shape_sidecars(full)
                missing = [
                    x for x in ("dbf", "shx")
                    if x not in row["sidecars"]
                ]
                if missing:
                    row["integrity_warning"] = "missing_sidecars:" + ",".join(missing)
            items.append(row)
            if len(items) >= int(max_items):
                warnings.append("max_items_reached")
                break
        if len(items) >= int(max_items):
            break
    items.sort(key=lambda x: (x.get("kind", ""), x.get("relative", "").lower()))
    return {
        "ok": True,
        "root": root,
        "items": items,
        "count": len(items),
        "warnings": warnings,
    }


def merge_explicit_and_discovered(explicit, discovered):
    rows = []
    seen = set()
    for source in (explicit or [], (discovered or {}).get("items") or []):
        for item in source:
            row = dict(item or {})
            key = os.path.normcase(os.path.abspath(str(row.get("path") or ""))) if row.get("path") else ""
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            rows.append(row)
    return rows
