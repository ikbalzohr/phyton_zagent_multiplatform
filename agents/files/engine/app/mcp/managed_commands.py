"""Explicit local opt-in to OWNER ACCOUNT execution, NOT an OS sandbox.

CWD is resource bounded; arbitrary approved interpreters can access everything
that the Windows owner can. No ambient credentials or PATH resolution is used.
"""
from __future__ import annotations

import asyncio
import ctypes
import json
import math
import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.execution_context import VerifiedContext, current
from app.paths import CONFIG_DIR, LOG_DIR

COMMAND_TOOL_NAMES = frozenset({
    'files_command_capabilities', 'files_command_cancel', 'files_exec_command',
    'files_powershell_run', 'files_node', 'files_npm', 'files_npx', 'files_git',
    'files_build', 'files_test', 'files_process_list', 'files_process_start',
    'files_process_stop',
})
POLICY_FILE = CONFIG_DIR / 'remote_execution_policy.json'
UNSUPPORTED_COMMAND_TOOLS = frozenset({'files_process_start'})
SUPPORTED_COMMAND_TOOLS = COMMAND_TOOL_NAMES - UNSUPPORTED_COMMAND_TOOLS
PROFILES_FILE = CONFIG_DIR / 'profiles.json'
AUDIT_LOG = LOG_DIR / 'command_audit.jsonl'
_POLICY_KEYS = frozenset({'version', 'enabled', 'execution_mode', 'acknowledge_host_access',
    'profile_id', 'root', 'allowed_tools', 'allowed_executables', 'max_timeout_seconds', 'max_output_chars'})
_LOCK = threading.RLock()
_RECORDS: dict[str, dict[str, Any]] = {}


@dataclass(frozen=True)
class CommandGrant:
    principal: str
    workspace: str
    profile: str
    resource: str
    root: Path
    executables: tuple[Path, ...]
    timeout: int
    output_limit: int
    expires_at: float

    @property
    def owner(self):
        return (self.principal, self.workspace, self.profile, self.resource, str(self.root))


def _json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('duplicate key')
            result[key] = value
        return result
    try:
        if path.stat().st_size > 262144:
            raise ValueError('oversized document')
        return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique)
    except (OSError, ValueError, TypeError) as exc:
        raise PermissionError('LOCAL_COMMAND_APPROVAL_REQUIRED') from exc


def _local_path(raw, directory=False):
    if not isinstance(raw, str) or not raw or '\x00' in raw:
        raise PermissionError('INVALID_LOCAL_PATH')
    path = Path(raw)
    # Do not expand environment variables, resolve relative paths, UNC or devices.
    if not path.is_absolute() or raw.startswith(('\\\\', '//')) or (os.name == 'nt' and ':' in raw[2:]):
        raise PermissionError('ABSOLUTE_LOCAL_PATH_REQUIRED')
    try:
        for ancestor in (path, *path.parents):
            stat = ancestor.lstat()
            if ancestor.is_symlink() or getattr(stat, 'st_file_attributes', 0) & 0x400:
                raise PermissionError('REPARSE_PATH_DENIED')
        resolved = path.resolve(strict=True)
        if directory and (not resolved.is_dir() or resolved == Path(resolved.anchor)):
            raise PermissionError('BOUNDED_DIRECTORY_REQUIRED')
        if not directory and not resolved.is_file():
            raise PermissionError('EXECUTABLE_FILE_REQUIRED')
        return resolved
    except OSError as exc:
        raise PermissionError('LOCAL_PATH_UNAVAILABLE') from exc


