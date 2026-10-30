"""Code-only private diagnostics. Keep the Files implementation aligned.

No exception text, caller IDs, tool arguments or configuration enters this store.
Windows directories inherit the enrolled private DataRoot ACL; never grant ACLs.
"""
from __future__ import annotations

from collections import deque
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import inspect
import json
import os
from pathlib import Path
import re
import stat
import sys
import threading
import uuid

MAX_BYTES = 1024 * 1024
MESSAGES = {
    'UNEXPECTED_ERROR': 'Request processing failed. Inspect the correlated stage and verify the deployed component configuration.',
    'AUTH_REQUIRED': 'Authorization is required. Use the configured authorization server.',
    'AUTH_INVALID_TOKEN': 'The token was rejected. Obtain valid authorization through the configured authorization server.',
    'AUTH_TOKEN_EXPIRED': 'Authorization has expired. Obtain valid authorization through the configured authorization server.',
    'AUTH_INTROSPECTION_FAILED': 'Token introspection failed. Verify the authorization server and private client configuration.',
    'AUTH_NOT_AUTHORIZED': 'Authorization was rejected. Ask the owner to verify the current grant without bypassing access checks.',
    'ROUTER_CONFIGURATION_ERROR': 'Configuration could not be loaded or validated. Verify the owner-managed component configuration.',
    'ROUTER_UPSTREAM_UNAVAILABLE': 'Upstream dispatch failed. Inspect private backend diagnostics before retrying a mutation.',
    'ROUTER_PROTOCOL_ERROR': 'Request arguments or protocol were rejected. Check the published input schema.',
    'FILES_OPERATION_FAILED': 'Files tool execution failed. Inspect the correlated stage before retrying a mutation.',
    'CORE_AGENT_START_FAILED': 'Agent startup failed. Inspect the component diagnostics.',
    'CORE_AGENT_EXITED': 'An agent exited. Inspect the component diagnostics.',
    'DASHBOARD_REQUEST_FAILED': 'The dashboard request failed. Inspect the correlated stage.',
    'DIAGNOSTIC_IO_FAILED': 'Persistent diagnostics are unavailable. Verify the private diagnostic storage.',
}
CURRENT_ID: ContextVar[str | None] = ContextVar('diagnostic_request_id', default=None)


def new_request_id():
    return uuid.uuid4().hex


def request_id():
    return CURRENT_ID.get() or new_request_id()


