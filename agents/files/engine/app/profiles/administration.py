"""One live Files writer for owner profile administration.

Only authenticated adapters may construct the two typed channel envelopes.
No public arguments supply capability or actor authority. Windows runtime only.
"""
from __future__ import annotations
import asyncio
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from app.profiles import manager
from app.core.execution_context import TrustedMetadata
from app.paths import DATA_ROOT, CONFIG_DIR, RUNTIME_DIR, LOG_DIR, BACKUP_ROOT, UPDATE_STATE_ROOT

ACTIONS = ('list', 'get', 'create', 'update', 'delete', 'set_default')
PROFILE_ADMIN_TOOLS = { 'files_profile_admin_' + a: a for a in ACTIONS }
CATALOG_TOOL = 'files_profile_catalog_snapshot'
ADMIN_META = 'zagent.profile_admin_context'
CATALOG_META = 'zagent.profile_catalog_context'
MAX_BYTES = 262144
ID = re.compile(r'[A-Za-z0-9_-]{1,256}\Z', re.ASCII)
HEX = re.compile(r'[0-9a-fA-F]{64}\Z', re.ASCII)
COMMON = {'version','source','actor_id','principal_id','workspace_id','device_id','installation_id','deadline'}
ADMIN_FIELDS = COMMON | {'action','public_tool','request_id','operation_id','capability_revision','payload_digest','bootstrap_resource'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('DUPLICATE_JSON_KEY')
        out[key] = value
    return out


def _load():
    raw = manager.PROFILES_FILE.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError('PROFILE_STATE_TOO_LARGE')
    state = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))
    _validate_state(state)
    return state


def _text(value, limit=256):
    return isinstance(value, str) and 0 < len(value) <= limit and not any(ord(c) < 32 for c in value)


def _id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('INVALID_PROFILE_ID')
    return value


def _validate_state(state):
    if not isinstance(state, dict) or not {'schema_version','active_profile','profiles'} <= set(state) or set(state) - {'schema_version','active_profile','profiles','owner_management'}:
        raise ValueError('INVALID_PROFILE_STATE')
    if not isinstance(state.get('profiles'), list):
        raise ValueError('INVALID_PROFILE_ROWS')
    names = []
    for row in state['profiles']:
        if (not isinstance(row, dict) or set(row) - {'name','root','mode','enabled','description','authorized_by_user','authorized_at','authorization_source','authorized_by','device_id','installation_id','execution_access'}
                or ('execution_access' in row and row['execution_access'] not in ('disabled','developer','full'))
                or (row.get('mode') == 'read-only' and row.get('execution_access','disabled') != 'disabled')
                or not isinstance(row.get('root'),str) or not 1 <= len(row['root']) <= 32768
                or row.get('mode') not in ('read-only','read-write')
                or any(k in row and type(row[k]) is not bool for k in ('enabled','authorized_by_user'))
                or ('description' in row and (not isinstance(row['description'],str) or len(row['description']) > 512))):
            raise ValueError('INVALID_PROFILE_ROW')
        names.append(_id(row.get('name')))
    if len(names) != len(set(names)):
        raise ValueError('DUPLICATE_PROFILE_ID')
    if 'owner_management' in state and state.get('active_profile') is not None and state['active_profile'] not in names:
        raise ValueError('INVALID_ACTIVE_PROFILE')
    m = state.get('owner_management')
    if m is None:
        if 'owner_management' in state:
            raise ValueError('INVALID_OWNER_MANAGEMENT')
        return
    if (not isinstance(m, dict) or set(m) != {'version','revision','owners','generations','operations'}
            or type(m['version']) is not int or m['version'] != 1
            or not isinstance(m['revision'], str) or not HEX.fullmatch(m['revision'])
            or not isinstance(m['owners'], dict) or not isinstance(m['generations'], dict)
            or set(m['generations']) != set(names)
            or not all(_text(g) for g in m['generations'].values())
            or not isinstance(m['operations'], list) or len(m['operations']) > 32):
        raise ValueError('INVALID_OWNER_MANAGEMENT')
    for principal, owner in m['owners'].items():
        if (not _text(principal) or not isinstance(owner, dict)
                or set(owner) != {'workspace_id','device_id','installation_id','resource_id','default_profile_id','allowed_profile_ids'}):
            raise ValueError('INVALID_OWNER_BINDING')
        _resource(owner, placement=False)
        if not set(owner['allowed_profile_ids']) <= set(names):
            raise ValueError('INVALID_OWNER_MEMBERSHIP')
    for record in m['operations']:
        if (not isinstance(record, dict) or set(record) != {'actor','key','digest','outcome'}
                or not _text(record['actor'], 2048) or not _text(record['key'],128)
                or not isinstance(record['digest'], str) or not HEX.fullmatch(record['digest'])
                or not isinstance(record['outcome'],dict)):
            raise ValueError('INVALID_OPERATION_RECORD')


