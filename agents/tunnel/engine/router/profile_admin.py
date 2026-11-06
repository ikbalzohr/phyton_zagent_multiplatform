"""Explicit owner administration authority, disjoint from native Files v1."""
from __future__ import annotations
import math
import re
import time
import uuid
from copy import deepcopy
from .access import AuthorizationError, digest

PROFILE_ADMIN_SCOPES = {
    'files_profile_admin_list': 'files:read',
    'files_profile_admin_get': 'files:read',
    'files_profile_admin_create': 'files:write',
    'files_profile_admin_update': 'files:write',
    'files_profile_admin_delete': 'files:write',
    'files_profile_admin_set_default': 'files:write',
}
ACTIONS = frozenset({'list', 'get', 'create', 'update', 'delete', 'set_default'})
CATALOG_TOOL = 'files_profile_catalog_snapshot'
ID_SCHEMA = {'type': 'string', 'pattern': r'^[A-Za-z0-9_-]{1,256}$', 'minLength': 1, 'maxLength': 256}
REV_SCHEMA = {'type': 'string', 'pattern': r'^[0-9a-fA-F]{64}$'}


def _deny():
    raise AuthorizationError('PROFILE_MANAGEMENT_NOT_AUTHORIZED', 403)


def _string(value):
    return isinstance(value, str) and bool(value) and len(value) <= 256 and value == value.strip() and not any(ord(c) < 32 for c in value)


def require_profile_management(auth, placement, authorizer, tool, *, check_authority=True):
    placement.validate()
    if tool not in PROFILE_ADMIN_SCOPES:
        _deny()
    grant = authorizer.current_grant(auth)
    if check_authority:
        auth.require(PROFILE_ADMIN_SCOPES[tool], tool)
        # Read/write authority is necessary but never sufficient.
        if PROFILE_ADMIN_SCOPES[tool] not in grant.get('scopes', []) or (tool not in grant.get('tools', []) and '*' not in grant.get('tools', [])):
            _deny()
    cap = grant.get('profile_management')
    if (not isinstance(cap, dict) or set(cap) != {'version', 'enabled', 'workspace_id', 'device_id', 'installation_id', 'actions'}
            or type(cap['version']) is not int or cap['version'] != 1 or cap['enabled'] is not True
            or any(not _string(cap[k]) for k in ('workspace_id', 'device_id', 'installation_id'))
            or cap['workspace_id'] != auth.workspace_id or cap['device_id'] != placement.device_id
            or cap['installation_id'] != placement.installation_id
            or not isinstance(cap['actions'], list) or not 1 <= len(cap['actions']) <= 6
            or any(not isinstance(a, str) or a not in ACTIONS for a in cap['actions'])
            or len(set(cap['actions'])) != len(cap['actions'])
            or tool.removeprefix('files_profile_admin_') not in cap['actions']):
        _deny()
    expiry = grant.get('expires_at')
    if type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry <= time.time() or grant.get('revoked', False) is not False:
        _deny()
    return cap


def has_owner_capability(auth, placement, authorizer):
    grant = authorizer.current_grant(auth)
    cap = grant.get('profile_management')
    if 'profile_management' not in grant:
        return False
    # A present malformed/disabled capability must not silently become legacy.
    actions = cap.get('actions') if isinstance(cap, dict) else None
    if not isinstance(actions, list) or not actions:
        _deny()
    for action in actions:
        if not isinstance(action, str):
            _deny()
        require_profile_management(auth, placement, authorizer, 'files_profile_admin_' + action, check_authority=False)
    return True


