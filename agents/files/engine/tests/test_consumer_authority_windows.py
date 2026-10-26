"""Windows regression fixtures; NOT_RUN on the source-editing VPS.
Run with the Files isolated interpreter and disposable CONFIG_DIR/DATA_ROOT.
"""
import os
import subprocess
import time
from types import SimpleNamespace

import pytest
from app.core.execution_context import request_meta, verify, authorize_operation

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='owner Windows validation only')


def signed(monkeypatch, tool='files_read', access='read', scope='files:read', **changes):
    # Authenticated internal transport, not a public _meta signature scheme.
    monkeypatch.setenv('ZAGENT_INTERNAL_TOKEN', 'k' * 32)
    monkeypatch.setenv('ZAGENT_DEVICE_ID', 'device')
    monkeypatch.setenv('ZAGENT_INSTALLATION_ID', 'install')
    value = dict(context_version=1, principal_id='p', workspace_id='w',
                 device_id='device', installation_id='install', operation_id='op',
                 request_id='r', trace_id='t', deadline=time.time() + 60,
                 effective_access=access, scopes=[scope], required_scope=scope,
                 public_tool=tool, effective_resources=[dict(resource_id='files:approved',
                 kind='files', profile_id='approved')])
    value.update(changes)
    ctx = SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(
        headers={'x-zagent-internal-token': 'k' * 32}), meta={'zagent.execution_context': value}))
    return request_meta(ctx)


@pytest.mark.parametrize('service_id', ['zagent_files', 'zagent_files_v3'])
@pytest.mark.parametrize('tool,arguments,access,scope', [
    ('files_exists', {'path': 'a'}, 'read', 'files:read'),
    ('files_write', {'path': 'a', 'content': 'b'}, 'write', 'files:write'),
    ('files_execute', {'operation': 'write', 'arguments': {'path': 'a', 'content': 'b'}}, 'write', 'files:write'),
])
def test_router_files_transport_preserves_verified_operation_payload(monkeypatch, service_id, tool, arguments, access, scope):
    # Exercise the REAL Router serializer and consumer verification together.
    # Only private HTTP transport is replaced; no service/journal is started.
    import asyncio
    from pathlib import Path
    tunnel = Path(__file__).resolve().parents[4] / 'agents/tunnel/engine'
    monkeypatch.syspath_prepend(str(tunnel))
    meta = signed(monkeypatch, tool, access, scope)
    from router.registry import MCPRegistry, UpstreamState
    registry = object.__new__(MCPRegistry)
    registry.states = {service_id: UpstreamState(service={'id': service_id}, tools=[{
        'name': tool, 'inputSchema': {'properties': {'metadata': {}, 'path': {}}},
        '_meta': {'zagent.capability': {'operation': tool}},
    }])}
    context = SimpleNamespace(execution_context=meta['zagent.execution_context'],
        session_id='owner', request_id='r', task_id='task', trace_id='t',
        idempotency_key='', resource_key='installation:install', access_mode='write',
        priority=2, profile_id='approved', target_device_id='device')
    async def initialized(state):
        return None
    async def post(state, payload, **kwargs):
        params = payload['params']
        assert params['_meta']['zagent.execution_context'] == context.execution_context
        authority = verify(meta, tool, params['arguments'])
        actual = dict(params['arguments'])
        actual.pop('metadata', None)  # real registered wrapper's transport stripping
        operation = tool[6:]
        if operation == 'execute':
            operation, actual = actual['operation'], actual['arguments']
        assert authorize_operation(authority, operation, actual) == operation
        assert params['arguments'] == arguments
        return {'result': {'content': [], 'isError': False}}
    registry.ensure_initialized = initialized
    registry._post = post
    asyncio.run(registry.invoke(service_id, tool, arguments, context))


def test_public_router_rejects_metadata_authority(monkeypatch):
    from pathlib import Path
    tunnel = Path(__file__).resolve().parents[4] / 'agents/tunnel/engine'
    monkeypatch.syspath_prepend(str(tunnel))
    from router.execution_context import reject_authority
    for metadata in (None, {}, {'effective_access': 'write'}):
        with pytest.raises(ValueError, match='CLIENT_AUTHORITY_NOT_ALLOWED'):
            reject_authority({'path': 'a', 'metadata': metadata})


@pytest.mark.parametrize('tool', ['files_workspace_open', 'files_workspace_status',
    'files_workspace_switch', 'files_operation_status', 'files_operation_cancel', 'files_operation_list'])
