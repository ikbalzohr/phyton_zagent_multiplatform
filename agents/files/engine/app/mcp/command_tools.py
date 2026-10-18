from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app.paths import CONFIG_DIR, LOG_DIR, RUNTIME_DIR
PROFILES_FILE = CONFIG_DIR / "profiles.json"
POLICY_FILE = CONFIG_DIR / "command_policy.json"
AUDIT_LOG = LOG_DIR / "command_audit.jsonl"
PROC_DIR = RUNTIME_DIR / "managed_processes"
PROC_REGISTRY = PROC_DIR / "registry.json"

_REGISTERED = False
_RUNNING_COMMANDS: dict[str, asyncio.subprocess.Process] = {}
_RUNNING_META: dict[str, dict[str, Any]] = {}

DEFAULT_POLICY = {
    "allowed_executables": [
        "node", "node.exe", "npm", "npm.cmd", "npx", "npx.cmd",
        "git", "git.exe", "python", "python.exe", "py", "py.exe",
        "powershell", "powershell.exe", "pwsh", "pwsh.exe",
        "cmd", "cmd.exe"
    ],
    "deny_powershell_patterns": [
        r"(?i)\bset-executionpolicy\b",
        r"(?i)\badd-mppreference\b",
        r"(?i)\bset-mppreference\b",
        r"(?i)\bnew-localuser\b",
        r"(?i)\bremove-localuser\b",
        r"(?i)\bnet\s+user\b",
        r"(?i)\breg(\.exe)?\s+(add|delete)\b",
        r"(?i)\bsc(\.exe)?\s+(create|delete|config)\b",
        r"(?i)\bschtasks(\.exe)?\s+/(create|delete|change)\b",
        r"(?i)\bformat(\.com)?\b",
        r"(?i)\bdiskpart\b",
        r"(?i)\bbcdedit\b"
    ],
    "max_timeout_seconds": 1800,
    "max_output_chars": 200000,
    "allow_unmanaged_process_stop": True
}


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_policy() -> dict[str, Any]:
    data = dict(DEFAULT_POLICY)
    try:
        if POLICY_FILE.exists():
            custom = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
            if isinstance(custom, dict):
                data.update(custom)
    except Exception:
        pass
    return data


def _load_profiles() -> dict[str, dict[str, Any]]:
    raw = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
    return {str(p["name"]): p for p in raw.get("profiles", [])}


def _profile_root(profile: str) -> Path:
    profiles = _load_profiles()
    p = profiles.get(profile)
    if not p:
        raise ValueError(f"Unknown profile: {profile}")
    if not p.get("enabled", True):
        raise PermissionError(f"Profile disabled: {profile}")
    if not p.get("authorized_by_user", False):
        raise PermissionError(f"Profile not authorized by user: {profile}")
    return Path(p["root"]).resolve()


def _resolve_cwd(profile: str, cwd: str | None) -> Path:
    root = _profile_root(profile)
    candidate = root if not cwd or cwd in {".", ""} else (root / cwd).resolve()
    root_norm = os.path.normcase(str(root))
    cand_norm = os.path.normcase(str(candidate))
    try:
        common = os.path.commonpath([root_norm, cand_norm])
    except ValueError as exc:
        raise PermissionError("Working directory is outside the authorized profile") from exc
    if common != root_norm:
        raise PermissionError("Working directory is outside the authorized profile")
    if not candidate.exists():
        raise FileNotFoundError(str(candidate))
    if not candidate.is_dir():
        raise NotADirectoryError(str(candidate))
    return candidate


def _audit(event: dict[str, Any]) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    payload = {"time": _now(), **event}
    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _meta_fields(metadata: dict[str, Any] | None) -> dict[str, Any]:
    metadata = metadata or {}
    return {
        "session_id": metadata.get("session_id"),
        "request_id": metadata.get("request_id"),
        "task_id": metadata.get("task_id"),
        "trace_id": metadata.get("trace_id"),
        "idempotency_key": metadata.get("idempotency_key"),
    }


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[:limit] + "\n...[truncated]...", True


