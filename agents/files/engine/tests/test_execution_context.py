"""Internal-channel/authority regression source; execution deferred to Windows."""
import time
from types import SimpleNamespace
import pytest
from app.core.execution_context import verify, request_meta, owner_key


def invocation(monkeypatch, token='k' * 32, **changes):
    monkeypatch.setenv('ZAGENT_INTERNAL_TOKEN', 'k' * 32)
    monkeypatch.setenv('ZAGENT_DEVICE_ID', 'device')
    monkeypatch.setenv('ZAGENT_INSTALLATION_ID', 'install')
    context = dict(context_version=1, principal_id='principal', workspace_id='workspace',
                   device_id='device', operation_id='op', request_id='request', trace_id='trace',
                   deadline=time.time() + 30, effective_access='read',
                   public_tool='files_read', required_scope='files:read', scopes=['files:read'],
                   installation_id='install',
                   effective_resources=[dict(resource_id='root', kind='files', profile_id='approved')])
    context.update(changes)
    return SimpleNamespace(request_context=SimpleNamespace(
        request=SimpleNamespace(headers={'x-zagent-internal-token': token}),
        meta={'zagent.execution_context': context}))


def test_public_meta_is_not_authority(monkeypatch):
    ctx = invocation(monkeypatch)
    with pytest.raises(PermissionError):
        verify(ctx.request_context.meta, 'files_read', {})


def test_only_authenticated_http_channel_accepts_authority(monkeypatch):
    ctx = invocation(monkeypatch)
    assert verify(request_meta(ctx), 'files_read', {})['workspace_id'] == 'workspace'
    for token in ('', 'wrong', 'k' * 31):
        with pytest.raises(PermissionError):
            request_meta(invocation(monkeypatch, token=token))
    monkeypatch.delenv('ZAGENT_INTERNAL_TOKEN')
    with pytest.raises(PermissionError):
        request_meta(ctx)


def test_expired_version_resource_and_wrong_device_fail(monkeypatch):
    for changes in ({'deadline': time.time() - 1}, {'deadline': float('nan')},
                    {'device_id': 'other'}, {'context_version': 2},
                    {'effective_resources': ['installation:unscoped']},
                    {'effective_access': 'admin'}):
        with pytest.raises(PermissionError):
            verify(request_meta(invocation(monkeypatch, **changes)), 'files_read', {})


def test_namespace_is_principal_workspace_not_chat():
    first = {'principal_id': 'p', 'workspace_id': 'w', 'session_id': 'chat-one'}
    assert owner_key(first) == owner_key(dict(first, session_id='chat-two'))
    assert owner_key(first) != owner_key(dict(first, workspace_id='other'))
    assert owner_key(first) != owner_key(dict(first, principal_id='other'))
