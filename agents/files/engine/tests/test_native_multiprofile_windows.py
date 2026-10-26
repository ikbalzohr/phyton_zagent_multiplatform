"""Real Registry serializer -> authenticated consumer -> native Engine fixtures.
Windows only; invoke run_native_multiprofile_windows.py to isolate ALL journals.
HTTP is captured in-process; this is not a live OAuth/network acceptance test.
"""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

if os.name != 'nt' or not os.environ.get('ZAGENT_MULTIPROFILE_FIXTURE_ROOT'):
    pytest.skip('Windows disposable runner required before product imports', allow_module_level=True)

from app.core.execution_context import (CURRENT, NATIVE_READ, NATIVE_WRITE, authorize_operation, owner_key,
    request_meta, verify, validate_profile)
from app.mcp import server as files
from app.profiles import manager
from router.access import AuthContext, AuthorizationError, ResourceAuthorizer
from router.execution_context import new_context, policy_resources, scheduler_meta
from router.files_policy import FILES_TOOL_SCOPES
from router.files_selection import files_tool_schema, selected_profile, forward_files_arguments
from router.identity import Placement
from router.registry import MCPRegistry, UpstreamState
from router import server as router


@pytest.fixture
def approval(tmp_path, monkeypatch):
    profiles = []
    for name in ('agentRoot', 'otherApproved'):
        root = tmp_path / name
        root.mkdir()
        (root / 'marker.txt').write_text(name, encoding='utf-8')
        profiles.append(dict(name=name, root=str(root), enabled=True,
            authorized_by_user=True, mode='read-write'))
    manager.save_profiles(dict(schema_version='2.0', active_profile='agentRoot', profiles=profiles))
    placement = Placement('fixture-device', 'fixture-installation')
    auth = AuthContext('fixture-principal', 'fixture-workspace',
        frozenset({'files:read', 'files:write', 'files:execute'}),
        frozenset(FILES_TOOL_SCOPES), 'fixture-revision', time.time() + 600)
    grant = dict(expires_at=time.time() + 600, revoked=False, files_resource=dict(
        resource_id='fixture-resource', kind='files', profile_id='agentRoot',
        allowed_profile_ids=['agentRoot', 'otherApproved'],
        device_id=placement.device_id, installation_id=placement.installation_id, revoked=False))
    config = dict(workspace_id=auth.workspace_id, policy_revision=auth.policy_revision,
                  grants={auth.principal_id: grant})
    authorizer = ResourceAuthorizer(config)
    monkeypatch.setattr(router, 'placement', placement)
    monkeypatch.setattr(router, 'authorizer', lambda: authorizer)
    def policy(name):
        if name not in FILES_TOOL_SCOPES:
            raise AuthorizationError('TOOL_NOT_AUTHORIZED', 403)
        return dict(scope=FILES_TOOL_SCOPES[name], enabled=True)
    monkeypatch.setattr(router, '_policy', policy)
    return SimpleNamespace(profiles=profiles, placement=placement, auth=auth,
        grant=grant, authorizer=authorizer)


def context(a, tool, args):
    return new_context(a.auth, a.placement, FILES_TOOL_SCOPES[tool], tool,
        resource_authorizer=a.authorizer, selected_profile_id=selected_profile(tool, args))


