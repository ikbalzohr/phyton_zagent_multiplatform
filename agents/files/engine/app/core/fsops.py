from __future__ import annotations

import ast
import base64
import difflib
import fnmatch
import hashlib
import json
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

from app.profiles.manager import active_profile, get_profile, list_profiles
from app.paths import CONFIG_DIR, BACKUP_ROOT

SETTINGS_FILE = CONFIG_DIR / "settings.json"
SETTINGS = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))

MAX_READ = int(SETTINGS.get("max_read_bytes", 10 * 1024 * 1024))
MAX_WRITE = int(SETTINGS.get("max_write_bytes", 50 * 1024 * 1024))
SECRET_NAMES = {x.lower() for x in SETTINGS.get("secret_names", [])}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _profile_root(profile: Dict[str, Any]) -> Path:
    return Path(profile["root"]).resolve()


def root() -> Path:
    return _profile_root(active_profile())


def resolve(path: str = ".", profile: Dict[str, Any] | None = None) -> Path:
    profile = profile or active_profile()
    if not profile.get("enabled", True) or not profile.get("authorized_by_user"):
        raise PermissionError("Profile is disabled or not approved")
    base = _profile_root(profile)
    raw = str(path or ".")
    candidate = Path(raw).resolve() if os.path.isabs(raw) else (base / raw).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise ValueError("Path berada di luar root profile.")
    return candidate


def rel(path: Path, profile: Dict[str, Any] | None = None) -> str:
    profile = profile or active_profile()
    return str(path.resolve().relative_to(_profile_root(profile)))


def require_write(profile: Dict[str, Any] | None = None) -> Dict[str, Any]:
    profile = profile or active_profile()
    if profile.get("mode") != "read-write":
        raise PermissionError("Profile aktif adalah read-only.")
    if not profile.get("enabled", True):
        raise PermissionError("Profile dinonaktifkan.")
    return profile


def guard_secret(path: Path) -> None:
    if path.name.lower() in SECRET_NAMES:
        raise PermissionError("File rahasia dilindungi.")


def guard_root_delete(path: Path, profile: Dict[str, Any] | None = None) -> None:
    profile = profile or active_profile()
    if path.resolve() == _profile_root(profile):
        raise PermissionError("Sandbox root tidak boleh dihapus.")


def _backup_id() -> str:
    import uuid
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + str(uuid.uuid4().int)