def profile_generation(row, state):
    managed = state.get('owner_management')
    return managed['generations'][row['name']] if managed else digest(row)


def current_catalog():
    """Internal committed snapshot. Never grants membership on an unmanaged read."""
    return _catalog(_load())


def _catalog(state):
    m = state.get('owner_management')
    return {'revision': m['revision'] if m else digest(state),
            'profiles': [_public(row) for row in state['profiles']],
            'generations': {p['name']: profile_generation(p, state) for p in state['profiles']},
            'managed': m is not None}


def _public(row):
    return {k: copy.deepcopy(v) for k,v in row.items() if k in
            {'name','root','mode','enabled','description','execution_access','authorized_by_user','authorization_source'}}


def _resource(value, placement=True):
    fields = {'resource_id','default_profile_id','allowed_profile_ids'}
    if not placement:
        fields |= {'workspace_id','device_id','installation_id'}
    if not isinstance(value,dict) or set(value) != fields:
        raise PermissionError('INVALID_BOOTSTRAP_RESOURCE')
    if not _text(value['resource_id']):
        raise PermissionError('INVALID_RESOURCE_ID')
    ids = value['allowed_profile_ids']
    if not isinstance(ids,list) or not 1 <= len(ids) <= 128 or len(set(map(str, ids))) != len(ids):
        raise PermissionError('INVALID_RESOURCE_MEMBERSHIP')
    for name in ids:
        _id(name)
    if value['default_profile_id'] not in ids:
        raise PermissionError('INVALID_RESOURCE_DEFAULT')
    if not placement and not all(_text(value[f]) for f in ('workspace_id','device_id','installation_id')):
        raise PermissionError('INVALID_RESOURCE_PLACEMENT')


