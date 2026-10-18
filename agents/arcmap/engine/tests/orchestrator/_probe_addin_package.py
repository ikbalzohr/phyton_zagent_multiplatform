
import hashlib, json, zipfile
from pathlib import Path

paths = [
    Path(r"C:\Users\fazrin\Documents\ArcGIS\AddIns\Desktop10.6\{B88AE9DB-CC43-4EA0-8B91-A72FC933D690}\Zagent.ArcMap.esriaddin"),
    Path(r"D:\3-Ikbalzohr\Agent\appBridge\production\Zagent\v3\agents\arcmap\artifacts\Zagent.ArcMap.esriaddin"),
    Path(r"D:\3-Ikbalzohr\Agent\ZohrSystem\Zagent\agents\arcmap\artifacts\Zagent.ArcMap.esriaddin"),
]
for p in paths:
    print("PATH", p)
    print("EXISTS", p.exists())
    if not p.exists():
        continue
    raw=p.read_bytes()
    print("SHA256", hashlib.sha256(raw).hexdigest(), "SIZE", len(raw))
    with zipfile.ZipFile(str(p),"r") as z:
        print("NAMES", z.namelist())
        for name in z.namelist():
            if name.lower().endswith("config.xml"):
                print("CONFIG", z.read(name).decode("utf-8","replace"))