def backup(path: Path, reason: str = "manual", profile: Dict[str, Any] | None = None) -> Dict[str, Any]:
    profile = profile or active_profile()
    path = path.resolve()
    if not path.exists():
        raise FileNotFoundError(str(path))
    backup_id = _backup_id()
    dest = BACKUP_ROOT / backup_id
    payload = dest / "payload"
    dest.mkdir(parents=True, exist_ok=False)
    if path.is_dir():
        shutil.copytree(path, payload)
        kind = "dir"
    else:
        payload.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, payload)
        kind = "file"
    meta = {
        "backup_id": backup_id,
        "profile": profile.get("name"),
        "root": profile.get("root"),
        "original_path": str(path),
        "relative_path": rel(path, profile),
        "kind": kind,
        "reason": reason,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    (dest / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


def backup_before_overwrite(path: Path, reason: str) -> str | None:
    if not path.exists():
        return None
    return backup(path, reason=reason)["backup_id"]


def backup_list(limit: int = 50) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for d in sorted(BACKUP_ROOT.iterdir(), reverse=True):
        meta = d / "metadata.json"
        if not d.is_dir() or not meta.exists():
            continue
        try:
            record = json.loads(meta.read_text(encoding="utf-8"))
            if record.get('profile') != active_profile()['name']:
                continue
            rows.append(record)
        except Exception:
            continue
        if len(rows) >= int(limit):
            break
    return rows


def restore_backup(backup_id: str, overwrite: bool = True) -> Dict[str, Any]:
    if not backup_id or any(c not in "0123456789_" for c in backup_id):
        raise ValueError("Invalid backup ID")
    d = BACKUP_ROOT / backup_id
    meta_path = d / "metadata.json"
    payload = d / "payload"
    if not meta_path.exists() or not payload.exists():
        raise FileNotFoundError(f"Backup tidak ditemukan: {backup_id}")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    current = active_profile()
    if meta.get("profile") != current.get("name"):
        raise PermissionError("Backup hanya dapat direstore saat profile asal sedang aktif.")
    target = Path(meta["original_path"]).resolve()
    resolve(str(target), current)
    require_write(current)
    if target.exists():
        if not overwrite:
            raise FileExistsError(str(target))
        backup(target, reason=f"pre_restore_{backup_id}", profile=current)
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    if meta["kind"] == "dir":
        shutil.copytree(payload, target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(payload, target)
    return {"ok": True, "backup_id": backup_id, "restored_to": str(target)}


def file_tree(path: str = ".", max_depth: int = 4, max_items: int = 1000) -> Dict[str, Any]:
    base = resolve(path)
    if not base.exists():
        raise FileNotFoundError(str(base))
    items: List[Dict[str, str]] = []
    truncated = False

    def walk(cur: Path, depth: int):
        nonlocal truncated
        if truncated or depth > max_depth:
            return
        if not cur.is_dir():
            return
        try:
            children = sorted(cur.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except PermissionError:
            return
        for child in children:
            if len(items) >= max_items:
                truncated = True
                return
            items.append({"path": rel(child), "type": "dir" if child.is_dir() else "file"})
            if child.is_dir() and depth < max_depth:
                walk(child, depth + 1)

    walk(base, 1)
    return {"root": path, "items": items, "truncated": truncated}


def stat(path: str) -> Dict[str, Any]:
    p = resolve(path)
    guard_secret(p)
    st = p.stat()
    out = {
        "path": path,
        "type": "dir" if p.is_dir() else "file",
        "size": st.st_size,
        "mtime": datetime.fromtimestamp(st.st_mtime).astimezone().isoformat(timespec="seconds"),
    }
    if p.is_file() and st.st_size <= MAX_READ * 5:
        out["sha256"] = sha256_file(p)
    return out


def read_text(path: str, encoding: str = "utf-8", start_line: int = 1, end_line: int | None = None) -> Dict[str, Any]:
    p = resolve(path)
    guard_secret(p)
    if not p.is_file():
        raise ValueError("Path bukan file.")
    if p.stat().st_size > MAX_READ:
        raise ValueError("File terlalu besar untuk dibaca.")
    lines = p.read_text(encoding=encoding).splitlines()
    start = max(1, int(start_line))
    end = len(lines) if end_line is None else min(len(lines), int(end_line))
    return {
        "path": path,
        "encoding": encoding,
        "start_line": start,
        "end_line": end,
        "text": "\n".join(lines[start - 1:end]),
    }


def read_bytes_b64(path: str) -> Dict[str, Any]:
    p = resolve(path)
    guard_secret(p)
    if not p.is_file():
        raise ValueError("Path bukan file.")
    if p.stat().st_size > MAX_READ:
        raise ValueError("File terlalu besar untuk dibaca sebagai Base64.")
    data = p.read_bytes()
    return {"path": path, "bytes": len(data), "content_b64": base64.b64encode(data).decode("ascii")}


def search(query: str, path: str = ".", glob: str = "*", case_sensitive: bool = False, max_results: int = 200) -> Dict[str, Any]:
    base = resolve(path)
    needle = query if case_sensitive else query.lower()
    results: List[Dict[str, Any]] = []
    for p in base.rglob("*"):
        p = resolve(str(p))
        if len(results) >= max_results:
            break
        if not p.is_file() or not fnmatch.fnmatch(p.name, glob):
            continue
        if p.name.lower() in SECRET_NAMES:
            continue
        try:
            if p.stat().st_size > MAX_READ:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for idx, line in enumerate(text.splitlines(), start=1):
            hay = line if case_sensitive else line.lower()
            if needle in hay:
                results.append({"path": rel(p), "line": idx, "text": line[:1000]})
                if len(results) >= max_results:
                    break
    return {"query": query, "results": results, "truncated": len(results) >= max_results}


def hash_file(path: str, algorithm: str = "sha256") -> Dict[str, Any]:
    p = resolve(path)
    guard_secret(p)
    if not p.is_file():
        raise ValueError("Path bukan file.")
    return {"path": path, "algorithm": algorithm, "hash": sha256_file(p, algorithm)}


def diff(path_a: str, path_b: str, context: int = 3, encoding: str = "utf-8") -> Dict[str, Any]:
    a = resolve(path_a)
    b = resolve(path_b)
    guard_secret(a)
    guard_secret(b)
    ta = a.read_text(encoding=encoding).splitlines(keepends=True)
    tb = b.read_text(encoding=encoding).splitlines(keepends=True)
    data = "".join(difflib.unified_diff(ta, tb, fromfile=path_a, tofile=path_b, n=int(context)))
    return {"path_a": path_a, "path_b": path_b, "diff": data}


def write(path: str, content: str, encoding: str = "utf-8", expected_sha256: str | None = None, create_parents: bool = True) -> Dict[str, Any]:
    require_write()
    p = resolve(path)
    guard_secret(p)
    raw = content.encode(encoding)
    if len(raw) > MAX_WRITE:
        raise ValueError("Konten terlalu besar.")
    if expected_sha256 and not p.exists():
        raise ValueError("SHA-256 target no longer exists")
    if p.exists() and expected_sha256:
        current = sha256_file(p)
        if current.lower() != expected_sha256.lower():
            raise ValueError("SHA-256 target berubah; write dibatalkan.")
    backup_id = backup_before_overwrite(p, "pre_write")
    if create_parents:
        p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, p)
    return {"path": rel(p), "bytes": len(raw), "sha256": sha256_bytes(raw), "backup_id": backup_id}


def append(path: str, content: str, encoding: str = "utf-8") -> Dict[str, Any]:
    require_write()
    p = resolve(path)
    guard_secret(p)
    backup_id = backup_before_overwrite(p, "pre_append")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding=encoding, newline="") as f:
        f.write(content)
    return {"path": rel(p), "sha256": sha256_file(p), "backup_id": backup_id}


def patch(path: str, old_text: str, new_text: str, count: int = 1, encoding: str = "utf-8", expected_sha256: str | None = None) -> Dict[str, Any]:
    require_write()
    p = resolve(path)
    guard_secret(p)
    if expected_sha256 and sha256_file(p).lower() != expected_sha256.lower():
        raise ValueError("SHA-256 target berubah; patch dibatalkan.")
    text = p.read_text(encoding=encoding)
    occurrences = text.count(old_text)
    if occurrences < count:
        raise ValueError(f"Old text hanya ditemukan {occurrences} kali; butuh {count}.")
    backup_id = backup(p, reason="pre_patch")["backup_id"]
    new_content = text.replace(old_text, new_text, int(count))
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(new_content, encoding=encoding)
    os.replace(tmp, p)
    return {"path": rel(p), "replacements": int(count), "sha256": sha256_file(p), "backup_id": backup_id}


def mkdir(path: str, parents: bool = True, exist_ok: bool = True) -> Dict[str, Any]:
    require_write()
    p = resolve(path)
    p.mkdir(parents=parents, exist_ok=exist_ok)
    return {"ok": True, "path": rel(p)}


def _remove(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def copy(src: str, dst: str, overwrite: bool = False) -> Dict[str, Any]:
    require_write()
    s = resolve(src)
    d = resolve(dst)
    if not s.exists():
        raise FileNotFoundError(str(s))
    backup_id = None
    if d.exists():
        if not overwrite:
            raise FileExistsError(str(d))
        backup_id = backup(d, reason="pre_copy_overwrite")["backup_id"]
        _remove(d)
    d.parent.mkdir(parents=True, exist_ok=True)
    if s.is_dir():
        shutil.copytree(s, d)
    else:
        shutil.copy2(s, d)
    return {"src": rel(s), "dst": rel(d), "backup_id": backup_id}


def move(src: str, dst: str, overwrite: bool = False) -> Dict[str, Any]:
    require_write()
    s = resolve(src)
    d = resolve(dst)
    guard_root_delete(s)
    if not s.exists():
        raise FileNotFoundError(str(s))
    source_backup = backup(s, reason="pre_move")["backup_id"]
    overwrite_backup = None
    if d.exists():
        if not overwrite:
            raise FileExistsError(str(d))
        overwrite_backup = backup(d, reason="pre_move_overwrite")["backup_id"]
        _remove(d)
    d.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s), str(d))
    return {"src": src, "dst": dst, "source_backup_id": source_backup, "overwrite_backup_id": overwrite_backup}


def delete(path: str) -> Dict[str, Any]:
    require_write()
    p = resolve(path)
    guard_root_delete(p)
    if not p.exists():
        raise FileNotFoundError(str(p))
    backup_id = backup(p, reason="pre_delete")["backup_id"]
    _remove(p)
    return {"deleted": path, "backup_id": backup_id, "recoverable": True}


def zip_create(source: str, zip_path: str, overwrite: bool = False) -> Dict[str, Any]:
    require_write()
    src = resolve(source)
    dst = resolve(zip_path)
    if dst.exists():
        if not overwrite:
            raise FileExistsError(str(dst))
        backup(dst, reason="pre_zip_overwrite")
        dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        if src.is_dir():
            for p in src.rglob("*"):
                if p.is_file():
                    z.write(p, arcname=str(p.relative_to(src.parent)))
        else:
            z.write(src, arcname=src.name)
    return {"source": source, "zip_path": zip_path, "bytes": dst.stat().st_size}


def unzip_safe(zip_path: str, dest_dir: str, overwrite: bool = False) -> Dict[str, Any]:
    require_write()
    zp = resolve(zip_path)
    dest = resolve(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    extracted: List[str] = []
    backup_ids: List[str] = []
    with zipfile.ZipFile(zp, "r") as z:
        for member in z.infolist():
            target = (dest / member.filename).resolve()
            try:
                target.relative_to(dest)
            except ValueError:
                raise ValueError(f"ZIP entry tidak aman: {member.filename}")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            guard_secret(target)
            if target.exists():
                if not overwrite:
                    raise FileExistsError(str(target))
                backup_ids.append(backup(target, reason="pre_unzip_overwrite")["backup_id"])
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(member, "r") as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)
            extracted.append(str(target.relative_to(root())))
    return {"zip_path": zip_path, "dest_dir": dest_dir, "files": extracted, "backup_ids": backup_ids}


def syntax_check(path: str) -> Dict[str, Any]:
    p = resolve(path)
    guard_secret(p)
    suffix = p.suffix.lower()
    text = p.read_text(encoding="utf-8")
    try:
        if suffix == ".py":
            ast.parse(text, filename=str(p))
            kind = "py"
        elif suffix == ".json":
            json.loads(text)
            kind = "json"
        elif suffix == ".toml":
            import tomllib
            tomllib.loads(text)
            kind = "toml"
        else:
            kind = "text"
        return {"path": path, "ok": True, "kind": kind}
    except Exception as exc:
        return {"path": path, "ok": False, "kind": suffix.lstrip(".") or "text", "error": str(exc)}


def cross_profile_capabilities() -> Dict[str, Any]:
    rows = []
    for p in list_profiles():
        rows.append({
            "name": p.get("name"),
            "root": p.get("root"),
            "mode": p.get("mode"),
            "active": p.get("active", False),
            "allowed_as_source": bool(p.get("enabled", True)),
            "allowed_as_destination": p.get("mode") == "read-write" and bool(p.get("enabled", True)),
        })
    return {
        "ok": True,
        "feature": "cross-profile-copy",
        "source_read_only_supported": True,
        "destination_must_be_read_write": True,
        "supports_files": True,
        "supports_directories": True,
        "overwrite_backup": True,
        "verification": "SHA-256 manifest",
        "profiles": rows,
    }


def _manifest(path: Path) -> Dict[str, str]:
    if path.is_file():
        return {path.name: sha256_file(path)}
    out: Dict[str, str] = {}
    for p in sorted(path.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(path))] = sha256_file(p)
    return out