async def paired(a, tool, arguments, service_id='zagent_files'):
    """Run actual Registry serialization, request_meta/verify and Engine dispatch."""
    trusted = context(a, tool, arguments)
    registry = object.__new__(MCPRegistry)
    registry.states = {service_id: UpstreamState(service={'id': service_id}, tools=[{
        'name': tool, 'inputSchema': {'properties': {'metadata': {}, 'path': {}}},
        '_meta': {'zagent.capability': {'operation': tool}}}])}
    ctx = SimpleNamespace(execution_context=trusted, session_id=a.auth.owner,
        request_id=trusted['request_id'], task_id=trusted['task_id'], trace_id=trusted['trace_id'],
        idempotency_key='', resource_key='installation:fixture-installation', access_mode='write',
        priority=2, profile_id='', target_device_id=a.placement.device_id)
    original = deepcopy(arguments)
    async def initialized(state):
        pass
    async def post(state, payload, **kwargs):
        params = payload['params']
        transport = SimpleNamespace(request_context=SimpleNamespace(
            request=SimpleNamespace(headers={'x-zagent-internal-token': os.environ['ZAGENT_INTERNAL_TOKEN']}),
            meta=params['_meta']))
        actual = params['arguments']
        authority = verify(request_meta(transport), tool, actual)
        assert authority['session_id'] != a.auth.owner  # Files namespace only, Router receipt unchanged
        validate_profile(authority, files.engine.approved(authority['profile_id']))
        op = actual['operation'] if tool == 'files_execute' else tool[6:]
        inner = actual['arguments'] if tool == 'files_execute' else actual
        authorize_operation(authority, op, inner)
        if op in {'workspace_open', 'workspace_status', 'workspace_switch', 'workspace_list',
                  'operation_status', 'operation_list', 'operation_cancel', 'capabilities'}:
            files.engine.ensure_session(authority['session_id'], authority['profile_id'])
            token = CURRENT.set(authority)
            try:
                value = getattr(files, 'files_' + op)(**inner)
            finally:
                CURRENT.reset(token)
        else:
            value = await files.engine.execute(op, inner, authority)
        return {'result': value}
    registry.ensure_initialized = initialized
    registry._post = post
    result = await registry.invoke(service_id, tool, arguments, ctx)
    assert arguments == original  # durable public request is never stripped/mutated
    return trusted, result


@pytest.mark.parametrize('service_id', ['zagent_files', 'zagent_files_v3'])
@pytest.mark.parametrize('name', ['agentRoot', 'otherApproved'])
def test_real_native_read_write_wrapper_and_session_isolation(approval, name, service_id):
    async def run():
        a = approval
        for tool, args in [
            ('files_read', {'path': 'marker.txt'}),
            ('files_write', {'path': 'new.txt', 'content': name}),
            ('files_execute', {'operation': 'read', 'arguments': {'path': 'marker.txt'}}),
            ('files_execute', {'operation': 'write', 'arguments': {'path': 'wrapped.txt', 'content': name}}),
        ]:
            trusted, result = await paired(a, tool, dict(args, profile_id=name), service_id)
            assert result['ok'] is True
            assert trusted['effective_resources'][0]['profile_id'] == name
            assert result['_meta']['zagent.profile_id'] == name
            if tool == 'files_read' or (tool == 'files_execute' and args['operation'] == 'read'):
                assert result['data']['text'] == name
        root = Path(next(p['root'] for p in a.profiles if p['name'] == name))
        assert (root / 'new.txt').read_text(encoding='utf-8') == name
        assert (root / 'wrapped.txt').read_text(encoding='utf-8') == name
        # Controls for B cannot retarget A's session or its subsequent native read.
        c1, _ = await paired(a, 'files_workspace_open', dict(workspace_id=a.auth.workspace_id,
            profiles=[name], active_profile=name, profile_id=name), service_id)
        c2, status = await paired(a, 'files_workspace_status', dict(workspace_id=a.auth.workspace_id,
            profile_id=name), service_id)
        assert owner_key(c1) == owner_key(c2)
        assert status['active_profile'] == name and status['profiles'] == [name]
        other = context(a, 'files_read', {'path': 'marker.txt',
            'profile_id': 'otherApproved' if name == 'agentRoot' else 'agentRoot'})
        assert owner_key(other) != owner_key(c1)
        other_name = other['effective_resources'][0]['profile_id']
        _, switched = await paired(a, 'files_workspace_switch', dict(workspace_id=a.auth.workspace_id,
            profile_id=other_name), service_id)
        assert switched['active_profile'] == other_name
        _, reread = await paired(a, 'files_read', {'path': 'marker.txt', 'profile_id': name}, service_id)
        assert reread['data']['text'] == name
        with pytest.raises(KeyError):
            files.engine.journal.get(result['_meta']['zagent.operation_id'], owner_key(other))
    asyncio.run(run())


