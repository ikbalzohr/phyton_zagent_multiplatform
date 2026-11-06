from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from app.core import fsops, project_instructions
from app.profiles.manager import (
    active_profile,
    default_profile,
    get_profile,
    get_request,
    list_profiles,
    list_requests,
    request_add,
    request_delete,
    request_update,
)

from app.paths import CONFIG_DIR
SETTINGS = json.loads((CONFIG_DIR / "settings.json").read_text(encoding="utf-8"))
HOST = SETTINGS.get("host", "127.0.0.1")
PORT = int(SETTINGS.get("port", 8011))




def _json(data):
    return json.dumps(data, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Health / profile
# ---------------------------------------------------------------------------

def files_ping() -> str:
    p = active_profile()
    return _json({
        "ok": True,
        "service": "Zagent Files",
        "version": "1.0.0",
        "profile": p["name"],
        "root": p["root"],
        "mode": p["mode"],
        "profile_hot_reload": True,
    })


def files_runtime_info() -> str:
    p = active_profile()
    return _json({
        "service": "Zagent Files",
        "version": "1.0.0",
        "python": sys.version,
        "platform": platform.platform(),
        "profile": p["name"],
        "root": p["root"],
        "mode": p["mode"],
        "max_read_bytes": fsops.MAX_READ,
        "max_write_bytes": fsops.MAX_WRITE,
        "protect_secret_names": True,
        "mcp_url": f"http://{HOST}:{PORT}/mcp",
        "profile_hot_reload": True,
        "profile_reload_strategy": "read profiles.json on every profile/filesystem request",
    })


def files_profile_list() -> str:
    return _json(list_profiles())


def files_profile_get() -> str:
    return _json(active_profile())


def files_profile_default_get() -> str:
    """Return the global default profile used only to seed new sessions."""
    return _json(default_profile())


def files_profile_reload() -> str:
    p = active_profile()
    return _json({
        "ok": True,
        "restarted": False,
        "hot_reload": True,
        "active_profile": p,
        "profiles": list_profiles(),
    })


def files_profile_switch(name: str) -> str:
    """Session switching is owned by Engine; this function only validates the target."""
    old = active_profile()
    new = get_profile(name)
    if not new.get("enabled", True):
        raise ValueError("Profile dinonaktifkan.")
    if not new.get("authorized_by_user"):
        raise PermissionError("Profile belum disetujui.")
    return _json({
        "old_profile": old.get("name"),
        "active_profile": new.get("name"),
        "root": new.get("root"),
        "mode": new.get("mode"),
        "scope": "session",
    })


# v2 approval-request profile management

def files_profile_request_add(name: str, root: str, mode: str = "read-only", description: str = "") -> str:
    return _json(request_add(name, root, mode, description, requested_by="chatgpt"))


def files_profile_request_update(
    name: str,
    root: str | None = None,
    mode: str | None = None,
    description: str | None = None,
    enabled: bool | None = None,
) -> str:
    return _json(request_update(
        name,
        root=root,
        mode=mode,
        description=description,
        enabled=enabled,
        requested_by="chatgpt",
    ))


def files_profile_request_delete(name: str) -> str:
    return _json(request_delete(name, requested_by="chatgpt"))


def files_profile_pending_list() -> str:
    return _json(list_requests("pending_user_approval"))


def files_profile_request_status(request_id: str) -> str:
    return _json(get_request(request_id))


# ---------------------------------------------------------------------------
# Filesystem parity with v1
# ---------------------------------------------------------------------------

def files_get_root() -> str:
    p = active_profile()
    return _json({"profile": p["name"], "root": p["root"], "mode": p["mode"]})


def files_exists(path: str) -> str:
    p = fsops.resolve(path)
    return _json({"path": path, "exists": p.exists()})


def files_list(path: str = ".", include_hidden: bool = True, limit: int = 500) -> str:
    p = fsops.resolve(path)
    if not p.is_dir():
        raise ValueError("Path bukan folder.")
    items = []
    for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        if not include_hidden and child.name.startswith("."):
            continue
        items.append({
            "name": child.name,
            "type": "dir" if child.is_dir() else "file",
            "path": fsops.rel(child),
        })
        if len(items) >= int(limit):
            break
    return _json(items)


def files_tree(path: str = ".", max_depth: int = 4, max_items: int = 1000) -> str:
    return _json(fsops.file_tree(path, max_depth, max_items))


def files_stat(path: str) -> str:
    return _json(fsops.stat(path))


def files_read(path: str, encoding: str = "utf-8", start_line: int = 1, end_line: int | None = None) -> str:
    return _json(fsops.read_text(path, encoding, start_line, end_line))


def files_read_bytes_b64(path: str) -> str:
    return _json(fsops.read_bytes_b64(path))


def files_search(
    query: str,
    path: str = ".",
    glob: str = "*",
    case_sensitive: bool = False,
    max_results: int = 200,
) -> str:
    return _json(fsops.search(query, path, glob, case_sensitive, max_results))


def files_project_instructions(path: str, allow_unmarked: bool = False) -> str:
    """Read current project-local ZAGENT.md; never writes on a read grant."""
    return _json(project_instructions.instructions(path, allow_unmarked))


def files_project_open(path: str, allow_unmarked: bool = False) -> str:
    """Open a project and exclusively create ZAGENT.md if missing and write-authorized."""
    return _json(project_instructions.open_project(path, allow_unmarked))


def files_hash(path: str, algorithm: str = "sha256") -> str:
    return _json(fsops.hash_file(path, algorithm))


def files_diff(path_a: str, path_b: str, context: int = 3, encoding: str = "utf-8") -> str:
    return _json(fsops.diff(path_a, path_b, context, encoding))


def files_write(
    path: str,
    content: str,
    encoding: str = "utf-8",
    expected_sha256: str | None = None,
    create_parents: bool = True,
) -> str:
    return _json(fsops.write(path, content, encoding, expected_sha256, create_parents))


def files_append(path: str, content: str, encoding: str = "utf-8") -> str:
    return _json(fsops.append(path, content, encoding))


def files_patch(
    path: str,
    old_text: str,
    new_text: str,
    count: int = 1,
    encoding: str = "utf-8",
    expected_sha256: str | None = None,
) -> str:
    return _json(fsops.patch(path, old_text, new_text, count, encoding, expected_sha256))


def files_mkdir(path: str, parents: bool = True, exist_ok: bool = True) -> str:
    return _json(fsops.mkdir(path, parents, exist_ok))


def files_copy(src: str, dst: str, overwrite: bool = False) -> str:
    return _json(fsops.copy(src, dst, overwrite))


def files_move(src: str, dst: str, overwrite: bool = False) -> str:
    return _json(fsops.move(src, dst, overwrite))


def files_delete(path: str) -> str:
    return _json(fsops.delete(path))


def files_backup(path: str, reason: str = "manual") -> str:
    p = fsops.resolve(path)
    return _json(fsops.backup(p, reason=reason))


def files_backup_list(limit: int = 50) -> str:
    return _json(fsops.backup_list(limit))


def files_restore(backup_id: str, overwrite: bool = True) -> str:
    return _json(fsops.restore_backup(backup_id, overwrite))


def files_zip(source: str, zip_path: str, overwrite: bool = False) -> str:
    return _json(fsops.zip_create(source, zip_path, overwrite))


def files_unzip(zip_path: str, dest_dir: str, overwrite: bool = False) -> str:
    return _json(fsops.unzip_safe(zip_path, dest_dir, overwrite))


def files_syntax_check(path: str) -> str:
    return _json(fsops.syntax_check(path))


def files_cross_profile_capabilities():
    return fsops.cross_profile_capabilities()


def files_copy_between_profiles(
    source_profile: str,
    source_path: str,
    destination_profile: str,
    destination_path: str,
    overwrite: bool = False,
    verify: bool = True,
):
    return fsops.copy_between_profiles(
        source_profile,
        source_path,
        destination_profile,
        destination_path,
        overwrite,
        verify,
    )


# ---------------------------------------------------------------------------
