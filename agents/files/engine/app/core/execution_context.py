"""Trusted internal channel, separate from public OAuth and public MCP metadata.

Core provisions ZAGENT_INTERNAL_TOKEN; Router forwards it only to private
backends. A public _meta dictionary can never construct TrustedMetadata.
"""
import hashlib
import hmac
import json
import math
import os
import time
from contextvars import ContextVar

CURRENT: ContextVar[dict | None] = ContextVar('zagent_verified_execution_context', default=None)


class VerifiedContext(dict):
    """In-process authority marker, never deserialized from public input."""


class TrustedMetadata(dict):
    """Only request_meta constructs this after authenticating HTTP headers."""


def owner_key(context):
    # Compatibility for direct private/local callers of this historical utility.
    # Remote verify() always requires context_version + one resource BEFORE
    # reaching here, so malformed remote authority cannot take this branch.
    if 'context_version' not in context and 'effective_resources' not in context:
        encoded = json.dumps([context['principal_id'], context['workspace_id']],
                             ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        return 'owner_v1_' + hashlib.sha256(encoded).hexdigest()
    resource = context['effective_resources'][0]
    owner = [context['principal_id'], context['workspace_id'],
             resource['resource_id'], resource['profile_id'],
             context['device_id'], context['installation_id']]
    if 'profile_generation' in resource:
        owner.append(resource['profile_generation'])
    encoded = json.dumps(owner, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return 'owner_files_v2_' + hashlib.sha256(encoded).hexdigest()


def request_meta(ctx):
    key = os.environ.get('ZAGENT_INTERNAL_TOKEN', '').encode('utf-8')
    if len(key) < 32:
        raise PermissionError('INTERNAL_CHANNEL_NOT_CONFIGURED')
    try:
        request = ctx.request_context.request
        supplied = request.headers.get('x-zagent-internal-token', '').encode('utf-8')
    except (AttributeError, ValueError, TypeError):
        raise PermissionError('AUTHENTICATED_INTERNAL_CHANNEL_REQUIRED')
    if not hmac.compare_digest(key, supplied):
        raise PermissionError('INVALID_INTERNAL_TOKEN')
    raw = ctx.request_context.meta
    meta = raw.model_dump(by_alias=True) if hasattr(raw, 'model_dump') else dict(raw or {})
    return TrustedMetadata(meta)


# Deliberately closed native catalog. Commands have a separate owner-managed gate.
NATIVE_READ = frozenset({'ping', 'runtime_info', 'get_root', 'exists', 'list', 'tree',
    'stat', 'read', 'read_bytes_b64', 'search', 'hash', 'diff', 'syntax_check', 'backup_list'})
NATIVE_WRITE = frozenset({'write', 'append', 'patch', 'mkdir', 'copy', 'move', 'delete',
    'backup', 'restore', 'zip', 'unzip'})
READ_CONTROLS = frozenset({'workspace_status', 'workspace_list', 'operation_status',
    'operation_list', 'capabilities'})
WRITE_CONTROLS = frozenset({'workspace_open', 'workspace_switch', 'operation_cancel'})
COMMAND_TOOLS = frozenset({'files_command_capabilities', 'files_command_cancel',
    'files_exec_command', 'files_powershell_run', 'files_node', 'files_npm', 'files_npx',
    'files_git', 'files_build', 'files_test', 'files_process_list', 'files_process_start',
    'files_process_stop'})
ALLOWLIST_READ = frozenset({'allowlist_list'})
ALLOWLIST_WRITE = frozenset({'allowlist_add', 'allowlist_remove', 'allowlist_replace'})
AUTHORITY_ARGUMENTS = frozenset({'_meta', 'metadata', 'execution_context', 'principal_id',
    'owner_session_id', 'session_id', 'scopes', 'grant_id', 'policy_revision', 'device_id',
    'target_device_id', 'installation_id', 'request_id', 'trace_id', 'task_id',
    'resource_key', 'access_mode', 'effective_access', 'effective_resources', 'files_resource',
    'operator_alias', 'profile_id', 'source_profile', 'destination_profile',
    'public_tool', 'required_scope', 'deadline', 'expires_at', 'fencing_epoch', 'lease_owner'})


def _fingerprint(arguments):
    return hashlib.sha256(json.dumps(arguments, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _operation(tool, arguments):
    if not isinstance(tool, str) or not tool.startswith('files_') or not isinstance(arguments, dict):
        raise PermissionError('UNKNOWN_FILES_OPERATION')
    op = tool[6:]
    if op in {'copy_between_profiles', 'copy_batch_between_profiles'}:
        raise PermissionError('CROSS_PROFILE_COPY_DISABLED')
    if op.startswith('profile_') or op.startswith('update_'):
        raise PermissionError('MANAGEMENT_PLANE_ONLY')
    forbidden = set(AUTHORITY_ARGUMENTS)
    if op in READ_CONTROLS | WRITE_CONTROLS | ALLOWLIST_READ | ALLOWLIST_WRITE or tool in COMMAND_TOOLS:
        forbidden.discard('profile_id')  # selection only, checked against trusted resource
    if op in {'operation_cancel', 'command_cancel'}:
        forbidden.discard('task_id')  # target selector only; actual owner is trusted context
    if forbidden.intersection(arguments):
        raise PermissionError('CLIENT_AUTHORITY_NOT_ALLOWED')
    if 'workspace_id' in arguments and op not in READ_CONTROLS | WRITE_CONTROLS:
        raise PermissionError('CLIENT_AUTHORITY_NOT_ALLOWED')
    if op == 'execute':
        if set(arguments) != {'operation', 'arguments'}:
            raise PermissionError('CLIENT_AUTHORITY_NOT_ALLOWED')
        inner = arguments['operation']
        if not isinstance(inner, str):
            raise PermissionError('UNKNOWN_FILES_OPERATION')
        inner = inner.removeprefix('files_')
        if (not isinstance(arguments['arguments'], dict)
                or {'profile', 'profile_id', 'active_profile', 'profiles'}.intersection(arguments['arguments'])):
            raise PermissionError('CLIENT_AUTHORITY_NOT_ALLOWED')
        if inner not in NATIVE_READ | NATIVE_WRITE:
            if inner in {'copy_between_profiles', 'copy_batch_between_profiles'}:
                raise PermissionError('CROSS_PROFILE_COPY_DISABLED')
            raise PermissionError('UNKNOWN_FILES_OPERATION')
        inner_op, _, _ = _operation('files_' + inner, arguments['arguments'])
        return inner_op, 'files:write', 'write'
    if tool in COMMAND_TOOLS:
        return op, 'files:execute', 'write'
    if op in NATIVE_READ | READ_CONTROLS | ALLOWLIST_READ:
        return op, 'files:read', 'read'
    if op in NATIVE_WRITE | WRITE_CONTROLS | ALLOWLIST_WRITE:
        return op, 'files:write', 'write'
    raise PermissionError('UNKNOWN_FILES_OPERATION')


def _check_scope(context, scope, access):
    scopes = context.get('scopes')
    if (context.get('required_scope') != scope or not isinstance(scopes, list)
            or not all(isinstance(s, str) for s in scopes) or scope not in scopes
            or (scope == 'files:execute' and 'files:write' not in scopes)):
        raise PermissionError('CANONICAL_SCOPE_REQUIRED')
    if context.get('effective_access') != access:
        raise PermissionError('OPERATION_ACCESS_MISMATCH')


def validate_profile(context, profile):
    """Compare approved current local state; a name never supplies approval."""
    if (profile.get('name') != context.get('profile_id')
            or profile.get('enabled') is not True or profile.get('authorized_by_user') is not True
            or profile.get('mode') not in ('read-only', 'read-write')):
        raise PermissionError('FILES_PROFILE_NOT_APPROVED')
    resource = context['effective_resources'][0]
    from app.profiles.administration import profile_generation
    from app.profiles import manager
    state = manager.load_profiles()
    if ('owner_management' in state or 'profile_generation' in resource) and resource.get('profile_generation') != profile_generation(profile, state):
        raise PermissionError('PROFILE_GENERATION_MISMATCH')
    if context['effective_access'] == 'write' and profile['mode'] != 'read-write':
        raise PermissionError('WRITE_PROFILE_REQUIRED')
    for field in ('device_id', 'installation_id'):
        if field in profile and profile[field] != context.get(field):
            raise PermissionError('PROFILE_IDENTITY_MISMATCH')
    return profile


def authorize_operation(context, operation, arguments):
    """Recheck native call at execution, including exact wrapper inner arguments."""
    if not isinstance(context, VerifiedContext):
        raise PermissionError('AUTHENTICATED_EXECUTION_CONTEXT_REQUIRED')
    if time.time() >= context['expires_at']:
        raise PermissionError('CONTEXT_EXPIRED')
    op, scope, access = _operation('files_' + operation.removeprefix('files_'), arguments)
    if (op != context.get('_authorized_operation')
            or _fingerprint(arguments) != context.get('_arguments_fingerprint')):
        raise PermissionError('CONTEXT_OPERATION_MISMATCH')
    if context.get('public_tool') == 'files_execute':
        # Canonical wrapper always requires write, even for an inner read.
        scope, access = 'files:write', 'write'
    elif context.get('public_tool') != 'files_' + op:
        raise PermissionError('CONTEXT_TOOL_MISMATCH')
    _check_scope(context, scope, access)
    return op


def verify(meta, tool, arguments):
    if not isinstance(meta, TrustedMetadata):
        raise PermissionError('AUTHENTICATED_INTERNAL_CHANNEL_REQUIRED')
    context = meta.get('zagent.execution_context')
    if not isinstance(context, dict):
        raise PermissionError('AUTHENTICATED_EXECUTION_CONTEXT_REQUIRED')
    if type(context.get('context_version')) is not int or context['context_version'] != 1:
        raise PermissionError('UNSUPPORTED_CONTEXT_VERSION')
    for field in ('principal_id', 'workspace_id', 'device_id', 'operation_id', 'request_id', 'trace_id'):
        value = context.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > 256:
            raise PermissionError('INVALID_CONTEXT_' + field.upper())
    expiry = context.get('deadline')
    if not isinstance(expiry, (int, float)) or isinstance(expiry, bool):
        raise PermissionError('INVALID_CONTEXT_DEADLINE')
    now = time.time()
    if not math.isfinite(expiry) or not now < expiry <= now + 3600:
        raise PermissionError('CONTEXT_EXPIRED_OR_INVALID')
    local = os.environ.get('ZAGENT_DEVICE_ID', '').strip()
    if not local or context['device_id'] != local:
        raise PermissionError('IDENTITY_MISMATCH_OR_DEVICE_NOT_CONFIGURED')
    installation = os.environ.get('ZAGENT_INSTALLATION_ID', '').strip()
    if installation and context.get('installation_id') != installation:
        raise PermissionError('INSTALLATION_IDENTITY_MISMATCH')
    if context.get('public_tool') != tool:
        raise PermissionError('CONTEXT_TOOL_MISMATCH')
    op, scope, access = _operation(tool, arguments)
    _check_scope(context, scope, access)
    resources = context.get('effective_resources')
    if not isinstance(resources, list) or len(resources) != 1:
        raise PermissionError('FILES_RESOURCE_MUST_BE_UNIQUE')
    resource = resources[0]
    if (not isinstance(resource, dict) or resource.get('kind') != 'files'
            or not all(isinstance(resource.get(k), str) and resource[k].strip()
                       and len(resource[k]) <= 256 for k in ('resource_id', 'profile_id'))
            or resource.get('revoked', False) is not False):
        raise PermissionError('INVALID_FILES_RESOURCE_SCOPE')
    for field in ('device_id', 'installation_id'):
        if field in resource and resource[field] != context.get(field):
            raise PermissionError('RESOURCE_IDENTITY_MISMATCH')
    profile_id = resource['profile_id']
    if context.get('profile_id', profile_id) != profile_id:
        raise PermissionError('PROFILE_NOT_IN_RESOURCE_SCOPE')
    for field in ('profile_id', 'active_profile', 'profile'):
        if arguments.get(field) is not None and arguments[field] != profile_id:
            raise PermissionError('PROFILE_NOT_IN_RESOURCE_SCOPE')
    if 'profiles' in arguments and arguments['profiles'] != [profile_id]:
        raise PermissionError('PROFILE_NOT_IN_RESOURCE_SCOPE')
    if 'workspace_id' in arguments and arguments['workspace_id'] != context['workspace_id']:
        raise PermissionError('WORKSPACE_SCOPE_MISMATCH')
    result = VerifiedContext(json.loads(json.dumps(context, allow_nan=False)))
    result['expires_at'] = expiry
    result['profile_id'] = profile_id
    result['session_id'] = owner_key(context)  # legacy column, not transport identity
    result['_authorized_operation'] = op
    actual_arguments = arguments['arguments'] if tool == 'files_execute' else arguments
    result['_arguments_fingerprint'] = _fingerprint(actual_arguments)
    result['_argument_keys'] = list(actual_arguments)
    result.pop('operator_alias', None)
    return result


def current():
    value = CURRENT.get()
    if not isinstance(value, VerifiedContext):
        raise PermissionError('AUTHENTICATED_EXECUTION_CONTEXT_REQUIRED')
    if time.time() >= value['expires_at']:
        raise PermissionError('CONTEXT_EXPIRED')
    return value