def authorize_command_call(tool, arguments, authority):
    """Server preflight AND tool-time check; no caller metadata can grant rights."""
    if type(authority) is not VerifiedContext:
        raise PermissionError('AUTHENTICATED_EXECUTION_CONTEXT_REQUIRED')
    if tool not in COMMAND_TOOL_NAMES or authority.get('public_tool') != tool:
        raise PermissionError('COMMAND_TOOL_CONTEXT_MISMATCH')
    scopes = authority.get('scopes')
    if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes) or not {'files:execute', 'files:write'}.issubset(scopes):
        raise PermissionError('COMMAND_EXECUTE_AND_WRITE_SCOPES_REQUIRED')
    if authority.get('effective_access') != 'write' or authority.get('required_scope') != 'files:execute':
        raise PermissionError('CANONICAL_COMMAND_WRITE_SCOPE_REQUIRED')
    expiry = authority.get('expires_at')
    if isinstance(expiry, bool) or not isinstance(expiry, (float, int)) or not math.isfinite(expiry) or expiry <= time.time():
        raise PermissionError('CONTEXT_EXPIRED')
    deadline = authority.get('deadline', expiry)
    if isinstance(deadline, bool) or not isinstance(deadline, (float, int)) or not math.isfinite(deadline) or deadline <= time.time():
        raise PermissionError('CONTEXT_DEADLINE_EXPIRED')
    expiry = min(expiry, deadline)
    resources = authority.get('effective_resources')
    if not isinstance(resources, list) or len(resources) != 1 or not isinstance(resources[0], dict):
        raise PermissionError('ONE_FILES_RESOURCE_REQUIRED')
    resource = resources[0]
    profile_id = resource.get('profile_id')
    if resource.get('kind') != 'files' or not isinstance(profile_id, str) or not profile_id or not isinstance(resource.get('resource_id'), str) or not resource['resource_id'] or resource.get('revoked', False) is not False:
        raise PermissionError('FILES_PROFILE_SCOPE_REQUIRED')
    if authority.get('profile_id', profile_id) != profile_id:
        raise PermissionError('CONTEXT_PROFILE_MISMATCH')
    if not isinstance(arguments, dict) or arguments.get('profile', profile_id) != profile_id:
        raise PermissionError('PROFILE_NOT_IN_RESOURCE_SCOPE')
    for key in ('principal_id', 'workspace_id'):
        if not isinstance(authority.get(key), str) or not authority[key]:
            raise PermissionError('OWNER_REQUIRED')
    policy = _json(POLICY_FILE)
    if not isinstance(policy, dict) or set(policy) != _POLICY_KEYS:
        raise PermissionError('INVALID_COMMAND_POLICY_SCHEMA')
    if type(policy['version']) is not int or policy['version'] != 1 or policy['enabled'] is not True or policy['acknowledge_host_access'] is not True or policy['execution_mode'] != 'owner-account':
        raise PermissionError('EXPLICIT_OWNER_ACCOUNT_APPROVAL_REQUIRED')
    if policy['profile_id'] != profile_id:
        raise PermissionError('COMMAND_POLICY_PROFILE_MISMATCH')
    tools = policy['allowed_tools']
    if not isinstance(tools, list) or not tools or not all(isinstance(t, str) and t in COMMAND_TOOL_NAMES for t in tools) or len(tools) != len(set(tools)) or tool not in tools:
        raise PermissionError('COMMAND_TOOL_NOT_LOCALLY_APPROVED')
    for key, upper in (('max_timeout_seconds', 1800), ('max_output_chars', 200000)):
        if type(policy[key]) is not int or not 1 <= policy[key] <= upper:
            raise PermissionError('INVALID_COMMAND_POLICY_LIMIT')
    profiles = _json(PROFILES_FILE)
    rows = profiles.get('profiles') if isinstance(profiles, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise PermissionError('INVALID_LOCAL_PROFILES')
    matches = [p for p in rows if p.get('name') == profile_id]
    if len(matches) != 1:
        raise PermissionError('LOCAL_PROFILE_REQUIRED')
    profile = matches[0]
    for field in ('device_id', 'installation_id'):
        if field in resource and resource[field] != authority.get(field):
            raise PermissionError('RESOURCE_IDENTITY_MISMATCH')
        if field in profile and profile.get(field) != authority.get(field):
            raise PermissionError('PROFILE_IDENTITY_MISMATCH')
    if profile.get('enabled') is not True or profile.get('authorized_by_user') is not True or profile.get('mode') != 'read-write':
        raise PermissionError('LOCALLY_APPROVED_READ_WRITE_PROFILE_REQUIRED')
    root = _local_path(profile.get('root'), directory=True)
    if _local_path(policy['root'], directory=True) != root:
        raise PermissionError('COMMAND_POLICY_ROOT_MISMATCH')
    raw_exes = policy['allowed_executables']
    if not isinstance(raw_exes, list) or not raw_exes or len(raw_exes) > 64:
        raise PermissionError('ABSOLUTE_EXECUTABLE_ALLOWLIST_REQUIRED')
    executables = tuple(_local_path(p) for p in raw_exes)
    return CommandGrant(authority['principal_id'], authority['workspace_id'], profile_id,
                        resource['resource_id'], root, executables, policy['max_timeout_seconds'],
                        policy['max_output_chars'], float(expiry))


def resolve_cwd(grant, cwd):
    if not isinstance(cwd, str) or '\x00' in cwd:
        raise PermissionError('INVALID_WORKING_DIRECTORY')
    candidate = _local_path(str(grant.root / cwd), directory=True)
    if candidate != grant.root and grant.root not in candidate.parents:
        raise PermissionError('WORKING_DIRECTORY_OUTSIDE_RESOURCE')
    return candidate


def resolve_executable(requested, grant):
    if not isinstance(requested, str) or not requested or '\x00' in requested:
        raise PermissionError('INVALID_EXECUTABLE')
    path = Path(requested)
    if path.is_absolute():
        resolved = _local_path(requested)
        matches = [p for p in grant.executables if p == resolved]
    elif path.name == requested and '/' not in requested and '\\' not in requested:
        # Basenames select ONLY an unambiguous absolute local allowlist entry.
        names = {requested.casefold(), requested.casefold() + '.exe', requested.casefold() + '.cmd'}
        matches = [p for p in grant.executables if p.name.casefold() in names]
    else:
        matches = []
    if len(matches) != 1:
        raise PermissionError('EXECUTABLE_NOT_EXPLICITLY_APPROVED')
    return _local_path(str(matches[0]))


def child_environment(grant):
    # No ambient PATH, HOME, profile, OAuth, internal keys, Python or Node hooks.
    allowed = {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'LANG', 'LC_ALL'}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    system = env.get('SystemRoot') or env.get('SYSTEMROOT')
    dirs = list(dict.fromkeys(str(p.parent) for p in grant.executables))
    if system:
        dirs.append(str(Path(system) / 'System32'))
    env['PATH'] = os.pathsep.join(dirs)
    return env


def owned_record(record_id, grant):
    with _LOCK:
        record = _RECORDS.get(str(record_id))
        if record is None or record['owner'] != grant.owner:
            raise PermissionError('OWNED_COMMAND_RECORD_REQUIRED')
        return record


def list_owned(grant):
    with _LOCK:
        return [dict(command_id=k, task_id=k, pid=r['pid'], profile=grant.profile, state='running')
                for k, r in _RECORDS.items() if r['owner'] == grant.owner]


def _audit(tool, grant, state):
    # Never serialize arguments, environment, scripts, output or public metadata.
    payload = dict(time=time.time(), tool=tool, principal_id=grant.principal,
                   workspace_id=grant.workspace, profile_id=grant.profile,
                   resource_id=grant.resource, state=state)
    with _LOCK:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(payload, ensure_ascii=True) + '\n')