def tool_schema(name):
    action = name.removeprefix('files_profile_admin_')
    props = {} if action == 'list' else {'target_profile_id': deepcopy(ID_SCHEMA)}
    required = [] if action == 'list' else ['target_profile_id']
    row = {'root': {'type': 'string', 'minLength': 1, 'maxLength': 32768},
           'mode': {'type': 'string', 'enum': ['read-only', 'read-write'], 'default': 'read-only'},
           'enabled': {'type': 'boolean', 'default': True},
           'description': {'type': 'string', 'maxLength': 512},
           'execution_access': {'type': 'string', 'enum': ['disabled','developer','full'], 'default': 'disabled'}}
    if action == 'create':
        props.update(row); required.append('root')
    elif action == 'update':
        props['changes'] = {'type': 'object', 'properties': row, 'minProperties': 1, 'additionalProperties': False}
        required.append('changes')
    elif action == 'delete':
        props['replacement_default_id'] = deepcopy(ID_SCHEMA)
    if action not in {'list', 'get'}:
        props.update({'expected_revision': deepcopy(REV_SCHEMA), 'idempotency_key': {'type': 'string', 'minLength': 1, 'maxLength': 128}})
        required += ['expected_revision', 'idempotency_key']
    return {'type': 'object', 'properties': props, 'required': required, 'additionalProperties': False}


def bootstrap_resource(auth, placement, authorizer):
    resource = authorizer.current_grant(auth).get('files_resource')
    if (not isinstance(resource, dict) or resource.get('kind') != 'files' or resource.get('revoked', False) is not False
            or resource.get('device_id') != placement.device_id or resource.get('installation_id') != placement.installation_id
            or not _string(resource.get('resource_id'))):
        _deny()
    default = resource.get('profile_id')
    allowed = resource.get('allowed_profile_ids', [default])
    if (not isinstance(allowed, list) or not 1 <= len(allowed) <= 128
            or any(not isinstance(p, str) or re.fullmatch(ID_SCHEMA['pattern'], p) is None for p in allowed)
            or len(set(allowed)) != len(allowed) or default not in allowed):
        _deny()
    return {'resource_id': resource['resource_id'], 'default_profile_id': default, 'allowed_profile_ids': list(allowed)}


def catalog_context(auth, placement):
    placement.validate()
    if auth.expires_at <= time.time() or not _string(auth.principal_id) or not _string(auth.workspace_id):
        _deny()
    return {'version': 1, 'source': 'oauth', 'actor_id': auth.principal_id, 'principal_id': auth.principal_id,
            'workspace_id': auth.workspace_id, 'device_id': placement.device_id, 'installation_id': placement.installation_id,
            'deadline': min(auth.expires_at, time.time() + 30)}


def new_admin_context(auth, placement, authorizer, tool, arguments):
    cap = require_profile_management(auth, placement, authorizer, tool)
    request = 'req_' + uuid.uuid4().hex
    operation = 'op_' + uuid.uuid4().hex
    envelope = {**catalog_context(auth, placement), 'action': tool.removeprefix('files_profile_admin_'),
                'public_tool': tool, 'request_id': request, 'operation_id': operation,
                'deadline': min(auth.expires_at, time.time()+300), 'capability_revision': digest(cap),
                'payload_digest': digest(arguments), 'bootstrap_resource': bootstrap_resource(auth, placement, authorizer)}
    return {'profile_admin_context': envelope, 'principal_id': auth.principal_id, 'workspace_id': auth.workspace_id,
            'device_id': placement.device_id, 'installation_id': placement.installation_id,
            'request_id': request, 'trace_id': 'trc_' + uuid.uuid4().hex, 'operation_id': operation,
            'task_id': 'tsk_' + uuid.uuid4().hex, 'deadline': envelope['deadline'],
            'policy_revision': auth.policy_revision, 'public_tool': tool, 'required_scope': PROFILE_ADMIN_SCOPES[tool],
            'effective_access': 'write', 'effective_resources': [{'kind': 'profile_admin', 'resource_id': 'installation:'+placement.installation_id}]}


