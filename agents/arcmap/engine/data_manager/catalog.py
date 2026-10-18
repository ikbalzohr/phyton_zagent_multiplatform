from pathlib import Path
import json
from .path_guard import ensure_writable

SPATIAL_EXTENSIONS = {".shp", ".tif", ".tiff", ".img", ".ecw", ".sid", ".kml", ".kmz", ".lyr", ".mxd"}

def scan(root):
    root = Path(root)
    rows = []
    if not root.exists():
        return rows
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in SPATIAL_EXTENSIONS:
            rows.append({
                "name": p.name,
                "path": str(p),
                "extension": p.suffix.lower(),
                "size_bytes": p.stat().st_size,
            })
        elif p.is_dir() and p.suffix.lower() == ".gdb":
            rows.append({"name": p.name, "path": str(p), "extension": ".gdb", "size_bytes": None})
    return rows

def save_catalog(root, output_json):
    rows = scan(root)
    ensure_writable(output_json).write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    return rows

def find(catalog, text):
    needle = text.lower()
    return [r for r in catalog if needle in r["name"].lower() or needle in r["path"].lower()]
