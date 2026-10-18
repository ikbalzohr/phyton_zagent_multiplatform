from __future__ import annotations

import ast
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from app.paths import ENGINE_ROOT, CONFIG_DIR, UPDATE_STATE_ROOT
APP_ROOT = ENGINE_ROOT
STATE_ROOT = UPDATE_STATE_ROOT
STAGING_ROOT = STATE_ROOT / "staging"
BACKUP_ROOT = STATE_ROOT / "backups"
HISTORY_FILE = STATE_ROOT / "history.jsonl"
LAST_RESULT_FILE = STATE_ROOT / "last_result.json"
REQUEST_ROOT = STATE_ROOT / "requests"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
SETTINGS = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))

MAX_STAGE_FILE_BYTES = int(SETTINGS.get("max_stage_file_bytes", 20 * 1024 * 1024))
MAX_STAGE_TOTAL_BYTES = int(SETTINGS.get("max_stage_total_bytes", 100 * 1024 * 1024))
PROTECTED = {
    ".env",
    ".env.development",
    ".env.local",
    ".env.production",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
    "profiles.json",
    "secrets.json",
}
LAUNCHER = None


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe_update_id(update_id: str) -> str:
    value = str(update_id or "").strip()
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")
    if not value or any(c not in allowed for c in value):
        raise ValueError("update_id tidak valid.")
    return value


def _safe_rel(path: str) -> Path:
    raw = str(path or "").replace("\\", "/").strip("/")
    if not raw:
        raise ValueError("Path update tidak boleh kosong.")
    p = Path(raw)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError("Path update harus relatif terhadap app root.")
    if p.name.lower() in PROTECTED:
        raise PermissionError(f"File dilindungi dari self-update: {p.name}")
    return p


def _stage_dir(update_id: str) -> Path:
    return STAGING_ROOT / _safe_update_id(update_id)


def _meta_path(update_id: str) -> Path:
    return _stage_dir(update_id) / "metadata.json"


def _load_meta(update_id: str) -> Dict[str, Any]:
    path = _meta_path(update_id)
    if not path.exists():
        raise FileNotFoundError(f"Update belum diprepare: {update_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _save_meta(update_id: str, data: Dict[str, Any]) -> None:
    d = _stage_dir(update_id)
    d.mkdir(parents=True, exist_ok=True)
    tmp = _meta_path(update_id).with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, _meta_path(update_id))


def _append_history(record: Dict[str, Any]) -> None:
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def capabilities() -> Dict[str, Any]:
    return {
        "ok": True,
        "self_update": True,
        "update_owner": "Zagent Core",
        "app_root": str(APP_ROOT),
        "state_root": str(STATE_ROOT),
        "max_stage_file_bytes": MAX_STAGE_FILE_BYTES,
        "max_stage_total_bytes": MAX_STAGE_TOTAL_BYTES,
        "protected_secret_names": sorted(PROTECTED),
        "supports": [
            "prepare",
            "stage_text",
            "stage_b64",
            "mark_delete",
            "validate",
            "apply",
            "rollback",
            "history",
            "abort",
        ],
        "launcher": None,
        "launcher_exists": False,
        "bootstrap_version": (APP_ROOT / "VERSION").read_text(encoding="utf-8").strip()
        if (APP_ROOT / "VERSION").exists() else "3.x",
    }


def status() -> Dict[str, Any]:
    staged: List[Dict[str, Any]] = []
    if STAGING_ROOT.exists():
        for d in sorted(STAGING_ROOT.iterdir()):
            meta = d / "metadata.json"
            if d.is_dir() and meta.exists():
                try:
                    staged.append(json.loads(meta.read_text(encoding="utf-8")))
                except Exception:
                    pass
    last = None
    if LAST_RESULT_FILE.exists():
        try:
            last = json.loads(LAST_RESULT_FILE.read_text(encoding="utf-8"))
        except Exception:
            last = None
    return {"ok": True, "staged": staged, "last_result": last}


def prepare(update_id: str, description: str = "", target_version: str = "") -> Dict[str, Any]:
    update_id = _safe_update_id(update_id)
    d = _stage_dir(update_id)
    if d.exists():
        shutil.rmtree(d)
    (d / "files").mkdir(parents=True, exist_ok=True)
    meta = {
        "update_id": update_id,
        "description": description,
        "target_version": target_version,
        "created_at": _now(),
        "status": "prepared",
        "files": {},
        "deletes": [],
        "validated": False,
    }
    _save_meta(update_id, meta)
    return meta


def _total_stage_bytes(meta: Dict[str, Any]) -> int:
    return sum(int(x.get("bytes", 0)) for x in meta.get("files", {}).values())


def stage_text(update_id: str, path: str, content: str, encoding: str = "utf-8", expected_sha256: str = "") -> Dict[str, Any]:
    rel = _safe_rel(path)
    raw = content.encode(encoding)
    return _stage_bytes(update_id, rel, raw, expected_sha256, encoding=encoding)


def stage_b64(update_id: str, path: str, content_b64: str, expected_sha256: str = "") -> Dict[str, Any]:
    rel = _safe_rel(path)
    raw = base64.b64decode(content_b64.encode("ascii"), validate=True)
    return _stage_bytes(update_id, rel, raw, expected_sha256, encoding=None)