def _verify(metadata, tool=None, arguments=None):
    if not isinstance(metadata, TrustedMetadata):
        raise PermissionError('AUTHENTICATED_INTERNAL_CHANNEL_REQUIRED')
    key = ADMIN_META if tool else CATALOG_META
    context = metadata.get(key)
    if not isinstance(context,dict) or set(context) != (ADMIN_FIELDS if tool else COMMON):
        raise PermissionError('INVALID_PROFILE_CONTEXT_SCHEMA')
    if type(context['version']) is not int or context['version'] != 1 or context['source'] not in ('oauth','dashboard'):
        raise PermissionError('INVALID_PROFILE_CONTEXT_VERSION_SOURCE')
    for field in COMMON - {'version','deadline','source'}:
        if not _text(context[field]):
            raise PermissionError('INVALID_PROFILE_CONTEXT_' + field)
    if context['source'] == 'oauth' and context['actor_id'] != context['principal_id']:
        raise PermissionError('OAUTH_ACTOR_MISMATCH')
    deadline = context['deadline']
    if (type(deadline) not in (int,float) or not math.isfinite(deadline)
            or not time.time() < deadline <= time.time() + 3600):
        raise PermissionError('PROFILE_CONTEXT_EXPIRED')
    for field, env in (('device_id','ZAGENT_DEVICE_ID'),('installation_id','ZAGENT_INSTALLATION_ID')):
        if not os.environ.get(env) or context[field] != os.environ[env]:
            raise PermissionError('PROFILE_CONTEXT_PLACEMENT_MISMATCH')
    if tool:
        if (tool not in PROFILE_ADMIN_TOOLS or context['public_tool'] != tool
                or context['action'] != PROFILE_ADMIN_TOOLS[tool]):
            raise PermissionError('PROFILE_ADMIN_TOOL_MISMATCH')
        for field in ('request_id','operation_id'):
            if not _text(context[field]):
                raise PermissionError('INVALID_PROFILE_CONTEXT_' + field)
        # profile_management is checked against the current configured owner by
        # the authenticated adapter; its canonical revision is channel-bound.
        if not isinstance(context['capability_revision'],str) or not HEX.fullmatch(context['capability_revision']):
            raise PermissionError('PROFILE_MANAGEMENT_CAPABILITY_REQUIRED')
        if context['payload_digest'] != digest(arguments):
            raise PermissionError('PROFILE_ADMIN_PAYLOAD_MISMATCH')
        _resource(context['bootstrap_resource'])
    return context


class CatalogLeases:
    """Async leases: owned cancellation can bypass a waiting writer, not an active one."""
    def __init__(self):
        self.condition = asyncio.Condition()
        self.readers = 0
        self.writer = False
        self.waiting = 0

    @asynccontextmanager
    async def read(self, control=False):
        async with self.condition:
            await self.condition.wait_for(lambda: not self.writer and (control or not self.waiting))
            self.readers += 1
        try:
            yield
        finally:
            async with self.condition:
                self.readers -= 1
                self.condition.notify_all()

    @asynccontextmanager
    async def write(self):
        async with self.condition:
            self.waiting += 1
            try:
                await self.condition.wait_for(lambda: not self.writer and not self.readers)
                self.writer = True
            finally:
                self.waiting -= 1
                self.condition.notify_all()
        try:
            yield
        finally:
            async with self.condition:
                self.writer = False
                self.condition.notify_all()


LEASES = CatalogLeases()


def read_lease(control=False):
    return LEASES.read(control)


async def catalog_worker(awaitable):
    """Keep admitted thread work leased until it actually ends, even on recancel.

    Cancelling an asyncio waiter cannot terminate a thread. Caller cancellation
    is propagated only after draining that thread; owned stop controls remain
    reachable while an administrator waits for this lease.
    """
    worker = None
    try:
        async with read_lease(control=True):
            worker = asyncio.ensure_future(awaitable)
            cancelled = False
            while True:
                try:
                    result = await asyncio.shield(worker)
                    break
                except asyncio.CancelledError:
                    if worker.cancelled():
                        raise
                    cancelled = True
            if cancelled:
                raise asyncio.CancelledError
            return result
    finally:
        if worker is None and asyncio.iscoroutine(awaitable):
            awaitable.close()


def _owner(state, context):
    m = state.get('owner_management')
    if not m:
        return None
    owner = m['owners'].get(context['principal_id'])
    if owner is None:
        return None
    if any(owner[f] != context[f] for f in ('workspace_id','device_id','installation_id')):
        raise PermissionError('OWNER_PLACEMENT_MISMATCH')
    if 'bootstrap_resource' in context and owner['resource_id'] != context['bootstrap_resource']['resource_id']:
        raise PermissionError('OWNER_RESOURCE_MISMATCH')
    return owner


async def catalog_snapshot(arguments, metadata):
    if arguments != {}:
        raise ValueError('CATALOG_ARGUMENTS_NOT_ALLOWED')
    context = _verify(metadata)
    async with read_lease(control=True):
        state = _load()
        result = _catalog(state)
        result['owner'] = copy.deepcopy(_owner(state, context))
        return result


