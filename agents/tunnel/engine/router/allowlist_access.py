"""Narrow owner control: only four memberships on the current existing grant.

No caller paths, target principals, scopes, executables or policy edits accepted.
The intent audit is fsynced before publication; only exact readback proves commit.
"""
import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading

from . import config
from .access import AuthorizationError, ResourceAuthorizer, digest
from .profile_admin import require_profile_management, bootstrap_resource, catalog_context, validate_catalog

TOOL = 'zagent_allowlist_access'
TOOLS = tuple('files_allowlist_' + a for a in ('list', 'add', 'remove', 'replace'))
SCHEMA = {'type':'object','properties':{
    'plan_only':{'type':'boolean','default':True},
    'expected_revision':{'type':'string','pattern':'^[a-f0-9]{64}$'},
    'expected_plan':{'type':'string','pattern':'^[a-f0-9]{64}$'}},'additionalProperties':False}
_LOCK = asyncio.Lock()
_WRITER_MUTEXES = {}


def require_available(auth, placement, authorizer, policy):
    require_profile_management(auth, placement, authorizer, 'files_profile_admin_update')
    bootstrap_resource(auth, placement, authorizer)
    grant = authorizer.current_grant(auth)
    for scope in ('files:read','files:write'):
        auth.require(scope)
        if scope not in grant.get('scopes', []):
            raise AuthorizationError('ALLOWLIST_ACCESS_DENIED')
    tools = grant.get('tools')
    if (not isinstance(tools, list) or any(not isinstance(t,str) or not t for t in tools)
            or len(set(tools)) != len(tools)):
        raise AuthorizationError('ALLOWLIST_ACCESS_DENIED')
    installed = config.load_tunnel_config()
    if type(installed.get('grant_writer_lock_version')) is not int or installed['grant_writer_lock_version'] != 1:
        raise AuthorizationError('CORE_WRITER_UPGRADE_REQUIRED',409)
    policies = installed.get('tool_policy')
    if policies is not None and not isinstance(policies,dict):
        raise AuthorizationError('ALLOWLIST_ACCESS_DENIED')
    explicit = (policies or {}).get(TOOL, {'scope':'files:write','enabled':True})
    if not isinstance(explicit,dict) or explicit.get('scope') != 'files:write' or explicit.get('enabled',True) is not True:
        raise AuthorizationError('ALLOWLIST_ACCESS_DENIED')
    for name in TOOLS:
        p = policy(name)
        if p.get('enabled',True) is not True or p.get('scope') != ('files:read' if name.endswith('_list') else 'files:write'):
            raise AuthorizationError('ALLOWLIST_ACCESS_DENIED')
    return grant


def _physical(path):
    path = Path(path).absolute()
    for p in [path, *path.parents]:
        if p.is_symlink() or (p.exists() and getattr(p.stat(), 'st_file_attributes',0) & 0x400):
            raise AuthorizationError('ALLOWLIST_ACCESS_DENIED')
    return path


@contextmanager
def writer(path):
    """Shared process and cross-process CAS lock for this config writer domain."""
    lock = _physical(Path(str(path)+'.access.lock'))
    # POSIX byte-range locks are process-owned. Gate local callers BEFORE
    # opening another fd: closing such an fd can release the process's locks.
    key = os.path.normcase(str(lock.resolve()))
    local = _WRITER_MUTEXES.setdefault(key, threading.Lock())
    if not local.acquire(blocking=False):
        raise BlockingIOError('CONFIG_WRITER_BUSY')
    try:
        fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
        with os.fdopen(fd,'r+b') as handle:
            if os.name == 'nt':
                import msvcrt
                handle.seek(0); handle.write(b'\0'); handle.flush(); handle.seek(0)
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.lockf(handle,fcntl.LOCK_EX | fcntl.LOCK_NB,1,0)
            try:
                yield
            finally:
                if os.name == 'nt':
                    handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    fcntl.lockf(handle,fcntl.LOCK_UN,1,0)
    finally:
        local.release()


def _replace_file(path, temporary):
    """One guarded publication seam on POSIX and Windows for fault injection.

    Windows ReplaceFileW preserves destination security metadata; POSIX sets the
    destination file mode on the staged file before rename. No non-atomic
    remove+rename fallback is allowed.
    """
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        replace = ctypes.WinDLL('kernel32', use_last_error=True).ReplaceFileW
        replace.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                            wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
        replace.restype = wintypes.BOOL
        if not replace(str(path), str(temporary), None, 0, None, None):
            raise OSError('PUBLICATION_FAILED')
    else:
        os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)