class _WindowsJob:
    """Kill-on-close job assigned BEFORE resuming the suspended root process.

    CPython Windows Popen._handle and ntdll.NtResumeProcess are required. Missing
    APIs or nested-job assignment failure deny execution; no uncontained retry.
    """
    def __init__(self):
        if os.name != 'nt':
            raise NotImplementedError('WINDOWS_OWNER_JOB_REQUIRED')
        from ctypes import wintypes as w
        class Basic(ctypes.Structure):
            _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                        ('LimitFlags', w.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                        ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', w.DWORD),
                        ('Affinity', ctypes.c_size_t), ('PriorityClass', w.DWORD), ('SchedulingClass', w.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in ('ReadOperationCount', 'WriteOperationCount',
                'OtherOperationCount', 'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]
        class Extended(ctypes.Structure):
            _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', IO),
                        ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                        ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.native = ctypes.WinDLL('ntdll', use_last_error=True)
        for name, args, result in (
            ('CreateJobObjectW', [ctypes.c_void_p, w.LPCWSTR], w.HANDLE),
            ('SetInformationJobObject', [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL),
            ('AssignProcessToJobObject', [w.HANDLE, w.HANDLE], w.BOOL),
            ('TerminateJobObject', [w.HANDLE, w.UINT], w.BOOL),
            ('CloseHandle', [w.HANDLE], w.BOOL),
        ):
            fn = getattr(self.kernel, name)
            fn.argtypes, fn.restype = args, result
        self.native.NtResumeProcess.argtypes = [w.HANDLE]
        self.native.NtResumeProcess.restype = w.LONG
        self.lock = threading.RLock()
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = Extended()
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise OSError('WINDOWS_JOB_LIMIT_CONFIGURATION_FAILED')

    def assign_and_resume(self, process):
        with self.lock:
            if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
                raise OSError('WINDOWS_JOB_ASSIGNMENT_FAILED')
            if self.native.NtResumeProcess(int(process._handle)) < 0:
                raise OSError('WINDOWS_JOB_RESUME_FAILED')

    def terminate(self):
        with self.lock:
            if self.handle and not self.kernel.TerminateJobObject(self.handle, 1):
                raise OSError('WINDOWS_JOB_TERMINATION_FAILED')

    def close(self):
        with self.lock:
            if self.handle:
                handle, self.handle = self.handle, None
                if not self.kernel.CloseHandle(handle):
                    raise OSError('WINDOWS_JOB_CLOSE_FAILED')


def _drain(stream, limit, target):
    retained = bytearray()
    discarded = False
    try:
        while True:
            block = stream.read(8192)
            if not block:
                break
            remaining = max(0, limit * 4 - len(retained))
            retained.extend(block[:remaining])
            discarded = discarded or len(block) > remaining
        text = retained.decode('utf-8', errors='replace')
        target.update(text=text[:limit], truncated=discarded or len(text) > limit)
    except (OSError, ValueError):
        target['error'] = True
    finally:
        stream.close()


def _run_owned(tool, arguments, grant, cancel, record_id):
    exe, argv = _command(tool, arguments, grant)
    workdir = resolve_cwd(grant, arguments.get('cwd', '.'))
    timeout = arguments.get('timeout_seconds', 120)
    if type(timeout) is not int or timeout < 1:
        raise ValueError('POSITIVE_INTEGER_TIMEOUT_REQUIRED')
    seconds = min(timeout, grant.timeout, grant.expires_at - time.time())
    if seconds <= 0 or cancel.is_set():
        raise PermissionError('CONTEXT_EXPIRED_OR_CANCELLED')
    job = _WindowsJob()  # Must succeed BEFORE creating even a suspended child.
    proc = None
    threads = []
    stdout, stderr = {}, {}
    started = time.monotonic()
    state = 'failed'
    try:
        _audit(tool, grant, 'starting')
        CREATE_SUSPENDED = 0x00000004
        proc = subprocess.Popen([str(exe), *argv], cwd=str(workdir), env=child_environment(grant),
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                close_fds=True, bufsize=0,
                                creationflags=CREATE_SUSPENDED | subprocess.CREATE_NO_WINDOW)
        # Root cannot execute or spawn descendants before assignment to this job.
        with _LOCK:
            if record_id in _RECORDS:
                raise PermissionError('COMMAND_RECORD_COLLISION')
            if cancel.is_set():
                raise InterruptedError('COMMAND_CANCELLED_BEFORE_RESUME')
            _RECORDS[record_id] = dict(owner=grant.owner, pid=proc.pid, job=job, cancel=cancel)
            job.assign_and_resume(proc)
        for stream, target in ((proc.stdout, stdout), (proc.stderr, stderr)):
            thread = threading.Thread(target=_drain, args=(stream, grant.output_limit, target), daemon=True)
            thread.start()
            threads.append(thread)
        while proc.poll() is None:
            if cancel.is_set():
                state = 'cancelled'
                raise InterruptedError('COMMAND_CANCELLED')
            if time.monotonic() - started >= seconds:
                state = 'timeout'
                raise TimeoutError('COMMAND_TIMEOUT_OR_CONTEXT_DEADLINE')
            cancel.wait(0.02)
        # A parent may exit leaving descendants with inherited stdout handles.
        # Kill all descendants before joining drainers; never wait for pipe EOF first.
        job.terminate()
        job.close()
        for thread in threads:
            thread.join(timeout=5)
        if any(t.is_alive() for t in threads) or stdout.get('error') or stderr.get('error'):
            raise OSError('COMMAND_OUTPUT_DRAIN_FAILED')
        state = 'finished'
        return dict(ok=proc.returncode == 0, exit_code=proc.returncode, pid=proc.pid,
                    command_id=record_id, task_id=record_id, profile=grant.profile, cwd=str(workdir),
                    stdout=stdout.get('text', ''), stderr=stderr.get('text', ''),
                    stdout_truncated=stdout.get('truncated', False), stderr_truncated=stderr.get('truncated', False))
    finally:
        # Close job even when audit, resume, reader startup, timeout or cancellation fails.
        try:
            job.close()
        finally:
            if proc is not None:
                if proc.poll() is None:
                    # Assignment can fail: this root is still suspended and owns no children.
                    proc.kill()
                proc.wait(timeout=5)
                for thread in threads:
                    thread.join(timeout=5)
                for stream in (proc.stdout, proc.stderr):
                    if stream is not None and not stream.closed:
                        stream.close()
            with _LOCK:
                record = _RECORDS.get(record_id)
                if record and record['job'] is job:
                    del _RECORDS[record_id]
            _audit(tool, grant, state)


def _npm_entrypoint(tool, grant):
    # Approval of the shim authorizes only the fixed sibling npm distribution
    # entrypoint. The shim itself is NEVER executed or parsed as a shell script.
    shim_name = 'npx.cmd' if tool == 'files_npx' else 'npm.cmd'
    shim = resolve_executable(shim_name, grant)
    if shim.name.casefold() != shim_name:
        raise PermissionError('EXPLICIT_NPM_SHIM_APPROVAL_REQUIRED')
    node = resolve_executable('node.exe', grant)
    filename = 'npx-cli.js' if tool == 'files_npx' else 'npm-cli.js'
    candidate = shim.parent / 'node_modules' / 'npm' / 'bin' / filename
    try:
        cli = _local_path(str(candidate))
    except PermissionError as exc:
        raise PermissionError('APPROVED_NPM_DISTRIBUTION_CLI_UNAVAILABLE_OR_REPARSE') from exc
    return node, cli


def _command(tool, arguments, grant):
    npm_tool = tool in ('files_npm', 'files_npx', 'files_build', 'files_test')
    if tool == 'files_exec_command':
        name, argv = arguments.get('executable'), arguments.get('args', [])
    elif tool == 'files_powershell_run':
        shells = [p for p in grant.executables if p.name.casefold() in ('powershell.exe', 'pwsh.exe')]
        if len(shells) != 1 or not isinstance(arguments.get('script'), str):
            raise PermissionError('ONE_EXPLICITLY_APPROVED_POWERSHELL_REQUIRED')
        name = str(shells[0])
        argv = ['-NoProfile', '-NonInteractive', '-Command', arguments['script']]
    else:
        names = {'files_node': 'node', 'files_npm': 'npm', 'files_npx': 'npx', 'files_git': 'git',
                 'files_build': 'npm', 'files_test': 'npm'}
        name = names[tool]
        argv = arguments.get('args', [])
        if tool in ('files_build', 'files_test'):
            script = arguments.get('script', 'build' if tool == 'files_build' else 'test')
            if not isinstance(script, str) or re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.:-]{0,127}', script) is None:
                raise ValueError('BOUNDED_NPM_SCRIPT_NAME_REQUIRED')
            argv = ['run', script]
    if not isinstance(argv, list) or len(argv) > 1024 or not all(isinstance(a, str) and '\x00' not in a for a in argv):
        raise ValueError('STRING_ARGUMENT_VECTOR_REQUIRED')
    if sum(len(a) for a in argv) > 30000:
        raise ValueError('COMMAND_ARGUMENT_LIMIT')
    if npm_tool:
        exe, cli = _npm_entrypoint(tool, grant)
        argv = [str(cli), *argv]
    else:
        exe = resolve_executable(name, grant)
    # cmd.exe parses metacharacters even with shell=False for .cmd/.bat.
    # Reject batch wrappers entirely rather than promise safe quoting. Owners
    # may explicitly approve node.exe and run a reviewed package CLI JS file.
    if exe.suffix.casefold() != '.exe':
        raise NotImplementedError('ONLY_NATIVE_EXE_SUPPORTED_NO_BATCH_SHELL_FALLBACK')
    return exe, argv


async def execute(tool, arguments):
    authority = current()
    # Optional profile None from the public schema is equivalent to omission.
    arguments = dict(arguments)
    if arguments.get('profile', object()) is None:
        arguments.pop('profile')
    grant = authorize_command_call(tool, arguments, authority)
    if tool == 'files_command_capabilities':
        return dict(execution_mode='owner-account', os_sandbox=False,
                    warning='Approved commands have the Windows owner account rights, not root-confined filesystem rights.',
                    persistent_process_start=False, batch_wrappers=False, windows_runtime_verified=False,
                    max_timeout_seconds=grant.timeout, max_output_chars=grant.output_limit,
                    supports=sorted(SUPPORTED_COMMAND_TOOLS), unsupported=sorted(UNSUPPORTED_COMMAND_TOOLS))
    if tool in UNSUPPORTED_COMMAND_TOOLS:
        raise NotImplementedError('UNSUPPORTED_MANAGED_COMMAND_NO_BATCH_OR_PERSISTENT_FALLBACK')
    if tool == 'files_process_list':
        # Never enumerate host processes or return command lines / environments.
        return dict(ok=True, processes=list_owned(grant))
    if tool in ('files_command_cancel', 'files_process_stop'):
        with _LOCK:
            if tool == 'files_command_cancel':
                record = owned_record(arguments.get('task_id'), grant)
            else:
                if type(arguments.get('pid')) is not int or arguments.get('confirm_unmanaged'):
                    raise PermissionError('OWNED_COMMAND_RECORD_REQUIRED')
                matches = [r for r in _RECORDS.values() if r['owner'] == grant.owner and r['pid'] == arguments['pid']]
                if len(matches) != 1:
                    raise PermissionError('OWNED_COMMAND_RECORD_REQUIRED')
                record = matches[0]
            record['cancel'].set()
            record['job'].terminate()
        _audit(tool, grant, 'termination_requested')
        return dict(ok=True, process_tree_termination_requested=True)
    record_id = authority.get('task_id') or authority.get('operation_id') or uuid.uuid4().hex
    if not isinstance(record_id, str) or not record_id or len(record_id) > 256:
        raise PermissionError('INVALID_COMMAND_RECORD_ID')
    cancel = threading.Event()
    # Shield the worker: cancelling asyncio.to_thread does NOT stop its thread.
    worker = asyncio.create_task(asyncio.to_thread(_run_owned, tool, arguments, grant, cancel, record_id))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        cancel.set()
        # Keep cleanup owned until the worker has closed its job. No taskkill/PID retry.
        try:
            await asyncio.shield(worker)
        except (Exception, asyncio.CancelledError):
            pass
        raise
