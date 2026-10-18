from pathlib import Path

RASTER_EXTENSIONS = {".tif", ".tiff", ".jpg", ".jpeg", ".png", ".ecw", ".sid", ".img"}

def find_exports(folder):
    folder = Path(folder)
    if not folder.exists():
        return []
    rows = []
    for p in folder.rglob("*"):
        if p.is_file() and p.suffix.lower() in RASTER_EXTENSIONS:
            rows.append({"name": p.name, "path": str(p), "size_bytes": p.stat().st_size})
    return rows
