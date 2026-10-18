"""ArcMap trusted-channel regression contracts; execution deferred."""
import time
from types import SimpleNamespace
import pytest
from mcp_server.execution_context import request_meta, verify, owner_key


def context(monkeypatch, token='k'*32, **changes):
    monkeypatch.setenv('ZAGENT_INTERNAL_TOKEN', 'k'*32)
    monkeypatch.setenv('ZAGENT_DEVICE_ID', 'device')
    value = dict(context_version=1, principal_id='p', workspace_id='w', device_id='device',
                 operation_id='op', request_id='r', trace_id='t', deadline=time.time()+30,
                 effective_access='read', effective_resources=[dict(resource_id='map',kind='arcmap')])
    value.update(changes)
    return SimpleNamespace(request_context=SimpleNamespace(
        request=SimpleNamespace(headers={'x-zagent-internal-token':token}),
        meta={'zagent.execution_context':value}))


def test_no_public_metadata_authority(monkeypatch):
    with pytest.raises(PermissionError):
        verify(context(monkeypatch).request_context.meta, 'arcmap_ping', {})
    with pytest.raises(PermissionError):
        request_meta(context(monkeypatch,token='wrong'))


def test_expiry_target_and_version_fail_closed(monkeypatch):
    assert verify(request_meta(context(monkeypatch)), 'arcmap_ping', {})['workspace_id']=='w'
    for changes in ({'deadline':0}, {'context_version':2}, {'device_id':'other'}, {'effective_resources':[]}):
        with pytest.raises(PermissionError):
            verify(request_meta(context(monkeypatch,**changes)), 'arcmap_ping', {})


def test_owner_is_not_transport_handle():
    assert owner_key(dict(principal_id='p',workspace_id='w',session_id='one')) == owner_key(dict(principal_id='p',workspace_id='w',session_id='two'))
    assert owner_key(dict(principal_id='p',workspace_id='w')) != owner_key(dict(principal_id='p',workspace_id='other'))