def revalidate_admin(context, auth, placement, authorizer):
    tool = context.get('public_tool')
    cap = require_profile_management(auth, placement, authorizer, tool)
    envelope = context.get('profile_admin_context')
    fields = {'version','source','actor_id','principal_id','workspace_id','device_id','installation_id',
              'action','public_tool','request_id','operation_id','deadline','capability_revision','payload_digest','bootstrap_resource'}
    if (not isinstance(envelope, dict) or set(envelope) != fields or type(envelope.get('version')) is not int or envelope['version'] != 1
            or envelope.get('request_id') != context.get('request_id') or envelope.get('operation_id') != context.get('operation_id')
            or envelope.get('deadline') != context.get('deadline')
            or not _string(envelope.get('request_id')) or not _string(envelope.get('operation_id'))
            or not isinstance(envelope.get('payload_digest'), str) or re.fullmatch(r'[0-9a-fA-F]{64}', envelope['payload_digest']) is None
            or envelope.get('capability_revision') != digest(cap)
            or envelope.get('bootstrap_resource') != bootstrap_resource(auth, placement, authorizer)
            or envelope.get('source') != 'oauth' or envelope.get('actor_id') != auth.principal_id
            or envelope.get('principal_id') != auth.principal_id or envelope.get('workspace_id') != auth.workspace_id
            or envelope.get('device_id') != placement.device_id or envelope.get('installation_id') != placement.installation_id
            or envelope.get('public_tool') != tool or envelope.get('action') != tool.removeprefix('files_profile_admin_')
            or type(envelope.get('deadline')) not in (int, float) or not math.isfinite(envelope['deadline'])
            or not time.time() < envelope['deadline'] <= time.time()+3600):
        _deny()


def validate_catalog(snapshot, auth, placement, authorizer):
    """Use only authenticated backend state; unknown shape/placement fails closed."""
    if (not isinstance(snapshot, dict) or set(snapshot) != {'managed','revision','profiles','generations','owner'}
            or type(snapshot.get('managed')) is not bool or (not snapshot['managed'] and snapshot.get('owner') is not None)
            or not isinstance(snapshot.get('revision'), str) or re.fullmatch(r'[0-9a-fA-F]{64}', snapshot['revision']) is None
            or not isinstance(snapshot.get('profiles'), list) or not isinstance(snapshot.get('generations'), dict)
            or 'owner' not in snapshot):
        raise AuthorizationError('PROFILE_CATALOG_INVALID', 403)
    generations = snapshot['generations']
    approved = {}
    seen = set()
    for row in snapshot['profiles']:
        if not isinstance(row, dict):
            _deny()
        pid = row.get('name')
        if not isinstance(pid, str) or re.fullmatch(ID_SCHEMA['pattern'], pid) is None or pid in seen:
            _deny()
        seen.add(pid)
        generation = generations.get(pid)
        if not _string(generation):
            _deny()
        if row.get('authorized_by_user') is True and row.get('enabled') is True:
            approved[pid] = generation
    if set(generations) != seen:
        _deny()
    resource = bootstrap_resource(auth, placement, authorizer)
    owner = snapshot['owner']
    if has_owner_capability(auth, placement, authorizer) and owner is not None:
        if (not isinstance(owner, dict) or set(owner) != {'workspace_id', 'device_id', 'installation_id', 'resource_id', 'default_profile_id', 'allowed_profile_ids'}
                or owner['workspace_id'] != auth.workspace_id or owner['device_id'] != placement.device_id
                or owner['installation_id'] != placement.installation_id or owner['resource_id'] != resource['resource_id']):
            _deny()
        resource = {k: owner[k] for k in ('resource_id', 'default_profile_id', 'allowed_profile_ids')}
    ids = resource['allowed_profile_ids']
    if (not isinstance(ids, list) or not 1 <= len(ids) <= 512 or any(not isinstance(p, str) or re.fullmatch(ID_SCHEMA['pattern'], p) is None for p in ids)
            or len(set(ids)) != len(ids) or resource['default_profile_id'] not in ids):
        _deny()
    return {**resource, 'allowed_profile_ids': [p for p in ids if p in approved], 'generations': approved}
