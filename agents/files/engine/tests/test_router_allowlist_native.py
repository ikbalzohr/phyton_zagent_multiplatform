"""Router-level native allowlist regressions; no live OAuth/network.

Exercises the actual Router _dispatch/_request_context/_executor path against a
disposable in-process Files backend. The Files backend is not started as a
server; registry.invoke drives the _post adapter directly.
"""
import asyncio
from copy import deepcopy
import json
import os
import shutil
import sys
import time
from types import SimpleNamespace

import pytest

if not os.environ.get('ZAGENT_NATIVE_ALLOWLIST_FIXTURE'):
    pytest.skip('run_native_allowlist.py required before product imports', allow_module_level=True)

from app.mcp import server as files
from app.mcp import managed_commands as commands
from app.profiles import manager
from app.profiles.administration import profile_generation as _profile_generation, _load as _load_state
from router.access import AuthContext, AuthorizationError, ResourceAuthorizer
from router.execution_context import new_context
from router.files_policy import FILES_TOOL_SCOPES
from router.files_selection import selected_profile
from router.identity import Placement
from router.registry import MCPRegistry, UpstreamState
from router import server as router


ALLOWLIST = {'files_allowlist_list': 'files:read', 'files_allowlist_add': 'files:write',
    'files_allowlist_remove': 'files:write', 'files_allowlist_replace': 'files:write'}
ALL_TOOLS = {**FILES_TOOL_SCOPES, **ALLOWLIST}


def serialize_call_result(result):
    """Simulate the Files HTTP transport serialization of call_tool's return."""
    if isinstance(result, list):
        serialized = [x.model_dump() if hasattr(x, 'model_dump') else x for x in result]
        return {'content': serialized}
    if isinstance(result, tuple):
        structured = result[1] if len(result) > 1 else None
        out = {'content': [x.model_dump() if hasattr(x, 'model_dump') else x for x in result[0]]}
        if structured is not None:
            out['structuredContent'] = structured
        return out
    if hasattr(result, 'model_dump'):
        return {'content': [result.model_dump()]}
    return result


def _files_post():
    async def post(svc, payload, **kwargs):
        p = payload['params']
        transport = SimpleNamespace(request_context=SimpleNamespace(
            request=SimpleNamespace(headers={'x-zagent-internal-token': os.environ['ZAGENT_INTERNAL_TOKEN']}),
            meta=p['_meta']))
        files.mcp.get_context = lambda: transport
        try:
            result = await files.mcp.call_tool(p['name'], p['arguments'])
        finally:
            del files.mcp.get_context
        return {'result': serialize_call_result(result)}
    return post


@pytest.fixture
def state(tmp_path):
    rows = []
    for name in ('A', 'B'):
        root = tmp_path / name
        root.mkdir()
        rows.append(dict(name=name, root=str(root), enabled=True, authorized_by_user=True, mode='read-write'))
    manager.save_profiles(dict(schema_version='2.0', active_profile='A', profiles=rows))
    exe = tmp_path / ('original' if os.name != 'nt' else 'original.exe')
    shutil.copyfile(sys.executable, exe)
    exe.chmod(0o700)
    policies = {name: dict(version=1, enabled=True, execution_mode='owner-account', acknowledge_host_access=True,
        profile_id=name, root=str(tmp_path / name), allowed_tools=['files_exec_command'],
        allowed_executables=[str(exe)], max_timeout_seconds=120, max_output_chars=10000) for name in ('A', 'B')}
    commands.POLICY_FILE.write_text(json.dumps(dict(version=2, profiles=policies)), encoding='utf-8')
    auth = AuthContext('principal', 'workspace', frozenset({'files:read', 'files:write', 'files:execute'}),
        frozenset(ALL_TOOLS), 'r1', time.time() + 600)
    grant = dict(scopes=list(auth.scopes), tools=list(auth.tools), files_resource=dict(
        resource_id='fixture-resource', kind='files', profile_id='A', allowed_profile_ids=['A', 'B'],
        device_id='fixture-device', installation_id='fixture-installation'))
    authorizer = ResourceAuthorizer(dict(workspace_id='workspace', policy_revision='r1', grants={'principal': grant}))
    tools = [{'name': name, 'inputSchema': {'properties': {}}, '_meta': {'zagent.capability': {'operation': name}}}
        for name in ALLOWLIST]
    return SimpleNamespace(auth=auth, authorizer=authorizer, grant=grant, exe=str(exe), root=tmp_path,
        placement=Placement('fixture-device', 'fixture-installation'), tools=tools)


async def dispatch(state, tool, arguments):
    context = new_context(state.auth, state.placement, ALLOWLIST[tool], tool,
        resource_authorizer=state.authorizer, selected_profile_id=selected_profile(tool, arguments))
    registry = object.__new__(MCPRegistry)
    registry.states = {'zagent_files': UpstreamState(service={'id': 'zagent_files'}, tools=state.tools)}
    async def initialized(s):
        pass
    registry.ensure_initialized = initialized
    registry._post = _files_post()
    ctx = SimpleNamespace(execution_context=context, session_id=state.auth.owner, request_id=context['request_id'],
        task_id=context['task_id'], trace_id=context['trace_id'], idempotency_key='',
        resource_key='installation:fixture-installation', access_mode='write', priority=2, profile_id='',
        target_device_id='fixture-device')
    return await registry.invoke('zagent_files', tool, deepcopy(arguments), ctx)


async def _catalog(value):
    return value


