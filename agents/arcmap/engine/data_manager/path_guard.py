import json
import ntpath
import os
from pathlib import Path

ENGINE_ROOT = Path(
    os.environ.get("ZAGENT_ARCMAP_ENGINE_ROOT")
    or Path(__file__).resolve().parents[1]
)
DATA_ROOT = Path(
    os.environ.get("ZAGENT_ARCMAP_DATA_ROOT")
    or (ENGINE_ROOT.parent / "data")
)
CONFIG_DIR = Path(
    os.environ.get("ZAGENT_ARCMAP_CONFIG_DIR")
    or (DATA_ROOT / "config")
)
STATIC_CONFIG = ENGINE_ROOT / "config" / "paths.json"

def _manual_root():
    for path in (CONFIG_DIR / "paths.json", STATIC_CONFIG):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            value = data.get("manual_baseline") or ""
            if value:
                return value
        except Exception:
            pass
    return ""

def _normalize(path):
    text = os.path.expandvars(os.path.expanduser(str(path)))
    return ntpath.normcase(ntpath.abspath(text))

def is_within(path, root):
    if not root:
        return False
    child = _normalize(path)
    base = _normalize(root)
    return child == base or child.startswith(base.rstrip("\\/") + "\\")

def ensure_writable(path):
    manual = _manual_root()
    if manual and is_within(path, manual):
        raise PermissionError(
            "Write blocked: configured immutable baseline is read-only: {0}".format(path)
        )
    return Path(path)