def _allowed_executable(executable: str) -> str:
    policy = _load_policy()
    requested = str(executable).strip()
    if not requested:
        raise ValueError("Executable is required")
    base = os.path.basename(requested).lower()
    allowed = {str(x).lower() for x in policy.get("allowed_executables", [])}
    resolved = shutil.which(requested) or requested
    resolved_base = os.path.basename(resolved).lower()
    if base not in allowed and resolved_base not in allowed:
        raise PermissionError(f"Executable is not allowed: {executable}")
    return resolved


def _validate_script(script: str) -> None:
    for pattern in _load_policy().get("deny_powershell_patterns", []):
        if re.search(pattern, script or ""):
            raise PermissionError(f"PowerShell policy denied pattern: {pattern}")


def _windows_batch_wrap(executable: str, args: list[str]) -> tuple[str, list[str]]:
    lower = executable.lower()
    if os.name == "nt" and lower.endswith((".cmd", ".bat")):
        cmd = shutil.which("cmd.exe") or "cmd.exe"
        return cmd, ["/d", "/s", "/c", executable, *args]
    return executable, args



async def _terminate_process_tree(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    if os.name == "nt":
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/PID", str(proc.pid), "/T", "/F",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_hidden_subprocess_kwargs(),
        )
        await killer.communicate()
    else:
        try:
            proc.kill()
        except ProcessLookupError:
            return
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except Exception:
        pass


def _hidden_subprocess_kwargs() -> dict[str, Any]:
    """Hide transient console windows for background subprocesses on Windows."""
    if os.name != "nt":
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0x00000001)
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
    return {
        "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        "startupinfo": startupinfo,
    }