def test_default_omission_and_queued_default_changes_never_retarget(approval):
    a = approval
    before = context(a, 'files_read', {'path': 'marker.txt'})
    assert before['effective_resources'][0]['profile_id'] == 'agentRoot'
    a.grant['files_resource']['profile_id'] = 'otherApproved'
    assert before['effective_resources'] == policy_resources(a.auth, a.placement,
        'files:read', a.authorizer, selected_profile_id=before['effective_resources'][0]['profile_id'])
    assert policy_resources(a.auth, a.placement, 'files:read', a.authorizer)[0]['profile_id'] == 'otherApproved'
    assert scheduler_meta(before, a.auth.owner)['resource_key'] == 'installation:fixture-installation'
    assert scheduler_meta(before, a.auth.owner)['access_mode'] == 'write'


@pytest.mark.parametrize('allowed', [[], ['agentRoot', 'agentRoot'], ['*'],
    ['agentRoot', '*'], ['otherApproved'], 'agentRoot', [None], ['agentRoot', ' bad'],
    ['agentRoot'] * 129, ['agentRoot', {}]])
def test_malformed_allowlists_fail_closed(approval, allowed):
    approval.grant['files_resource']['allowed_profile_ids'] = allowed
    with pytest.raises(AuthorizationError):
        context(approval, 'files_read', {'path': 'marker.txt'})


@pytest.mark.parametrize('selector', ['appBridge', 'unapproved', '', '*', None, [], {}])
def test_unknown_removed_malformed_selector_denied(approval, selector):
    with pytest.raises(AuthorizationError):
        context(approval, 'files_read', dict(path='marker.txt', profile_id=selector))


def test_single_profile_legacy_grant_compatibility(approval):
    del approval.grant['files_resource']['allowed_profile_ids']
    assert context(approval, 'files_read', {})['effective_resources'][0]['profile_id'] == 'agentRoot'
    with pytest.raises(AuthorizationError):
        context(approval, 'files_read', {'profile_id': 'otherApproved'})


@pytest.mark.parametrize('change', ['revoked', 'expired', 'resource_revoked', 'scope'])
def test_revocation_expiry_and_missing_scope(approval, change):
    a = approval
    if change == 'revoked':
        a.grant['revoked'] = True
    elif change == 'expired':
        a.grant['expires_at'] = time.time() - 1
    elif change == 'resource_revoked':
        a.grant['files_resource']['revoked'] = True
    else:
        a.auth = AuthContext(a.auth.principal_id, a.auth.workspace_id, frozenset(), a.auth.tools,
                             a.auth.policy_revision, a.auth.expires_at)
    with pytest.raises(AuthorizationError):
        context(a, 'files_read', {})


def test_every_supported_files_schema_uses_same_selector_contract(approval, monkeypatch):
    originals = [{'name': name, 'inputSchema': {'type': 'object', 'properties': {},
                  'additionalProperties': False}} for name in FILES_TOOL_SCOPES]
    for item in originals:
        if item['name'] == 'files_execute':
            item['inputSchema']['properties'].update(operation={'type': 'string'}, arguments={'type': 'object'})
    unchanged = deepcopy(originals)
    monkeypatch.setattr(router.registry, 'list_public_tools', lambda: originals)
    for name in FILES_TOOL_SCOPES:
        schema = files_tool_schema(next(t for t in originals if t['name'] == name))
        assert schema['inputSchema']['properties']['profile_id']['type'] == 'string'
        args: dict[str, object] = {'profile_id': 'otherApproved'}
        if name == 'files_execute':
            args.update(operation='read', arguments={})
        router._validate_tool(name, args, approval.auth)
    assert originals == unchanged


