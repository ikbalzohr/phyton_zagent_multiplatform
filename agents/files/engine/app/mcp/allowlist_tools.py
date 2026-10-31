"""Native MCP executable membership administration; no broker/enrollment authority.

The ordinary verified Files context selects exactly one approved resource. This
module never grants command execution or changes owner-account approval.
"""
from contextlib import contextmanager
import hashlib
import inspect
import os
from pathlib import Path
import re
import tempfile
import threading

_LOCK = threading.RLock()


@contextmanager
def _writer(path):
    # Same lock domain as the existing optional legacy allowlist engine.
    from app.allowlist.engine import _physical, _writer as windows_writer
    if os.name == 'nt':
        with windows_writer(path):
            yield
    else:
        import fcntl
        lock = _physical(Path(str(path) + '.allowlist.lock'))
        with lock.open('a+b') as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _publish(path, raw, expected, revalidate):
    from app.allowlist.engine import _physical, _read
    path = _physical(path)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.native-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        revalidate()
        if _read(path) != expected:
            raise ValueError('REVISION_CONFLICT')
        if os.name == 'nt':
            # ReplaceFile preserves the existing target's DACL, unlike replacing
            # it with an inherited temporary-file DACL. Never fall back.
            import ctypes
            from ctypes import wintypes
            replace = ctypes.WinDLL('kernel32', use_last_error=True).ReplaceFileW
            replace.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
            replace.restype = wintypes.BOOL
            if not replace(str(path), temporary, None, 0, None, None):
                raise OSError('POLICY_PUBLICATION_FAILED')
        else:
            os.chmod(temporary, path.stat().st_mode & 0o777)
            os.replace(temporary, path)
        if _read(path) != raw:
            raise OSError('POLICY_PUBLICATION_UNCERTAIN')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _executable(raw):
    if (not isinstance(raw, str) or not raw or len(raw) > 2048
            or any(ord(c) < 32 or ord(c) == 127 for c in raw)
            or any(c in raw for c in ('%', '*', '?', '$', '"'))
            or os.path.normpath(raw) != raw):
        raise ValueError('EXACT_LOCAL_EXECUTABLE_REQUIRED')
    if os.name == 'nt':
        from app.allowlist.engine import validate_executable
        validate_executable(raw)
    path = commands._local_path(raw)
    with path.open('rb') as stream:
        header = stream.read(64)
        if os.name == 'nt':
            if len(header) != 64 or header[:2] != b'MZ':
                raise ValueError('EXECUTABLE_IMAGE_REQUIRED')
            stream.seek(int.from_bytes(header[60:64], 'little'))
            if stream.read(4) != b'PE\x00\x00':
                raise ValueError('EXECUTABLE_IMAGE_REQUIRED')
        elif header[:4] != b'\x7fELF' or not os.access(path, os.X_OK):
            raise ValueError('EXECUTABLE_IMAGE_REQUIRED')
    return str(path)

from mcp.types import ToolAnnotations
from app.core.execution_context import authorize_operation, current, validate_profile
from app.mcp import managed_commands as commands
from app.profiles import manager

TOOLS = frozenset('files_allowlist_' + action for action in ('list', 'add', 'remove', 'replace'))


def _authorize(tool, arguments):
    authority = current()
    authorize_operation(authority, tool, arguments)
    profile_id = arguments['profile_id']
    rows = [row for row in manager.load_profiles()['profiles'] if row['name'] == profile_id]
    if len(rows) != 1:
        raise PermissionError('FILES_PROFILE_NOT_APPROVED')
    validate_profile(authority, rows[0])
    return rows[0]


def _snapshot(profile):
    from app.allowlist.engine import _read
    from app.allowlist.protocol import loads
    raw = _read(commands.POLICY_FILE)
    document = loads(raw)
    policies = commands._policy_profiles(document)
    if profile['name'] not in policies:
        raise PermissionError('COMMAND_POLICY_PROFILE_MISMATCH')
    policy = policies[profile['name']]
    if commands._local_path(policy['root'], True) != commands._local_path(profile['root'], True):
        raise PermissionError('COMMAND_POLICY_ROOT_MISMATCH')
    exes = policy['allowed_executables']
    if (not isinstance(exes, list) or not 1 <= len(exes) <= 64
            or not all(isinstance(e, str) and e and len(e) <= 2048 for e in exes)
            or len({e.casefold() for e in exes}) != len(exes)):
        raise ValueError('POLICY_INVALID')
    return raw, document, policy


