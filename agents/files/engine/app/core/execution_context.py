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

CURRENT = ContextVar('zagent_verified_execution_context', default=None)


class VerifiedContext(dict):
    """In-process authority marker, never deserialized from public input."""


class TrustedMetadata(dict):
    """Only request_meta constructs this after authenticating HTTP headers."""


def owner_key(context):
    encoded = json.dumps([context['principal_id'], context['workspace_id']],
                         ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return 'owner_v1_' + hashlib.sha256(encoded).hexdigest()


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
    resources = context.get('effective_resources')
    if not isinstance(resources, list) or not resources or len(resources) > 128:
        raise PermissionError('RESOURCE_SCOPE_REQUIRED')
    for resource in resources:
        if not isinstance(resource, dict) or not all(isinstance(resource.get(k), str) and resource[k] for k in ('resource_id', 'kind')):
            raise PermissionError('INVALID_RESOURCE_SCOPE')
    if context.get('effective_access') not in ('read', 'write'):
        raise PermissionError('INVALID_ACCESS_SCOPE')
    result = VerifiedContext(context)
    result['expires_at'] = expiry
    result['session_id'] = owner_key(context)  # legacy column, not transport identity
    result.pop('operator_alias', None)
    return result


def current():
    value = CURRENT.get()
    if not isinstance(value, VerifiedContext):
        raise PermissionError('AUTHENTICATED_EXECUTION_CONTEXT_REQUIRED')
    if time.time() >= value['expires_at']:
        raise PermissionError('CONTEXT_EXPIRED')
    return value