def _stage_bytes(update_id: str, rel: Path, raw: bytes, expected_sha256: str, encoding: str | None) -> Dict[str, Any]:
    if len(raw) > MAX_STAGE_FILE_BYTES:
        raise ValueError("File staging terlalu besar.")
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 and digest.lower() != expected_sha256.lower():
        raise ValueError("SHA-256 staged content tidak sesuai expected_sha256.")
    meta = _load_meta(update_id)
    current_total = _total_stage_bytes(meta)
    prior = meta.get("files", {}).get(rel.as_posix(), {})
    next_total = current_total - int(prior.get("bytes", 0)) + len(raw)
    if next_total > MAX_STAGE_TOTAL_BYTES:
        raise ValueError("Total staging melebihi batas.")
    target = _stage_dir(update_id) / "files" / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    meta.setdefault("files", {})[rel.as_posix()] = {
        "bytes": len(raw),
        "sha256": digest,
        "encoding": encoding,
    }
    meta["validated"] = False
    meta["status"] = "staged"
    _save_meta(update_id, meta)
    return {"ok": True, "update_id": update_id, "path": rel.as_posix(), "bytes": len(raw), "sha256": digest}


def mark_delete(update_id: str, path: str) -> Dict[str, Any]:
    rel = _safe_rel(path)
    meta = _load_meta(update_id)
    value = rel.as_posix()
    if value not in meta.setdefault("deletes", []):
        meta["deletes"].append(value)
    meta["validated"] = False
    meta["status"] = "staged"
    _save_meta(update_id, meta)
    return {"ok": True, "update_id": update_id, "delete": value}


def validate(update_id: str) -> Dict[str, Any]:
    meta = _load_meta(update_id)
    errors: List[str] = []
    files_dir = _stage_dir(update_id) / "files"
    total = 0
    for rel_text, spec in meta.get("files", {}).items():
        rel = _safe_rel(rel_text)
        p = files_dir / rel
        if not p.exists():
            errors.append(f"Missing staged file: {rel_text}")
            continue
        size = p.stat().st_size
        total += size
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        if size != int(spec.get("bytes", -1)):
            errors.append(f"Size mismatch: {rel_text}")
        if digest.lower() != str(spec.get("sha256", "")).lower():
            errors.append(f"SHA mismatch: {rel_text}")
        if p.suffix.lower() == ".py":
            try:
                ast.parse(p.read_text(encoding="utf-8"), filename=rel_text)
            except Exception as exc:
                errors.append(f"Python syntax error {rel_text}: {exc}")
        if p.suffix.lower() == ".json":
            try:
                json.loads(p.read_text(encoding="utf-8"))
            except Exception as exc:
                errors.append(f"JSON parse error {rel_text}: {exc}")
    if total > MAX_STAGE_TOTAL_BYTES:
        errors.append("Total staging melebihi batas.")
    for rel_text in meta.get("deletes", []):
        try:
            _safe_rel(rel_text)
        except Exception as exc:
            errors.append(str(exc))
    ok = not errors
    meta["validated"] = ok
    meta["validated_at"] = _now()
    meta["status"] = "validated" if ok else "validation_failed"
    meta["validation_errors"] = errors
    _save_meta(update_id, meta)
    return {"ok": ok, "update_id": update_id, "files": len(meta.get("files", {})), "deletes": len(meta.get("deletes", [])), "total_bytes": total, "errors": errors}


def _queue_core_update(action: str, update_id: str) -> Dict[str, Any]:
    meta = _load_meta(update_id)
    if action == "apply" and not meta.get("validated"):
        raise ValueError("Update belum tervalidasi.")
    if action == "rollback":
        backup_dir = BACKUP_ROOT / _safe_update_id(update_id)
        if not (backup_dir / "manifest.json").exists():
            raise FileNotFoundError(f"Backup update tidak ditemukan: {update_id}")

    REQUEST_ROOT.mkdir(parents=True, exist_ok=True)
    request = {
        "schema_version": 1,
        "request_id": f"files-update-{_safe_update_id(update_id)}-{action}",
        "component": "files",
        "action": action,
        "update_id": _safe_update_id(update_id),
        "requested_at": _now(),
        "status": "pending_core",
        "engine_root": str(APP_ROOT),
        "state_root": str(STATE_ROOT),
    }
    target = REQUEST_ROOT / (request["request_id"] + ".json")
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, target)
    return {
        "ok": True,
        "queued": True,
        "requires_core": True,
        "request_id": request["request_id"],
        "request_file": str(target),
        "action": action,
        "update_id": update_id,
    }


def apply(update_id: str) -> Dict[str, Any]:
    return _queue_core_update("apply", update_id)


def rollback(update_id: str) -> Dict[str, Any]:
    return _queue_core_update("rollback", update_id)


def history(limit: int = 20) -> List[Dict[str, Any]]:
    if not HISTORY_FILE.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows[-int(limit):][::-1]


def abort(update_id: str) -> Dict[str, Any]:
    meta = _load_meta(update_id)
    if meta.get("status") in {"applied", "rolled_back"}:
        raise ValueError("Update yang sudah applied/rolled back tidak dapat diabort.")
    shutil.rmtree(_stage_dir(update_id))
    return {"ok": True, "update_id": update_id, "aborted": True}