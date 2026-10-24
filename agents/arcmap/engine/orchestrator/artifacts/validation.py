import hashlib
import struct
from pathlib import Path

def sha256_file(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def validate_pdf(path,metadata=None):
    p=Path(path); meta=metadata or {}
    if not p.exists() or p.stat().st_size<5: return {"ok":False,"code":"ARTIFACT_INVALID","reason":"missing_or_empty"}
    with p.open("rb") as f: head=f.read(5)
    if head!=b"%PDF-": return {"ok":False,"code":"ARTIFACT_INVALID","reason":"bad_pdf_signature"}
    dpi=int(meta.get("dpi") or 0)
    if dpi and dpi<400: return {"ok":False,"code":"ARTIFACT_INVALID","reason":"dpi_below_policy","dpi":dpi}
    return {"ok":True,"kind":"PDF","sha256":sha256_file(p),"bytes":p.stat().st_size,"dpi":dpi or None}

def validate_png(path,metadata=None):
    p=Path(path); meta=metadata or {}
    if not p.exists() or p.stat().st_size<24: return {"ok":False,"code":"ARTIFACT_INVALID","reason":"missing_or_short"}
    data=p.read_bytes()[:24]
    if data[:8]!=b"\x89PNG\r\n\x1a\n" or data[12:16]!=b"IHDR":
        return {"ok":False,"code":"ARTIFACT_INVALID","reason":"bad_png_signature"}
    w,h=struct.unpack(">II",data[16:24])
    if w<=0 or h<=0: return {"ok":False,"code":"ARTIFACT_INVALID","reason":"bad_dimensions"}
    dpi=int(meta.get("dpi") or 0)
    if dpi and dpi<400: return {"ok":False,"code":"ARTIFACT_INVALID","reason":"dpi_below_policy","dpi":dpi}
    return {"ok":True,"kind":"PNG","sha256":sha256_file(p),"bytes":p.stat().st_size,"width":w,"height":h,"dpi":dpi or None}