@pytest.mark.parametrize('tool,args', [
    ('files_exec_command', {'profile_id': 'agentRoot', 'profile': 'otherApproved'}),
    ('files_workspace_open', {'profile_id': 'agentRoot', 'profiles': ['otherApproved']}),
    ('files_workspace_open', {'profiles': ['agentRoot', 'otherApproved']}),
    ('files_workspace_open', {'profiles': ['agentRoot'], 'active_profile': 'otherApproved'}),
])
def test_conflicting_domain_selectors_rejected(approval, tool, args):
    with pytest.raises(AuthorizationError):
        context(approval, tool, args)


@pytest.mark.parametrize('key', ['metadata', '_meta', 'profile_id', 'profile', 'profiles', 'active_profile'])
def test_wrapper_nested_spoof_and_native_metadata_remain_rejected(approval, key):
    async def run():
        with pytest.raises(ValueError, match='CLIENT_AUTHORITY_NOT_ALLOWED'):
            await paired(approval, 'files_execute', dict(profile_id='agentRoot', operation='read',
                arguments={'path': 'marker.txt', key: 'otherApproved'}))
        # Separately bypass public selection to exercise the still-strict
        # consumer guard on an authenticated but invalid transport payload.
        trusted = context(approval, 'files_execute', {'operation': 'read', 'arguments': {'path': 'marker.txt'}})
        transport = SimpleNamespace(request_context=SimpleNamespace(
            request=SimpleNamespace(headers={'x-zagent-internal-token': os.environ['ZAGENT_INTERNAL_TOKEN']}),
            meta={'zagent.execution_context': trusted}))
        with pytest.raises(PermissionError, match='CLIENT_AUTHORITY_NOT_ALLOWED'):
            verify(request_meta(transport), 'files_execute', {'operation': 'read',
                'arguments': {'path': 'marker.txt', key: 'otherApproved'}})
        if key in {'metadata', '_meta'}:
            with pytest.raises(PermissionError):
                await paired(approval, 'files_read', {'path': 'marker.txt', key: {}})
    asyncio.run(run())


def test_removed_or_disabled_local_profile_never_falls_back(approval):
    a = approval
    document = manager.load_profiles()
    document['profiles'] = [p for p in document['profiles'] if p['name'] != 'otherApproved']
    manager.save_profiles(document)
    with pytest.raises(KeyError):
        asyncio.run(paired(a, 'files_read', {'path': 'marker.txt', 'profile_id': 'otherApproved'}))
    document['profiles'][0]['enabled'] = False
    manager.save_profiles(document)
    with pytest.raises(PermissionError):
        asyncio.run(paired(a, 'files_read', {'path': 'marker.txt'}))


def test_receipts_keep_router_owner_but_removed_profile_results_are_denied(approval, monkeypatch):
    a = approval
    trusted = context(a, 'files_read', {'path': 'marker.txt', 'profile_id': 'otherApproved'})
    row = {'session_id': a.auth.owner, 'execution_context_json': json.dumps(trusted)}
    async def get(task_id):
        return row
    monkeypatch.setattr(router.orchestrator.journal, 'get', get)
    assert asyncio.run(router._owned_task('fixture-task', a.auth)) is row
    a.grant['files_resource']['allowed_profile_ids'] = ['agentRoot']
    with pytest.raises(AuthorizationError):
        asyncio.run(router._owned_task('fixture-task', a.auth))


def test_forwarding_preserves_domain_selector_and_command_profile(approval):
    a = approval
    for tool, args in [('files_workspace_switch', {'profile_id': 'otherApproved', 'workspace_id': a.auth.workspace_id}),
                       ('files_exec_command', {'profile_id': 'otherApproved', 'profile': 'otherApproved'})]:
        trusted = context(a, tool, args)
        forwarded = forward_files_arguments(tool, args, trusted)
        if tool == 'files_workspace_switch':
            assert forwarded == args
        else:
            assert forwarded == {'profile': 'otherApproved'}
        with pytest.raises(AuthorizationError):
            forward_files_arguments(tool, dict(args, profile_id='agentRoot'), trusted)