def publish(path, raw, expected, revalidate):
    path = _physical(path)
    fd, temporary = tempfile.mkstemp(prefix=path.name+'.access-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        revalidate()
        observed = _physical(path).read_bytes() if path.exists() else None
        if observed != expected:
            raise AuthorizationError('REVISION_CONFLICT',409)
        if expected is None:
            # Bootstrap creation without overwriting a concurrently-created file.
            os.link(temporary,path)
        else:
            _replace_file(path, temporary)
        if path.read_bytes() != raw:
            raise AuthorizationError('PUBLICATION_UNCERTAIN',409)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def _strict_config(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise AuthorizationError('ALLOWLIST_ACCESS_DENIED')
            result[key] = value
        return result
    def invalid(_):
        raise AuthorizationError('ALLOWLIST_ACCESS_DENIED')
    return json.loads(raw.decode('utf-8-sig'), object_pairs_hook=pairs, parse_constant=invalid)


def _sha(raw):return hashlib.sha256(raw).hexdigest()


async def control(server, arguments, initial, bearer):
    # The same installation read lease excludes profile-administration writers.
    async with server.orchestrator.locks.acquire('installation:'+server.placement.installation_id,'read'):
        async with _LOCK:
            path = _physical(config.TUNNEL_FILE)
            with writer(path):
                auth = await server.authorizer().authenticate(bearer,server._auth_client)
                if (auth.principal_id,auth.workspace_id) != (initial.principal_id,initial.workspace_id):
                    raise AuthorizationError('ALLOWLIST_ACCESS_DENIED')
                current = server.authorizer()
                grant = require_available(auth,server.placement,current,server._policy)
                snapshot = await server.registry.profile_catalog_snapshot(catalog_context(auth,server.placement))
                if snapshot.get('managed') is not True or not isinstance(snapshot.get('owner'),dict):
                    raise AuthorizationError('ALLOWLIST_ACCESS_DENIED')
                validate_catalog(snapshot,auth,server.placement,current)
                mappings = {name:server.registry.tool_index.get(name) for name in TOOLS}
                for name in TOOLS:
                    mapping = mappings[name]
                    if not mapping or mapping[0] not in {'zagent_files','zagent_files_v3'} or mapping[1] != name:
                        raise AuthorizationError('ALLOWLIST_BACKEND_UNAVAILABLE',409)
                raw = path.read_bytes(); cfg=_strict_config(raw)
                fresh = ResourceAuthorizer(cfg.get('resource_server') or {})
                fresh_grant = require_available(auth,server.placement,fresh,server._policy)
                if fresh_grant != grant:raise AuthorizationError('REVISION_CONFLICT',409)
                revision = _sha(raw)
                added = [t for t in TOOLS if t not in grant['tools']]
                plan = digest(dict(principal=auth.principal_id,workspace=auth.workspace_id,
                    device=server.placement.device_id,installation=server.placement.installation_id,
                    revision=revision,add=added,catalog=digest(snapshot)))
                audit_path = _physical(Path(str(path)+'.access-audit.jsonl'))
                audit_verified = False
                if audit_path.exists():
                    for line in audit_path.read_text().splitlines():
                        row=json.loads(line)
                        if row.get('principal')==auth.principal_id and row.get('after')==revision:
                            audit_verified=True
                result=dict(ok=True,plan_only=arguments.get('plan_only',True),revision=revision,
                    expected_plan=plan,tools=list(TOOLS),add=added,state='enabled' if not added else 'planned',audit_verified=audit_verified)
                if arguments.get('plan_only',True):return result
                if arguments.get('expected_revision') != revision or arguments.get('expected_plan') != plan:
                    raise AuthorizationError('REVISION_CONFLICT',409)
                if not added:return result
                fresh_grant['tools'] += added
                output=(json.dumps(cfg,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
                # Fresh OAuth immediately before the synchronous commit/CAS section.
                final = await server.authorizer().authenticate(bearer,server._auth_client)
                if (final.principal_id,final.workspace_id,final.scopes,final.tools,final.policy_revision) != (auth.principal_id,auth.workspace_id,auth.scopes,auth.tools,auth.policy_revision):
                    raise AuthorizationError('AUTHORIZATION_CHANGED',409)
                def revalidate():
                    require_available(final,server.placement,server.authorizer(),server._policy)
                    for name in TOOLS:
                        if server.registry.tool_index.get(name) != mappings[name]:
                            raise AuthorizationError('ALLOWLIST_BACKEND_UNAVAILABLE',409)
                revalidate()
                audit = dict(version=1,principal=auth.principal_id,workspace=auth.workspace_id,
                    before=revision,after=_sha(output),plan=plan,add=added)
                with audit_path.open('a',encoding='utf-8') as stream:
                    stream.write(json.dumps(audit,sort_keys=True)+'\n');stream.flush();os.fsync(stream.fileno())
                publish(path,output,raw,revalidate)
                readback=json.loads(path.read_bytes())
                if readback != cfg:raise AuthorizationError('PUBLICATION_UNCERTAIN',409)
                return dict(result,revision=_sha(output),state='enabled',add=[],audit_verified=True)
