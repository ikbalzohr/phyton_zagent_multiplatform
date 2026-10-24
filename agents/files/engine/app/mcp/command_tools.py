"""Thin public tool schemas; all authority and execution lives in managed_commands.

No legacy command_policy.json, PATH shell fallback, host inventory or unmanaged
PID termination path is reachable here. Private launcher console helpers remain
for run_mcp.py compatibility; its batch shim is never called by the executor.
"""
from __future__ import annotations
import os
import subprocess
from typing import Any
from app.mcp.managed_commands import COMMAND_TOOL_NAMES, authorize_command_call, execute


def _hidden_subprocess_kwargs() -> dict[str, Any]:
    if os.name != 'nt':
        return {}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = subprocess.SW_HIDE
    return {'creationflags': subprocess.CREATE_NO_WINDOW, 'startupinfo': startupinfo}


def register_command_tools(mcp) -> None:
    @mcp.tool()
    async def files_command_capabilities() -> dict:
        return await execute('files_command_capabilities', {})

    @mcp.tool()
    async def files_exec_command(executable: str, args: list[str], profile: str | None = None,
                                 cwd: str = '.', timeout_seconds: int = 120,
                                 metadata: dict[str, Any] | None = None) -> dict:
        return await execute('files_exec_command', _arguments(locals()))

    @mcp.tool()
    async def files_powershell_run(script: str, profile: str | None = None, cwd: str = '.',
                                   timeout_seconds: int = 120, metadata: dict[str, Any] | None = None) -> dict:
        return await execute('files_powershell_run', _arguments(locals()))

    @mcp.tool()
    async def files_node(args: list[str], profile: str | None = None, cwd: str = '.',
                         timeout_seconds: int = 120, metadata: dict[str, Any] | None = None) -> dict:
        return await execute('files_node', _arguments(locals()))

    @mcp.tool()
    async def files_npm(args: list[str], profile: str | None = None, cwd: str = '.',
                        timeout_seconds: int = 600, metadata: dict[str, Any] | None = None) -> dict:
        return await execute('files_npm', _arguments(locals()))

    @mcp.tool()
    async def files_npx(args: list[str], profile: str | None = None, cwd: str = '.',
                        timeout_seconds: int = 600, metadata: dict[str, Any] | None = None) -> dict:
        return await execute('files_npx', _arguments(locals()))

    @mcp.tool()
    async def files_git(args: list[str], profile: str | None = None, cwd: str = '.',
                        timeout_seconds: int = 300, metadata: dict[str, Any] | None = None) -> dict:
        return await execute('files_git', _arguments(locals()))

    @mcp.tool()
    async def files_build(profile: str | None = None, cwd: str = '.', script: str = 'build',
                          timeout_seconds: int = 1200, metadata: dict[str, Any] | None = None) -> dict:
        return await execute('files_build', _arguments(locals()))

    @mcp.tool()
    async def files_test(profile: str | None = None, cwd: str = '.', script: str = 'test',
                         timeout_seconds: int = 1200, metadata: dict[str, Any] | None = None) -> dict:
        return await execute('files_test', _arguments(locals()))

    @mcp.tool()
    async def files_command_cancel(task_id: str, session_id: str = '', metadata: dict[str, Any] | None = None) -> dict:
        return await execute('files_command_cancel', _arguments(locals()))

    @mcp.tool()
    async def files_process_list(name_filter: str = '', metadata: dict[str, Any] | None = None) -> dict:
        return await execute('files_process_list', _arguments(locals()))

    @mcp.tool()
    async def files_process_start(executable: str, args: list[str], profile: str | None = None,
                                  cwd: str = '.', metadata: dict[str, Any] | None = None) -> dict:
        return await execute('files_process_start', _arguments(locals()))

    @mcp.tool()
    async def files_process_stop(pid: int, force: bool = False, confirm_unmanaged: bool = False,
                                 expected_name: str = '', metadata: dict[str, Any] | None = None) -> dict:
        return await execute('files_process_stop', _arguments(locals()))


def _arguments(values):
    # Missing optional profile derives from the unique bound Files resource.
    return {k: v for k, v in values.items() if k != 'metadata' and not (k == 'profile' and v is None)}
