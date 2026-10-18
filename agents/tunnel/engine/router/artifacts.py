"""Artifact delivery by opaque ID; no caller-supplied filesystem locator."""
from __future__ import annotations
import base64
import hashlib
import os
from pathlib import Path
from typing import Any


def read_artifact(journal, artifact_id: str, owner: str, approved_roots: list[str],
                  offset: int = 0, length: int = 65536) -> dict[str, Any]:
    if not isinstance(offset, int) or offset < 0 or not isinstance(length, int) or not 1 <= length <= 262144:
        raise ValueError("INVALID_RANGE")
    with journal._lock:
        row = journal.conn.execute("SELECT a.* FROM artifacts a JOIN workflow_runs r ON r.run_id=a.run_id WHERE a.artifact_id=? AND r.owner_session_id=? AND a.valid=1", (artifact_id, owner)).fetchone()
    if row is None:
        raise KeyError("ARTIFACT_NOT_FOUND")
    path = Path(row["path"]).resolve(strict=True)
    roots = [Path(root).resolve(strict=True) for root in approved_roots]
    if not any(path.is_relative_to(root) for root in roots) or not path.is_file():
        raise PermissionError("ARTIFACT_NOT_AUTHORIZED")
    # Hash and read the same opened object; mutation during delivery is rejected.
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        magic = stream.read(16)
        stream.seek(0)
        mime = "application/pdf" if magic.startswith(b"%PDF-") else ("image/png" if magic.startswith(b"\x89PNG\r\n\x1a\n") else ("image/jpeg" if magic.startswith(b"\xff\xd8\xff") else "application/octet-stream"))
        hasher = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            hasher.update(chunk)
        actual = hasher.hexdigest()
        if actual != row["content_hash"]:
            raise ValueError("ARTIFACT_HASH_MISMATCH")
        stream.seek(offset)
        content = stream.read(length)
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("ARTIFACT_CHANGED")
    return {"ok":True,"artifact_id":artifact_id,"run_id":row["run_id"],
            "sha256":actual,"size":before.st_size,"offset":offset,"length":len(content),
            "mime_type":mime,
            "mime_detection":"magic-or-octet-stream", "encoding":"base64",
            "content":base64.b64encode(content).decode("ascii"),
            "eof":offset+len(content) >= before.st_size}