def invoke(tool, arguments):
    action = tool.removeprefix('files_allowlist_')
    fields = {'profile_id'}
    if action != 'list':
        fields |= {'executable', 'expected_revision'}
    if action == 'replace':
        fields.add('replacement_executable')
    if (tool not in TOOLS or set(arguments) != fields
            or any(not isinstance(v, str) or not v for v in arguments.values())
            or re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9_.-]{0,255}', arguments['profile_id']) is None
            or (action != 'list' and re.fullmatch('[0-9a-f]{64}', arguments['expected_revision']) is None)):
        raise ValueError('INVALID_ARGUMENT')
    profile = _authorize(tool, arguments)
    with _LOCK, _writer(commands.POLICY_FILE):
        profile = _authorize(tool, arguments)
        raw, document, policy = _snapshot(profile)
        revision = hashlib.sha256(raw).hexdigest()
        if action == 'list':
            return dict(ok=True, profile_id=profile['name'], revision=revision,
                        executables=list(policy['allowed_executables']))
        if revision != arguments['expected_revision']:
            raise ValueError('REVISION_CONFLICT')
        exes = policy['allowed_executables']
        added, removed = [], []
        if action == 'remove':
            old = arguments['executable']
            if old not in exes:
                raise ValueError('EXECUTABLE_NOT_ALLOWED')
            if len(exes) == 1:
                raise ValueError('NONEMPTY_ALLOWLIST_REQUIRED')
            exes.remove(old)
            removed = [old]
        else:
            new = arguments['replacement_executable'] if action == 'replace' else arguments['executable']
            if action == 'replace' and arguments['executable'] not in exes:
                raise ValueError('EXECUTABLE_NOT_ALLOWED')
            if _executable(new) != new:
                raise ValueError('EXACT_LOCAL_EXECUTABLE_REQUIRED')
            if new.casefold() in {e.casefold() for e in exes}:
                raise ValueError('EXECUTABLE_ALREADY_ALLOWED')
            if action == 'replace':
                old = arguments['executable']
                exes[exes.index(old)] = new
                removed = [old]
            else:
                if len(exes) >= 64:
                    raise ValueError('ALLOWLIST_CAPACITY')
                exes.append(new)
            added = [new]
        from app.allowlist.protocol import canonical
        candidate = canonical(document) + b'\n'
        if len(candidate) > 262144:
            raise ValueError('POLICY_TOO_LARGE')
        commands._policy_profiles(document)
        _publish(commands.POLICY_FILE, candidate, raw, lambda: _authorize(tool, arguments))
        return dict(ok=True, profile_id=profile['name'], previous_revision=revision,
                    revision=hashlib.sha256(candidate).hexdigest(), changed=True, added=added, removed=removed)


def register(mcp):
    def make(tool):
        action = tool.removeprefix('files_allowlist_')
        fields = ['profile_id']
        if action != 'list':
            fields += ['executable', 'expected_revision']
        if action == 'replace':
            fields += ['replacement_executable']
        async def wrapped(**arguments):
            from mcp.server.fastmcp import ToolError
            try:
                return invoke(tool, arguments)
            except ValueError as exc:
                message = str(exc)
                raise ToolError(message) from exc
            except PermissionError as exc:
                raise ToolError(str(exc)) from exc
        wrapped.__name__ = tool
        wrapped.__signature__ = inspect.Signature([
            inspect.Parameter(key, inspect.Parameter.KEYWORD_ONLY, annotation=str) for key in fields], return_annotation=dict)
        wrapped.__annotations__ = {key: str for key in fields} | {'return': dict}
        return wrapped
    for tool in sorted(TOOLS):
        mcp.add_tool(make(tool), description='Administer exact executable paths for one authorized Files profile. '
            'Executables run with owner-account rights, not in a sandbox. Existing command scope and local approval remain required.',
            annotations=ToolAnnotations(readOnlyHint=tool.endswith('_list'), destructiveHint=not tool.endswith('_list'), openWorldHint=False))
