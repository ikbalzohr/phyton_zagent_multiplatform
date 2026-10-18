import json
from pathlib import Path

PROFILE_DIR = Path(__file__).resolve().parent / "map_profiles"

def list_profiles():
    return sorted(p.stem for p in PROFILE_DIR.glob("*.json"))

def load_profile(name):
    path = PROFILE_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))

def profile_name_from_mxd(filename):
    stem = Path(filename).stem
    if " - " not in stem:
        return ""
    return stem.rsplit(" - ", 1)[1].strip().title()