def test_workspace_selector_is_bound_to_authenticated_workspace(monkeypatch, tool):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[4] / 'agents/tunnel/engine'))
    from router.execution_context import authority_arguments, reject_authority
    from router.access import AuthorizationError
    args = {'workspace_id': 'w'}
    filtered = authority_arguments(tool, args, 'w')
    reject_authority(filtered)
    assert args == {'workspace_id': 'w'}  # selector must still reach the domain handler
    with pytest.raises(AuthorizationError, match='WORKSPACE_SCOPE_MISMATCH'):
        authority_arguments(tool, {'workspace_id': 'other'}, 'w')
    for injected in ('metadata', 'session_id', 'principal_id', 'execution_context'):
        with pytest.raises(ValueError, match='CLIENT_AUTHORITY_NOT_ALLOWED'):
            reject_authority(authority_arguments(tool, dict(args, **{injected: 'spoof'}), 'w'))
    with pytest.raises(ValueError, match='CLIENT_AUTHORITY_NOT_ALLOWED'):
        reject_authority(authority_arguments('files_read', args, 'w'))


def test_read_and_write_canonical_authority(monkeypatch):
    assert verify(signed(monkeypatch), 'files_read', {'path': 'a'})['profile_id'] == 'approved'
    assert verify(signed(monkeypatch, 'files_write', 'write', 'files:write'),
                  'files_write', {'path': 'a', 'content': 'b'})['effective_access'] == 'write'
    for changes in ({'required_scope': 'files:write'}, {'scopes': ['files:write']},
                    {'effective_access': 'write'}, {'public_tool': 'files_stat'},
                    {'installation_id': 'other'}, {'device_id': 'other'}):
        with pytest.raises(PermissionError):
            verify(signed(monkeypatch, **changes), 'files_read', {})


@pytest.mark.parametrize('arguments', [{'metadata': {}}, {'_meta': {}},
    {'profile_id': 'other'}, {'principal_id': 'other'}, {'effective_access': 'write'}])
def test_arguments_cannot_inject_authority(monkeypatch, arguments):
    with pytest.raises(PermissionError):
        verify(signed(monkeypatch), 'files_read', arguments)


def test_mixed_unknown_duplicate_and_cross_profile_resources_fail(monkeypatch):
    resource = dict(resource_id='r', kind='files', profile_id='approved')
    for resources in ([resource, resource], [dict(resource, kind='browser')],
                      [dict(resource, profile_id='')], [dict(resource, device_id='other')]):
        with pytest.raises(PermissionError):
            verify(signed(monkeypatch, effective_resources=resources), 'files_read', {})
    for op in ('profile_request_add', 'copy_between_profiles',
               'copy_batch_between_profiles', 'execute', 'exec_command', 'made_up'):
        with pytest.raises(PermissionError):
            verify(signed(monkeypatch, 'files_execute'), 'files_execute',
                   {'operation': op, 'arguments': {}})


def test_wrapper_inner_scope_and_operation_cannot_change(monkeypatch):
    args = {'operation': 'write', 'arguments': {'path': 'a', 'content': 'b'}}
    with pytest.raises(PermissionError):
        verify(signed(monkeypatch, 'files_execute'), 'files_execute', args)
    authority = verify(signed(monkeypatch, 'files_execute', 'write', 'files:write'), 'files_execute', args)
    with pytest.raises(PermissionError):
        authorize_operation(authority, 'delete', {'path': 'a'})
    with pytest.raises(PermissionError):
        authorize_operation(authority, 'write', {'path': 'different', 'content': 'b'})


def test_wrapper_always_requires_canonical_write_scope_even_for_read(monkeypatch):
    args = {'operation': 'read', 'arguments': {'path': 'a'}}
    with pytest.raises(PermissionError):
        verify(signed(monkeypatch, 'files_execute'), 'files_execute', args)
    authority = verify(signed(monkeypatch, 'files_execute', 'write', 'files:write'), 'files_execute', args)
    assert authorize_operation(authority, 'read', {'path': 'a'}) == 'read'


def test_cancel_task_id_is_a_selector_not_authority(monkeypatch):
    assert verify(signed(monkeypatch, 'files_operation_cancel', 'write', 'files:write'),
                  'files_operation_cancel', {'workspace_id': 'w', 'task_id': 'task'})