def _arguments(action, args):
    if not isinstance(args,dict):
        raise ValueError('INVALID_ADMIN_ARGUMENTS')
    required = set() if action == 'list' else {'target_profile_id'}
    optional = set()
    if action not in ('list','get'):
        required |= {'expected_revision','idempotency_key'}
    if action == 'create':
        required |= {'root'}
        optional = {'mode','enabled','description','execution_access'}
    elif action == 'update':
        required |= {'changes'}
    elif action == 'delete':
        optional = {'replacement_default_id'}
    if not required <= set(args) or set(args) - required - optional:
        raise ValueError('INVALID_ADMIN_ARGUMENT_FIELDS')
    if action != 'list':
        _id(args['target_profile_id'])
    if action in ('list','get'):
        return
    if not isinstance(args['expected_revision'],str) or not HEX.fullmatch(args['expected_revision']):
        raise ValueError('INVALID_EXPECTED_REVISION')
    if not _text(args['idempotency_key'],128):
        raise ValueError('INVALID_IDEMPOTENCY_KEY')
    if 'replacement_default_id' in args:
        _id(args['replacement_default_id'])
    changes = args.get('changes') if action == 'update' else ({k:args[k] for k in ('root','mode','enabled','description','execution_access') if k in args} if action == 'create' else {})
    if not isinstance(changes,dict) or (action == 'update' and not changes) or set(changes) - {'root','mode','enabled','description','execution_access'}:
        raise ValueError('INVALID_PROFILE_CHANGES')
    if 'execution_access' in changes and changes['execution_access'] not in ('disabled','developer','full'):
        raise ValueError('INVALID_PROFILE_EXECUTION_ACCESS')
    if 'mode' in changes and changes['mode'] not in ('read-only','read-write'):
        raise ValueError('INVALID_PROFILE_MODE')
    if 'enabled' in changes and type(changes['enabled']) is not bool:
        raise ValueError('INVALID_PROFILE_ENABLED')
    if 'description' in changes and (not isinstance(changes['description'],str) or len(changes['description']) > 512):
        raise ValueError('INVALID_PROFILE_DESCRIPTION')
    if 'root' in changes and not isinstance(changes['root'],str):
        raise ValueError('INVALID_PROFILE_ROOT')


def _root(value):
    if os.name != 'nt':
        raise RuntimeError('WINDOWS_PROFILE_ADMINISTRATION_REQUIRED')
    if not isinstance(value,str) or not value or not os.path.isabs(value) or value.startswith(('\\\\','//')):
        raise ValueError('LOCAL_ABSOLUTE_ROOT_REQUIRED')
    if len(value) > 32768 or not re.match(r'^[A-Za-z]:', value):
        raise ValueError('LOCAL_DRIVE_ABSOLUTE_ROOT_REQUIRED')
    p = Path(value)
    if str(p) != os.path.normpath(value) or not p.is_dir() or p == Path(p.anchor):
        raise ValueError('INVALID_PROFILE_ROOT')
    for part in (p, *p.parents):
        if part.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise PermissionError('REPARSE_PROFILE_ROOT')
    # Owner-approved ancestor directories may be profile roots. Refuse only
    # direct registration of the service-private data directories themselves
    # or their children. Per-file access to these directories remains denied
    # by fsops.guard_secret even through an approved ancestor profile.
    anchor = os.environ.get('ZAGENT_CORE_DATA_ROOT') or os.environ.get('ZAGENT_DATA_ROOT')
    if not anchor or not os.path.isabs(anchor) or not Path(anchor).is_dir():
        raise PermissionError('PRIVATE_CORE_ROOT_NOT_CONFIGURED')
    private = [Path(anchor), DATA_ROOT, CONFIG_DIR, RUNTIME_DIR, LOG_DIR, BACKUP_ROOT, UPDATE_STATE_ROOT]
    for env in ('ZAGENT_DATA_ROOT', 'ZAGENT_CORE_DATA_ROOT'):
        if os.environ.get(env):
            private.append(Path(os.environ[env]))
    for sensitive in private:
        a, b = os.path.normcase(str(p.resolve())), os.path.normcase(str(sensitive.resolve()))
        common = os.path.commonpath([a, b]) if os.path.splitdrive(a)[0] == os.path.splitdrive(b)[0] else None
        if common == b:
            raise PermissionError('PRIVATE_ROOT_DIRECT_ACCESS_DENIED')
    return str(p)