def test_router_dispatch_allows_nondefault_profile(state):
    async def run():
        router_placement, router_authorizer, router_policy, router_catalog = \
            router.placement, router.authorizer, router._policy, router._files_catalog
        router.placement = state.placement
        router.authorizer = lambda: state.authorizer
        router._auth_client = object()
        try:
            async def policy(name):
                return dict(scope=ALL_TOOLS.get(name, 'files:read'), enabled=True)
            router._policy = policy
            catalog = {'default_profile_id': 'A', 'allowed_profile_ids': ['A', 'B'],
                'generations': {'A': 'gA', 'B': 'gB'}, 'profiles': [{'name': 'B', 'root': str(state.root / 'B')}]}
            router._files_catalog = lambda auth, a: _catalog(catalog)
            result = await dispatch(state, 'files_allowlist_list', {'profile_id': 'B'})
            text = json.loads(result['content'][0]['text'])
            assert text['ok'] is True and text['profile_id'] == 'B'
        finally:
            router.placement, router.authorizer, router._auth_client = router_placement, router_authorizer, None
            router._policy, router._files_catalog = router_policy, router_catalog
    asyncio.run(run())


def test_http_perimeter_exposes_allowlist_and_enforces_scope(state, monkeypatch):
    # Prove the real /mcp ASGI perimeter wires native allowlist tools end-to-end:
    # auth -> tools/list visibility -> tools/call (durable receipt) -> async
    # worker execution -> Files call_tool -> zagent_task_result retrieval.
    import httpx

    # Catalog generations must match the live Files engine's profile_generation.
    live_state = _load_state()
    generations = {p['name']: _profile_generation(p, live_state) for p in live_state['profiles']}
    catalog = {'default_profile_id': live_state['active_profile'],
        'allowed_profile_ids': [p['name'] for p in live_state['profiles']],
        'generations': generations,
        'profiles': [{'name': p['name'], 'root': p['root']} for p in live_state['profiles']]}
    monkeypatch.setattr(router, 'placement', state.placement)
    monkeypatch.setattr(router, '_files_catalog', lambda auth, a: _catalog(catalog))

    class StubAuthorizer:
        configured = True
        config = {'resource_uri': ''}
        def current_grant(self, auth):
            return state.grant
        async def authenticate(self, authorization, client):
            return state.auth
    monkeypatch.setattr(router, 'authorizer', lambda: StubAuthorizer())
    monkeypatch.setattr(router, '_auth_client', object())
    # Populate the module-level registry the same way the in-process fixture does.
    monkeypatch.setattr(router.registry, 'states', {'zagent_files': UpstreamState(
        service={'id': 'zagent_files', 'name': 'Files', 'namespace': 'files'}, tools=list(state.tools))})
    monkeypatch.setattr(router.registry, 'tool_index', {t['name']: ('zagent_files', t['name']) for t in state.tools})
    router.registry.rebuild_index()
    async def _no_init(state):
        pass
    monkeypatch.setattr(router.registry, 'ensure_initialized', _no_init)
    monkeypatch.setattr(router.registry, '_post', _files_post())

    async def run():
        await router.orchestrator.start()
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=router.app), base_url='http://127.0.0.1')
        try:
            # 1. tools/list: native allowlist tools are visible with the right scopes.
            listed = await client.post('/mcp', headers={'Authorization': 'Bearer synthetic'},
                json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
            names = [t['name'] for t in listed.json()['result']['tools']]
            assert 'files_allowlist_list' in names
            assert 'files_allowlist_add' in names

            # 2. tools/call: durable receipt, then async worker runs the Files handler.
            submitted = await client.post('/mcp', headers={'Authorization': 'Bearer synthetic'},
                json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
                    'params': {'name': 'files_allowlist_list', 'arguments': {'profile_id': 'A'}}})
            receipt = json.loads(submitted.json()['result']['content'][0]['text'])
            assert receipt['accepted'] is True
            task_id = receipt['task_id']

            # 3. Poll zagent_task_result until the worker persists the real outcome.
            value = None
            for _ in range(100):
                result = await client.post('/mcp', headers={'Authorization': 'Bearer synthetic'},
                    json={'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                        'params': {'name': 'zagent_task_result', 'arguments': {'task_id': task_id}}})
                body = json.loads(result.json()['result']['content'][0]['text'])
                if body.get('ok') is True and body.get('task', {}).get('state') == 'succeeded':
                    wrapped = body['task'].get('result') or {}
                    if isinstance(wrapped, dict) and wrapped.get('content'):
                        value = json.loads(wrapped['content'][0]['text'])
                    break
                if body.get('ok') is True and body.get('task', {}).get('state') == 'failed':
                    break
                await asyncio.sleep(0.05)
            assert value is not None, 'task did not complete'
            assert value['ok'] is True
            assert value['profile_id'] == 'A'

            # 4. Scope downgrade: a files:read-only principal is denied a write tool (403).
            read_only = AuthContext('principal', 'workspace', frozenset({'files:read'}),
                frozenset({'files_allowlist_list'}), 'r1', time.time() + 600)
            class ReadOnlyAuthorizer:
                configured = True
                config = {'resource_uri': ''}
                async def authenticate(self, authorization, client):
                    return read_only
            router.authorizer = lambda: ReadOnlyAuthorizer()
            try:
                denied = await client.post('/mcp', headers={'Authorization': 'Bearer synthetic'},
                    json={'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
                        'params': {'name': 'files_allowlist_add', 'arguments': {'profile_id': 'A',
                            'executable': str(state.exe), 'expected_revision': 'a' * 64}}})
                assert denied.status_code == 403
            finally:
                monkeypatch.undo()
                monkeypatch.setattr(router, 'authorizer', lambda: StubAuthorizer())
        finally:
            await client.aclose()
            await router.orchestrator.stop()

    try:
        asyncio.run(run())
    finally:
        monkeypatch.undo()
