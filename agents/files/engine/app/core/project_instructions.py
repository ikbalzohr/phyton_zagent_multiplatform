"""Project-local ZAGENT.md context. No global agent memory or policy authority.

All paths are resolved through Files' approved-profile filesystem guard. The
content is lower-trust project data for MCP clients, never an authorization rule.
"""
from __future__ import annotations

import errno
import hashlib
import os
import threading
from pathlib import Path

from app.core import fsops

NAME = "ZAGENT.md"
MAX_BYTES = 32768
_CREATE_LOCK = threading.RLock()
MARKERS = (
    ".git", "pyproject.toml", "requirements.txt", "package.json",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle",
    "build.gradle.kts", "settings.gradle", "settings.gradle.kts",
    "pubspec.yaml", "CMakeLists.txt", "Zagent.slnx",
)


def _directory(path: str) -> Path:
    folder = fsops.resolve(path)
    if not folder.is_dir():
        raise ValueError("PROJECT_ROOT_MUST_BE_AN_EXISTING_DIRECTORY")
    return folder


def _is_project(folder: Path) -> bool:
    for marker in (NAME, *MARKERS):
        candidate = folder / marker
        try:
            fsops.guard_no_links(candidate)
        except PermissionError:
            continue
        if candidate.exists():
            return True
    # An arbitrary solution name is also a trustworthy project marker.
    for pattern in ("*.sln", "*.slnx", "*.csproj"):
        for item in folder.glob(pattern):
            try:
                fsops.guard_no_links(item)
            except PermissionError:
                continue
            return True
    return False


def detect(path: str) -> Path | None:
    """Find nearest recognizable project, not the enclosing Files profile."""
    target = fsops.resolve(path)
    base = fsops.root()
    folder = target if target.is_dir() else target.parent
    while folder == base or base in folder.parents:
        if folder.is_dir() and _is_project(folder):
            if folder != base:
                return folder
            # A Files profile may be a container of many projects. Generic
            # manifests at that level must not silently turn the container
            # into a project. An actual repository or an existing ZAGENT.md
            # can still make the profile root a project in its own right.
            for marker in (folder / ".git", folder / NAME):
                try:
                    fsops.guard_no_links(marker)
                except PermissionError:
                    continue
                if marker.exists():
                    return folder
        if folder == base:
            break
        folder = folder.parent
    return None


def _snapshot(folder: Path, include_content: bool = True) -> dict:
    target = fsops.resolve(str(folder / NAME))
    result = {"project_root": fsops.rel(folder), "file": fsops.rel(target),
              "status": "missing", "created": False}
    if not target.exists():
        return result
    if not target.is_file():
        raise ValueError("PROJECT_INSTRUCTIONS_NOT_A_FILE")
    with _CREATE_LOCK:
        with target.open("rb") as source:
            raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        return {**result, "status": "too_large", "max_bytes": MAX_BYTES}
    text = raw.decode("utf-8", errors="strict")
    result.update(status="available", sha256=hashlib.sha256(raw).hexdigest(),
                  bytes=len(raw))
    if include_content:
        result["content"] = text
    return result


def _can_disclose() -> bool:
    from app.core.execution_context import CURRENT
    ctx = CURRENT.get()
    return ctx is None or "files:read" in ctx.get("scopes", ())


def instructions(path: str, allow_unmarked: bool = False) -> dict:
    folder = _directory(path)
    if not allow_unmarked and not _is_project(folder):
        return {"project_root": fsops.rel(folder), "status": "unrecognized",
                "created": False, "reason": "Specify an existing project root, or allow_unmarked for a new project"}
    return _snapshot(folder, _can_disclose())


def _create(folder: Path) -> bool:
    fsops.require_write()
    target = fsops.resolve(str(folder / NAME))
    if target.exists():
        fsops.guard_no_links(target)
        return False
    # Exclusive create: never overwrite another agent's concurrently created file.
    # The directory must already exist; no implicit project or parent creation.
    title = folder.name.replace("\r", " ").replace("\n", " ")
    template = (
        f"# {title} — Project Instructions\n\n"
        "This file provides project-local guidance to AI agents using Zagent.\n"
        "It does not grant permissions or override platform security policies.\n\n"
        "## Project context\n\n"
        "- Describe the project's purpose, architecture, and technologies here.\n\n"
        "## Working conventions\n\n"
        "- Inspect relevant code and documentation before editing.\n"
        "- Follow existing project patterns and verify changes with relevant tests.\n"
        "- Report test results and any unverified behavior.\n"
        "- Do not commit, push, deploy, or alter runtime configuration without authorization.\n"
    )
    fsops.require_write()
    with _CREATE_LOCK:
        try:
            with target.open("x", encoding="utf-8", newline="\n") as output:
                output.write(template)
                output.flush()
                os.fsync(output.fileno())
            return True
        except FileExistsError:
            return False


def open_project(path: str, allow_unmarked: bool = False) -> dict:
    folder = _directory(path)
    if not allow_unmarked and not _is_project(folder):
        return {"project_root": fsops.rel(folder), "status": "unrecognized",
                "created": False, "reason": "Explicitly allow an unmarked new project root"}
    try:
        created = _create(folder)
    except OSError as exc:
        if exc.errno not in (errno.EACCES, errno.EPERM, errno.EROFS):
            raise
        return {**_snapshot(folder, _can_disclose()),
                "created": False, "creation_skipped": "filesystem_read_only"}
    return {**_snapshot(folder, _can_disclose()), "created": created}


# Never implicitly create instructions for destructive source/target operations.
_AUTO_CREATE = {"write", "append", "patch", "mkdir", "copy"}
_OUTPUT_PATH = {"copy": "dst"}


def for_operation(operation: str, arguments: dict, *, can_create: bool) -> dict | None:
    """Fresh snapshot for every operation, not a long-lived in-memory cache."""
    name = _OUTPUT_PATH.get(operation, "path")
    path = arguments.get(name)
    if not isinstance(path, str) or not path:
        return None
    folder = detect(path)
    if folder is None:
        return None
    target = fsops.resolve(path)
    is_instruction_target = target == fsops.resolve(str(folder / NAME))
    created = False
    skipped = None
    if (can_create and operation in _AUTO_CREATE and not is_instruction_target
            and not (folder / NAME).exists()):
        try:
            created = _create(folder)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EPERM, errno.EROFS):
                raise
            skipped = "filesystem_read_only"
    snapshot = _snapshot(folder, _can_disclose())
    snapshot["created"] = created
    if skipped:
        snapshot["creation_skipped"] = skipped
    return snapshot