def _publish(state, expected_revision):
    # Synchronous critical section only, never held over an await. Legacy
    # writers share this lock and will reject after managed metadata appears.
    with manager._LOCK:
        if current_catalog()['revision'] != expected_revision:
            raise ValueError('REVISION_CONFLICT')
        _publish_locked(state)


def _publish_locked(state):
    _validate_state(state)
    raw = canonical(state)
    if len(raw) > MAX_BYTES:
        raise ValueError('PROFILE_STATE_TOO_LARGE')
    path = manager.PROFILES_FILE
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary,path)
        if path.read_bytes() != raw:
            raise IOError('PROFILE_COMMIT_READBACK_MISMATCH')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


_WRITER_HANDLE = None


def _claim_writer():
    global _WRITER_HANDLE
    if _WRITER_HANDLE is not None:
        return
    if os.name != 'nt':
        raise RuntimeError('WINDOWS_PROFILE_ADMINISTRATION_REQUIRED')
    import msvcrt
    path = manager.PROFILES_FILE.with_suffix('.admin.owner')
    if path.exists() and path.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise PermissionError('REPARSE_ADMIN_LOCK')
    handle = path.open('a+b')
    try:
        handle.write(b'0')
        handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except BaseException:
        handle.close()
        raise
    _WRITER_HANDLE = handle