class EventStore:
    def __init__(self, component, data_root=None):
        if component not in {'router', 'files', 'core'}:
            raise ValueError('INVALID_DIAGNOSTIC_COMPONENT')
        self.component = component
        self.root = Path(data_root) if data_root else None
        self.available = False
        self.fallback = deque(maxlen=64)
        self._lock = threading.Lock()
        self._warned = False

    def _unavailable(self):
        self.available = False
        if not self._warned:
            self._warned = True
            try:
                sys.stderr.write('ZAGENT_DIAGNOSTICS_UNAVAILABLE: persistent diagnostics unavailable; bounded memory only.\n')
            except Exception:
                pass

    @staticmethod
    def _check(path, private=False):
        value = path.lstat()
        if stat.S_ISLNK(value.st_mode) or getattr(value, 'st_file_attributes', 0) & 0x400:
            raise OSError('UNSAFE_DIAGNOSTIC_PATH')
        if private and os.name != 'nt' and (value.st_uid != os.getuid() or value.st_mode & 0o077):
            raise OSError('UNSAFE_DIAGNOSTIC_PERMISSIONS')
        return value

    def _path(self):
        if self.root is None or not self.root.is_absolute():
            raise OSError('DIAGNOSTIC_ROOT_UNAVAILABLE')
        # Do not resolve(): resolving first would hide symlinks/reparse points.
        for directory in [*reversed(self.root.parents), self.root]:
            if not directory.exists() and not directory.is_symlink():
                directory.mkdir(mode=0o700)
            if not stat.S_ISDIR(self._check(directory).st_mode):
                raise OSError('UNSAFE_DIAGNOSTIC_DIRECTORY')
        directory = self.root
        for name in ('logs', 'diagnostics'):
            directory /= name
            directory.mkdir(mode=0o700, exist_ok=True)
            value = self._check(directory)
            if os.name != 'nt':
                if value.st_uid != os.getuid():
                    raise OSError('UNSAFE_DIAGNOSTIC_OWNER')
                # Core may have created these directories first with its
                # default umask. Tighten only our owned logging directories.
                os.chmod(directory, 0o700, follow_symlinks=False)
            if not stat.S_ISDIR(self._check(directory, private=True).st_mode):
                raise OSError('UNSAFE_DIAGNOSTIC_DIRECTORY')
        return directory / (self.component + '.jsonl')

    def emit(self, correlation, stage, code, severity='error'):
        # All fields must be bounded allowlisted literals; no caller text survives.
        code = code if isinstance(code, str) and code in MESSAGES else 'UNEXPECTED_ERROR'
        if (not isinstance(correlation, str) or not re.fullmatch(r'[0-9a-f]{32}', correlation)
                or not isinstance(stage, str) or not re.fullmatch(r'[a-z][a-z0-9_.-]{0,63}', stage)
                or severity not in {'warning', 'error', 'info'}):
            return False
        event = dict(version=1, timestampUtc=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                     requestId=correlation, component=self.component, stage=stage,
                     code=code, severity=severity, message=MESSAGES[code])
        payload = (json.dumps(event, separators=(',', ':'), ensure_ascii=True) + '\n').encode('utf-8')
        with self._lock:
            try:
                path = self._path()
                rotated = path.with_name(path.name + '.1')
                for target in (path, rotated):
                    if target.exists() or target.is_symlink():
                        if not stat.S_ISREG(self._check(target, private=True).st_mode):
                            raise OSError('UNSAFE_DIAGNOSTIC_FILE')
                if path.exists() and path.stat().st_size + len(payload) > MAX_BYTES:
                    os.replace(path, rotated)
                flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
                fd = os.open(path, flags, 0o600)
                try:
                    value = os.fstat(fd)
                    if not stat.S_ISREG(value.st_mode) or (os.name != 'nt' and (value.st_uid != os.getuid() or value.st_mode & 0o077)):
                        raise OSError('UNSAFE_DIAGNOSTIC_FILE')
                    written = os.write(fd, payload)
                    if written != len(payload):
                        raise OSError('DIAGNOSTIC_SHORT_WRITE')
                finally:
                    os.close(fd)
                self.available = True
                return True
            except Exception:
                self.fallback.append(event)
                self._unavailable()
                return False


COMPONENT = 'files'
store = EventStore(COMPONENT, os.environ.get('ZAGENT_CORE_DATA_ROOT'))


def record(stage, code='UNEXPECTED_ERROR', correlation=None):
    return store.emit(correlation or request_id(), stage, code)


def traced(stage, code='UNEXPECTED_ERROR'):
    """Record a static reason and preserve the original exception semantics."""
    def decorate(function):
        if inspect.iscoroutinefunction(function):
            @wraps(function)
            async def asynchronous(*args, **kwargs):
                token = CURRENT_ID.set(request_id())
                try:
                    return await function(*args, **kwargs)
                except Exception as exc:
                    record(stage, failure_code(exc, code))
                    raise
                finally:
                    CURRENT_ID.reset(token)
            return asynchronous
        @wraps(function)
        def synchronous(*args, **kwargs):
            token = CURRENT_ID.set(request_id())
            try:
                return function(*args, **kwargs)
            except Exception as exc:
                record(stage, failure_code(exc, code))
                raise
            finally:
                CURRENT_ID.reset(token)
        return synchronous
    return decorate


def failure_code(exc, default='UNEXPECTED_ERROR'):
    # Only exact known protocol codes influence the diagnostic enum. Never
    # persist a supplied .code, exception class name or exception string.
    value = getattr(exc, 'code', None)
    known = {'invalid_token': 'AUTH_INVALID_TOKEN', 'insufficient_scope': 'AUTH_NOT_AUTHORIZED',
             'grant_revoked': 'AUTH_NOT_AUTHORIZED', 'authorization_unavailable': 'AUTH_INTROSPECTION_FAILED',
             'NOT_CONFIGURED': 'ROUTER_CONFIGURATION_ERROR', 'NOT_READY': 'ROUTER_CONFIGURATION_ERROR',
             'AUTHORIZATION_EXPIRED': 'AUTH_TOKEN_EXPIRED'}
    return known.get(value, default) if isinstance(value, str) else default