def copy_between_profiles(source_profile: str, source_path: str, destination_profile: str, destination_path: str, overwrite: bool = False, verify: bool = True) -> Dict[str, Any]:
    sp = get_profile(source_profile)
    dp = get_profile(destination_profile)
    if not sp.get("enabled", True) or not dp.get("enabled", True):
        raise PermissionError("Profile dinonaktifkan.")
    if dp.get("mode") != "read-write":
        raise PermissionError("Destination profile harus read-write.")
    src = resolve(source_path, sp)
    dst = resolve(destination_path, dp)
    if not src.exists():
        raise FileNotFoundError(str(src))
    overwrite_backup = None
    if dst.exists():
        if not overwrite:
            raise FileExistsError(str(dst))
        # backup uses current profile semantics; create manual cross backup here
        stamp = _backup_id()
        bd = BACKUP_ROOT / stamp
        bd.mkdir(parents=True)
        payload = bd / "payload"
        if dst.is_dir():
            shutil.copytree(dst, payload)
        else:
            shutil.copy2(dst, payload)
        meta = {
            "backup_id": stamp,
            "profile": destination_profile,
            "root": dp["root"],
            "original_path": str(dst),
            "relative_path": str(dst.relative_to(_profile_root(dp))),
            "kind": "dir" if dst.is_dir() else "file",
            "reason": "pre_cross_profile_overwrite",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        (bd / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        overwrite_backup = stamp
        _remove(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    verified = True
    source_manifest = destination_manifest = None
    if verify:
        source_manifest = _manifest(src)
        destination_manifest = _manifest(dst)
        verified = source_manifest == destination_manifest
        if not verified:
            raise IOError("Cross-profile verification gagal.")
    return {
        "ok": True,
        "source_profile": source_profile,
        "source_path": source_path,
        "destination_profile": destination_profile,
        "destination_path": destination_path,
        "overwrite_backup_id": overwrite_backup,
        "verified": verified,
        "source_manifest": source_manifest,
        "destination_manifest": destination_manifest,
    }