@pytest.mark.parametrize('op', sorted(NATIVE_READ | NATIVE_WRITE))
@pytest.mark.parametrize('name', ['agentRoot', 'otherApproved'])
def test_all_native_operation_authorization_seams(approval, op, name):
    # Every supported native op accepts selection at the public seam, and only
    # stripped native arguments at the consumer. Domain I/O is exercised above
    # for read/write/wrapper; this matrix tests authority, not each op's I/O.
    a = approval
    tool = 'files_' + op
    arguments = {'profile_id': name}
    trusted = context(a, tool, arguments)
    registry = object.__new__(MCPRegistry)
    registry.states = {'zagent_files': UpstreamState(service={'id': 'zagent_files'}, tools=[])}
    ctx = SimpleNamespace(execution_context=trusted, session_id=a.auth.owner,
        request_id=trusted['request_id'], trace_id=trusted['trace_id'], task_id=trusted['task_id'], profile_id='')
    async def initialized(state):
        pass
    async def post(state, payload, **kwargs):
        params = payload['params']
        assert params['arguments'] == {}
        transport = SimpleNamespace(request_context=SimpleNamespace(
            request=SimpleNamespace(headers={'x-zagent-internal-token': os.environ['ZAGENT_INTERNAL_TOKEN']}),
            meta=params['_meta']))
        authority = verify(request_meta(transport), tool, params['arguments'])
        assert authority['profile_id'] == name
        assert authorize_operation(authority, op, {}) == op
        return {'result': {'ok': True}}
    registry.ensure_initialized = initialized
    registry._post = post
    assert asyncio.run(registry.invoke('zagent_files', tool, arguments, ctx))['ok'] is True


def test_real_revalidate_pins_original_selection(approval, monkeypatch):
    a = approval
    trusted = context(a, 'files_read', {'path': 'marker.txt'})
    async def authenticate(bearer, client):
        a.authorizer.current_grant(a.auth)
        return a.auth
    monkeypatch.setattr(a.authorizer, 'authenticate', authenticate)
    monkeypatch.setattr(router, '_auth_client', object())
    monkeypatch.setitem(router._credentials, trusted['request_id'], ('fixture-memory-only', trusted['deadline']))
    a.grant['files_resource']['profile_id'] = 'otherApproved'
    assert asyncio.run(router._revalidate(trusted)) == a.auth
    a.grant['files_resource']['allowed_profile_ids'] = ['otherApproved']
    with pytest.raises(AuthorizationError):
        asyncio.run(router._revalidate(trusted))


def test_task_submit_uses_augmented_schema_and_journals_original_arguments(approval, monkeypatch):
    a = approval
    original_policy = router._policy
    monkeypatch.setattr(router, '_policy', lambda name: {'scope': 'files:read', 'enabled': True}
        if name == 'zagent_task_submit' else original_policy(name))
    a.auth = AuthContext(a.auth.principal_id, a.auth.workspace_id, a.auth.scopes,
        a.auth.tools | {'zagent_task_submit'}, a.auth.policy_revision, a.auth.expires_at)
    monkeypatch.setattr(router.registry, 'list_public_tools', lambda: [dict(name='files_read',
        inputSchema=dict(type='object', properties={'path': {'type': 'string'}}, additionalProperties=False))])
    monkeypatch.setattr(router.registry, 'get_mapping', lambda name: ('zagent_files', name))
    captured = []
    async def submit(service, tool, arguments, meta):
        captured.append((deepcopy(arguments), deepcopy(meta)))
        return {'task_id': meta['task_id'], 'state': 'queued'}
    monkeypatch.setattr(router.orchestrator, 'submit', submit)
    arguments = {'path': 'marker.txt', 'profile_id': 'otherApproved'}
    asyncio.run(router._dispatch('zagent_task_submit', {'tool_name': 'files_read', 'arguments': arguments},
        a.auth, 'fixture-memory-only'))
    assert captured[0][0] == arguments
    assert captured[0][1]['execution_context']['effective_resources'][0]['profile_id'] == 'otherApproved'
    assert captured[0][1]['session_id'] == a.auth.owner