def test_command_cancel_selector_does_not_override_owner_identity(monkeypatch):
    tool = 'files_command_cancel'
    meta = signed(monkeypatch, tool, 'write', 'files:execute',
                  scopes=['files:execute', 'files:write'])
    context = verify(meta, tool, {'task_id': 'target-task'})
    assert context['principal_id'] == 'p'
    for injected in ({'task_id': 'target-task', 'session_id': 'other'},
                     {'task_id': 'target-task', 'principal_id': 'other'},
                     {'task_id': 'target-task', 'effective_access': 'write'}):
        with pytest.raises(PermissionError):
            verify(meta, tool, injected)
    with pytest.raises(PermissionError):
        verify(signed(monkeypatch), 'files_read', {'path': 'a', 'task_id': 'target-task'})


def test_read_context_cannot_use_mutation_guard(native, monkeypatch):
    from app.core.execution_context import CURRENT
    fs, root, profile = native
    monkeypatch.setattr(fs, 'get_profile', lambda name: dict(profile))
    authority = verify(signed(monkeypatch), 'files_read', {'path': 'a'})
    token = CURRENT.set(authority)
    try:
        with pytest.raises(PermissionError, match='WRITE_SCOPE_REQUIRED'):
            fs.write('a', 'not allowed')
        assert not (root / 'a').exists()
    finally:
        CURRENT.reset(token)


def test_overlapping_copy_and_move_do_not_delete_source(native):
    fs, root, profile = native
    (root / 'folder').mkdir()
    (root / 'folder/a').write_text('keep')
    for operation in (fs.copy, fs.move):
        for source, target in [('folder', 'folder'), ('folder', 'folder/sub'), ('folder/a', 'folder')]:
            with pytest.raises(ValueError, match='overlap'):
                operation(source, target, overwrite=True)
        assert (root / 'folder/a').read_text(encoding='utf-8') == 'keep'


def test_core_workspace_list_context_stays_compatible(monkeypatch):
    authority = verify(signed(monkeypatch, 'files_workspace_list',
                             policy_revision='local-management-v1'), 'files_workspace_list', {})
    assert authority['effective_access'] == 'read'


@pytest.fixture
def native(monkeypatch, tmp_path):
    from app.core import fsops
    from app.profiles import manager
    root = tmp_path / 'approved'
    root.mkdir()
    backups = tmp_path / 'backups'
    backups.mkdir()
    profile = dict(name='approved', root=str(root), mode='read-write', enabled=True, authorized_by_user=True)
    monkeypatch.setattr(fsops, 'BACKUP_ROOT', backups)
    token = manager.BOUND_PROFILE.set(profile)
    yield fsops, root, profile
    manager.BOUND_PROFILE.reset(token)


def test_native_write_patch_delete_and_predictable_temp_are_safe(native):
    fs, root, profile = native
    (root / 'a.txt.tmp').write_text('do not touch')
    fs.write('a.txt', 'first')
    fs.patch('a.txt', 'first', 'second')
    assert fs.read_text('a.txt')['text'] == 'second'
    assert (root / 'a.txt.tmp').read_text(encoding='utf-8') == 'do not touch'
    fs.delete('a.txt')
    assert not (root / 'a.txt').exists()
    assert not list(root.glob('.zagent-*.tmp'))


def test_native_rejects_junction_ancestor_and_recursive_subtree(native, tmp_path):
    fs, root, profile = native
    outside = tmp_path / 'outside'
    outside.mkdir()
    victim = outside / 'victim.txt'
    victim.write_text('unchanged')
    nested = root / 'nested'
    nested.mkdir()
    junction = nested / 'jump'
    result = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(junction), str(outside)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    try:
        for operation in (lambda: fs.read_text('nested/jump/victim.txt'),
                          lambda: fs.write('nested/jump/victim.txt', 'changed'),
                          lambda: fs.delete('nested'), lambda: fs.copy('nested', 'copied')):
            with pytest.raises(PermissionError):
                operation()
        assert victim.read_text(encoding='utf-8') == 'unchanged'
        assert not (root / 'copied').exists()
    finally:
        junction.rmdir()


def test_disabled_cross_profile_batch_never_uses_active_fallback():
    from app.core.batch import copy_batch_between_profiles
    with pytest.raises(PermissionError, match='CROSS_PROFILE_COPY_DISABLED'):
        copy_batch_between_profiles('a', ['f'], 'b', '.')