async def _run(
    executable: str,
    args: list[str],
    profile: str,
    cwd: str | None,
    timeout_seconds: int,
    metadata: dict[str, Any] | None,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = _profile_root(profile)
    workdir = _resolve_cwd(profile, cwd)
    exe = _allowed_executable(executable)
    exe, argv = _windows_batch_wrap(exe, [str(a) for a in args])
    policy = _load_policy()
    timeout = max(1, min(int(timeout_seconds), int(policy.get("max_timeout_seconds", 1800))))
    started = time.monotonic()
    audit_base = {
        "action": "exec",
        "profile": profile,
        "root": str(root),
        "cwd": str(workdir),
        "executable": exe,
        "args": argv,
        **_meta_fields(metadata),
    }
    _audit({**audit_base, "state": "started"})

    process_env = {**os.environ, **(env or {})}
    metadata = metadata or {}
    if metadata.get("session_id"):
        process_env["ZAGENT_SESSION_ID"] = str(metadata.get("session_id"))
    if metadata.get("request_id"):
        process_env["ZAGENT_REQUEST_ID"] = str(metadata.get("request_id"))
    if metadata.get("task_id"):
        process_env["ZAGENT_TASK_ID"] = str(metadata.get("task_id"))
    if metadata.get("trace_id"):
        process_env["ZAGENT_TRACE_ID"] = str(metadata.get("trace_id"))

    proc = await asyncio.create_subprocess_exec(
        exe,
        *argv,
        cwd=str(workdir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=process_env,
        **_hidden_subprocess_kwargs(),
    )
    task_id = str((metadata or {}).get("task_id") or "")
    if task_id:
        _RUNNING_COMMANDS[task_id] = proc
        _RUNNING_META[task_id] = {
            "task_id": task_id,
            "session_id": str((metadata or {}).get("session_id") or ""),
            "pid": proc.pid,
            "profile": profile,
            "cwd": str(workdir),
            "executable": exe,
            "started_at": _now(),
        }
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        await _terminate_process_tree(proc)
        if task_id:
            _RUNNING_COMMANDS.pop(task_id, None)
            _RUNNING_META.pop(task_id, None)
        _audit({**audit_base, "state": "timeout", "pid": proc.pid, "timeout_seconds": timeout})
        raise TimeoutError(f"Command timed out after {timeout}s")
    except asyncio.CancelledError:
        await _terminate_process_tree(proc)
        if task_id:
            _RUNNING_COMMANDS.pop(task_id, None)
            _RUNNING_META.pop(task_id, None)
        _audit({**audit_base, "state": "cancelled", "pid": proc.pid})
        raise

    if task_id:
        _RUNNING_COMMANDS.pop(task_id, None)
        _RUNNING_META.pop(task_id, None)

    enc = "utf-8"
    stdout = stdout_b.decode(enc, errors="replace")
    stderr = stderr_b.decode(enc, errors="replace")
    limit = int(policy.get("max_output_chars", 200000))
    stdout, trunc_out = _truncate(stdout, limit)
    stderr, trunc_err = _truncate(stderr, limit)
    duration_ms = round((time.monotonic() - started) * 1000, 3)
    result = {
        "ok": proc.returncode == 0,
        "exit_code": proc.returncode,
        "pid": proc.pid,
        "stdout": stdout,
        "stderr": stderr,
        "stdout_truncated": trunc_out,
        "stderr_truncated": trunc_err,
        "duration_ms": duration_ms,
        "profile": profile,
        "cwd": str(workdir),
        "_meta": {
            **{f"zagent.{k}": v for k, v in _meta_fields(metadata).items() if v is not None},
            "zagent.command_layer": "3.1.3",
        },
    }
    _audit({**audit_base, "state": "finished", "pid": proc.pid, "exit_code": proc.returncode, "duration_ms": duration_ms})
    return result


def _read_registry() -> dict[str, Any]:
    try:
        return json.loads(PROC_REGISTRY.read_text(encoding="utf-8"))
    except Exception:
        return {"processes": {}}


def _write_registry(data: dict[str, Any]) -> None:
    PROC_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PROC_REGISTRY.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(PROC_REGISTRY)


def _powershell_exe() -> str:
    return shutil.which("powershell.exe") or shutil.which("powershell") or shutil.which("pwsh.exe") or shutil.which("pwsh") or "powershell.exe"


async def _process_info(pid: int) -> dict[str, Any] | None:
    ps = _powershell_exe()
    script = (
        "$p=Get-CimInstance Win32_Process -Filter \\\"ProcessId=%d\\\" -ErrorAction SilentlyContinue;"
        "if($p){$p|Select-Object ProcessId,Name,ExecutablePath,CommandLine|ConvertTo-Json -Compress}"
    ) % int(pid)
    proc = await asyncio.create_subprocess_exec(
        ps, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        **_hidden_subprocess_kwargs(),
    )
    out, _ = await proc.communicate()
    text = out.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return {"raw": text, "ProcessId": int(pid)}


def register_command_tools(mcp) -> None:
    global _REGISTERED
    if _REGISTERED:
        return
    _REGISTERED = True

    @mcp.tool()
    def files_command_capabilities() -> dict:
        policy = _load_policy()
        return {
            "service": "Zagent Files",
            "command_layer_version": "3.1.3",
            "self_update": True,
            "profile_scoped_working_directory": True,
            "audit_log": str(AUDIT_LOG),
            "supports": [
                "powershell_run", "exec_command", "command_cancel", "process_list", "process_start", "process_stop",
                "node", "npm", "npx", "git", "build", "test"
            ],
            "allowed_executables": policy.get("allowed_executables", []),
            "max_timeout_seconds": policy.get("max_timeout_seconds", 1800),
        }

    @mcp.tool()
    async def files_command_cancel(
        task_id: str,
        session_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        task_id = str(task_id or "").strip()
        session_id = str(session_id or "").strip()
        if not task_id:
            raise ValueError("task_id is required")
        proc = _RUNNING_COMMANDS.get(task_id)
        meta = _RUNNING_META.get(task_id) or {}
        if session_id and meta.get("session_id") and session_id != str(meta.get("session_id")):
            raise PermissionError("session_id does not own this running command")
        if proc is None or proc.returncode is not None:
            _RUNNING_COMMANDS.pop(task_id, None)
            _RUNNING_META.pop(task_id, None)
            return {
                "ok": True,
                "task_id": task_id,
                "already_stopped": True,
                "state": "not_running",
            }
        pid = proc.pid
        await _terminate_process_tree(proc)
        _RUNNING_COMMANDS.pop(task_id, None)
        _RUNNING_META.pop(task_id, None)
        _audit({
            "action": "command_cancel",
            "state": "cancelled",
            "pid": pid,
            "task_id": task_id,
            "session_id": session_id or meta.get("session_id"),
            **_meta_fields(metadata),
        })
        return {
            "ok": True,
            "task_id": task_id,
            "pid": pid,
            "state": "cancelled",
            "process_tree_terminated": True,
        }

    @mcp.tool()
    async def files_exec_command(
        executable: str,
        args: list[str],
        profile: str,
        cwd: str = ".",
        timeout_seconds: int = 120,
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        return await _run(executable, args or [], profile, cwd, timeout_seconds, metadata)

    @mcp.tool()
    async def files_powershell_run(
        script: str,
        profile: str,
        cwd: str = ".",
        timeout_seconds: int = 120,
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        _validate_script(script)
        return await _run(
            _powershell_exe(),
            ["-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-ExecutionPolicy", "Bypass", "-Command", script],
            profile, cwd, timeout_seconds, metadata
        )

    @mcp.tool()
    async def files_node(
        args: list[str],
        profile: str,
        cwd: str = ".",
        timeout_seconds: int = 120,
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        return await _run("node", args or [], profile, cwd, timeout_seconds, metadata)

    @mcp.tool()
    async def files_npm(
        args: list[str],
        profile: str,
        cwd: str = ".",
        timeout_seconds: int = 600,
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        return await _run("npm", args or [], profile, cwd, timeout_seconds, metadata)

    @mcp.tool()
    async def files_npx(
        args: list[str],
        profile: str,
        cwd: str = ".",
        timeout_seconds: int = 600,
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        return await _run("npx", args or [], profile, cwd, timeout_seconds, metadata)

    @mcp.tool()
    async def files_git(
        args: list[str],
        profile: str,
        cwd: str = ".",
        timeout_seconds: int = 300,
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        return await _run("git", args or [], profile, cwd, timeout_seconds, metadata)

    @mcp.tool()
    async def files_build(
        profile: str,
        cwd: str = ".",
        script: str = "build",
        timeout_seconds: int = 1200,
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        return await _run("npm", ["run", script], profile, cwd, timeout_seconds, metadata)

    @mcp.tool()
    async def files_test(
        profile: str,
        cwd: str = ".",
        script: str = "test",
        timeout_seconds: int = 1200,
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        return await _run("npm", ["run", script], profile, cwd, timeout_seconds, metadata)

    @mcp.tool()
    async def files_process_list(
        name_filter: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        ps = _powershell_exe()
        safe_filter = (name_filter or "").replace("'", "''")
        where = f"| Where-Object {{$_.Name -like '*{safe_filter}*'}}" if safe_filter else ""
        script = (
            "$p=Get-CimInstance Win32_Process "
            + where +
            " | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath,CommandLine;"
            "$p|ConvertTo-Json -Compress"
        )
        proc = await asyncio.create_subprocess_exec(
            ps, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            **_hidden_subprocess_kwargs(),
        )
        out, err = await proc.communicate()
        raw = out.decode("utf-8", errors="replace").strip()
        data: Any = []
        if raw:
            try:
                data = json.loads(raw)
            except Exception:
                data = raw
        _audit({"action":"process_list","filter":name_filter,**_meta_fields(metadata),"exit_code":proc.returncode})
        return {"ok":proc.returncode == 0,"processes":data,"stderr":err.decode("utf-8",errors="replace")}

    @mcp.tool()
    async def files_process_start(
        executable: str,
        args: list[str],
        profile: str,
        cwd: str = ".",
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        workdir = _resolve_cwd(profile, cwd)
        exe = _allowed_executable(executable)
        exe, argv = _windows_batch_wrap(exe, [str(a) for a in (args or [])])
        PROC_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out_path = PROC_DIR / f"{stamp}.stdout.log"
        err_path = PROC_DIR / f"{stamp}.stderr.log"
        out_f = out_path.open("ab")
        err_f = err_path.open("ab")
        hidden_kwargs = _hidden_subprocess_kwargs()
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | int(hidden_kwargs.pop("creationflags", 0) or 0)
        proc = subprocess.Popen(
            [exe, *argv],
            cwd=str(workdir),
            stdin=subprocess.DEVNULL,
            stdout=out_f,
            stderr=err_f,
            creationflags=flags,
            close_fds=True,
            **hidden_kwargs,
        )
        out_f.close()
        err_f.close()
        reg = _read_registry()
        reg.setdefault("processes", {})[str(proc.pid)] = {
            "pid": proc.pid,
            "executable": exe,
            "args": argv,
            "profile": profile,
            "cwd": str(workdir),
            "started_at": _now(),
            "stdout_log": str(out_path),
            "stderr_log": str(err_path),
            **_meta_fields(metadata),
        }
        _write_registry(reg)
        _audit({"action":"process_start","pid":proc.pid,"executable":exe,"args":argv,"profile":profile,"cwd":str(workdir),**_meta_fields(metadata)})
        return {"ok":True,"pid":proc.pid,"stdout_log":str(out_path),"stderr_log":str(err_path)}

    @mcp.tool()
    async def files_process_stop(
        pid: int,
        force: bool = False,
        confirm_unmanaged: bool = False,
        expected_name: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict:
        pid = int(pid)
        reg = _read_registry()
        managed = reg.get("processes", {}).get(str(pid))
        info = await _process_info(pid)
        if info is None and managed:
            # A newly spawned process can take a short moment to become
            # visible through Win32_Process/CIM. Do not misclassify a
            # managed PID as already stopped on the first lookup.
            for delay in (0.05, 0.15, 0.30):
                await asyncio.sleep(delay)
                info = await _process_info(pid)
                if info is not None:
                    break
        if info is None:
            if managed:
                reg.get("processes", {}).pop(str(pid), None)
                _write_registry(reg)
            return {"ok":True,"pid":pid,"already_stopped":True,"managed":bool(managed)}
        actual_name = str(info.get("Name") or info.get("name") or "")
        if expected_name and expected_name.lower() not in actual_name.lower():
            raise PermissionError(f"PID {pid} is '{actual_name}', expected '{expected_name}'")
        if not managed and not confirm_unmanaged:
            raise PermissionError("PID is not managed by Zagent Files. Set confirm_unmanaged=true after verifying process_list output.")
        if not managed and not _load_policy().get("allow_unmanaged_process_stop", True):
            raise PermissionError("Stopping unmanaged processes is disabled by policy")
        args = ["taskkill", "/PID", str(pid), "/T"]
        if force:
            args.append("/F")
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            **_hidden_subprocess_kwargs(),
        )
        out, err = await proc.communicate()
        reg.get("processes", {}).pop(str(pid), None)
        _write_registry(reg)
        _audit({"action":"process_stop","pid":pid,"force":force,"managed":bool(managed),"name":actual_name,**_meta_fields(metadata),"exit_code":proc.returncode})
        return {
            "ok": proc.returncode == 0,
            "pid": pid,
            "managed": bool(managed),
            "name": actual_name,
            "stdout": out.decode("utf-8", errors="replace"),
            "stderr": err.decode("utf-8", errors="replace"),
            "exit_code": proc.returncode,
        }