class ProfileAdministrationService:
    async def admin_call(self, tool, arguments, metadata):
        context = _verify(metadata, tool, arguments)
        action = PROFILE_ADMIN_TOOLS[tool]
        _arguments(action, arguments)
        if action not in ('list','get'):
            _claim_writer()
        lease = read_lease() if action in ('list','get') else LEASES.write()
        async with lease:
            # Recheck deadline after waiting for admitted operations to finish.
            _verify(metadata,tool,arguments)
            state = _load()
            catalog = _catalog(state)
            owner = _owner(state,context)
            if action in ('list','get'):
                rows = catalog['profiles']
                if action == 'get':
                    rows = [r for r in rows if r['name'] == arguments['target_profile_id']]
                    if not rows:
                        raise KeyError('PROFILE_NOT_FOUND')
                return {'status':'committed','revision':catalog['revision'],'access_sync':'unchanged','profiles':rows,'owner':copy.deepcopy(owner)}
            fingerprint = digest({'tool':tool,'arguments':arguments})
            actor = digest({k:context[k] for k in ('source','actor_id','principal_id','workspace_id','device_id','installation_id')})
            managed = state.get('owner_management')
            if managed:
                for record in managed['operations']:
                    if record['actor'] == actor and record['key'] == arguments['idempotency_key']:
                        if record['digest'] != fingerprint:
                            raise ValueError('IDEMPOTENCY_CONFLICT')
                        return copy.deepcopy(record['outcome'])
            if arguments['expected_revision'] != catalog['revision']:
                raise ValueError('REVISION_CONFLICT')
            if managed is None:
                resource = context['bootstrap_resource']
                approved = {r['name'] for r in state['profiles'] if r.get('authorized_by_user') is True and r.get('enabled') is True}
                if not set(resource['allowed_profile_ids']) <= approved:
                    raise PermissionError('BOOTSTRAP_PROFILE_NOT_APPROVED')
                managed = state['owner_management'] = {'version':1,'revision':catalog['revision'],'owners':{},'generations':catalog['generations'],'operations':[]}
            if owner is None:
                if managed['owners']:
                    raise PermissionError('EXPLICIT_MANAGED_OWNER_REQUIRED')
                owner = {**copy.deepcopy(context['bootstrap_resource']), **{f:context[f] for f in ('workspace_id','device_id','installation_id')}}
                managed['owners'][context['principal_id']] = owner
            target = arguments['target_profile_id']
            rows = state['profiles']
            row = next((r for r in rows if r['name'] == target),None)
            if action == 'create':
                if row is not None:
                    raise ValueError('PROFILE_ALREADY_EXISTS')
                row = {'name':target,'root':_root(arguments['root']),'mode':arguments.get('mode','read-only'),'enabled':arguments.get('enabled',True),'description':arguments.get('description',''),
                       'execution_access':arguments.get('execution_access','disabled')}
                rows.append(row)
                owner['allowed_profile_ids'].append(target)
            else:
                if row is None:
                    raise KeyError('PROFILE_NOT_FOUND')
                if target not in owner['allowed_profile_ids']:
                    raise PermissionError('PROFILE_NOT_IN_OWNER_MEMBERSHIP')
            if action in ('create','update'):
                changes = arguments.get('changes',{})
                if 'root' in changes:
                    changes = {**changes,'root':_root(changes['root'])}
                if action == 'create' or any(k in changes and changes[k] != row.get(k) for k in ('root','mode','enabled','execution_access')):
                    managed['generations'][target] = uuid.uuid4().hex
                row.update(changes)
                if row.get('mode') != 'read-write' and row.get('execution_access','disabled') != 'disabled':
                    raise ValueError('READ_ONLY_EXECUTION_DISABLED_REQUIRED')
                if any(r is not row and os.path.normcase(r.get('root','')) == os.path.normcase(row['root']) for r in rows):
                    raise ValueError('PROFILE_ROOT_ALREADY_EXISTS')
                row.update(authorized_by_user=True, authorization_source=context['source'] + '_owner_admin', authorized_at=manager._now(), authorized_by=context['actor_id'])
            def usable(name):
                return name in owner['allowed_profile_ids'] and any(r['name'] == name and r.get('enabled') is True and r.get('authorized_by_user') is True for r in rows)
            if action == 'set_default':
                if not usable(target):
                    raise ValueError('DEFAULT_PROFILE_NOT_USABLE')
                state['active_profile'] = owner['default_profile_id'] = target
            if action == 'delete':
                replacement = arguments.get('replacement_default_id')
                needs_replacement = state['active_profile'] == target or any(o['default_profile_id'] == target for o in managed['owners'].values())
                if needs_replacement and (not replacement or replacement == target or not usable(replacement)):
                    raise ValueError('EXPLICIT_REPLACEMENT_DEFAULT_REQUIRED')
                if state['active_profile'] == target:
                    state['active_profile'] = replacement
                for o in managed['owners'].values():
                    if o['default_profile_id'] == target:
                        if replacement not in o['allowed_profile_ids']:
                            raise ValueError('REPLACEMENT_NOT_IN_OWNER_MEMBERSHIP')
                        o['default_profile_id'] = replacement
                    o['allowed_profile_ids'] = [p for p in o['allowed_profile_ids'] if p != target]
                rows.remove(row)
                del managed['generations'][target]
            revision = digest({'previous':catalog['revision'],'operation':context['operation_id'],'payload':fingerprint,'nonce':uuid.uuid4().hex})
            managed['revision'] = revision
            outcome = {'status':'committed','revision':revision,'access_sync':'committed','profile':_public(row),'owner':copy.deepcopy(owner)}
            managed['operations'] = (managed['operations'] + [{'actor':actor,'key':arguments['idempotency_key'],'digest':fingerprint,'outcome':copy.deepcopy(outcome)}])[-32:]
            _publish(state, catalog['revision'])
            return outcome


SERVICE = ProfileAdministrationService()


async def admin_call(tool, arguments, metadata):
    return await SERVICE.admin_call(tool, arguments, metadata)
