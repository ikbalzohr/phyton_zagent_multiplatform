"""Actual Router context/Registry and registered Files handler, disposable state only."""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
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
from router.access import AuthContext, ResourceAuthorizer
from router.execution_context import new_context
from router.files_policy import FILES_TOOL_SCOPES
from router.files_selection import selected_profile
from router.identity import Placement
from router.registry import MCPRegistry, UpstreamState

from contextlib import contextmanager


@contextmanager
def native_context(state, tool, arguments):
    """Use the real verified Router context without an HTTP transport fixture."""
    from app.core.execution_context import CURRENT, TrustedMetadata, verify
    context = new_context(state.auth, state.placement, TOOLS[tool], tool,
        resource_authorizer=state.authorizer, selected_profile_id='B')
    authority = verify(TrustedMetadata({'zagent.execution_context': context}), tool, arguments)
    token = CURRENT.set(authority)
    try:
        yield
    finally:
        CURRENT.reset(token)


@pytest.mark.parametrize('action,updates,code', [
    ('add', {'expected_revision': '0' * 64}, 'REVISION_CONFLICT'),
    ('add', {'expected_revision': 'invalid'}, 'INVALID_ARGUMENT'),
    ('add', {'executable': '*'}, 'EXACT_LOCAL_EXECUTABLE_REQUIRED'),
    ('add', {'executable': '$HOME/python'}, 'EXACT_LOCAL_EXECUTABLE_REQUIRED'),
    ('add', {}, 'EXECUTABLE_ALREADY_ALLOWED'),
    ('remove', {}, 'NONEMPTY_ALLOWLIST_REQUIRED'),
    ('remove', {'executable': 'missing'}, 'EXECUTABLE_NOT_ALLOWED'),
    ('replace', {'replacement_executable': '*'}, 'EXACT_LOCAL_EXECUTABLE_REQUIRED'),
    ('add', {'extra': 'forbidden'}, 'INVALID_ARGUMENT'),
])
def test_rejections_leave_policy_unchanged(state, action, updates, code):
    import hashlib
    from app.mcp.allowlist_tools import invoke
    before = commands.POLICY_FILE.read_bytes()
    tool = 'files_allowlist_' + action
    arguments = dict(profile_id='B', executable=state.exe,
                     expected_revision=hashlib.sha256(before).hexdigest())
    if action == 'replace':
        arguments['replacement_executable'] = state.exe
    arguments.update(updates)
    with native_context(state, tool, arguments):
        with pytest.raises(ValueError, match=code):
            invoke(tool, arguments)
    assert commands.POLICY_FILE.read_bytes() == before


def test_publication_failure_preserves_policy(state, monkeypatch):
    import hashlib
    from app.mcp import allowlist_tools as api
    before = commands.POLICY_FILE.read_bytes()
    new = state.root / ('publish.exe' if os.name == 'nt' else 'publish')
    shutil.copyfile(sys.executable, new)
    new.chmod(0o700)
    arguments = dict(profile_id='B', executable=str(new),
                     expected_revision=hashlib.sha256(before).hexdigest())
    def fail(*args):
        raise OSError('fixture publication failure')
    monkeypatch.setattr(api, '_publish', fail)
    with native_context(state, 'files_allowlist_add', arguments):
        with pytest.raises(OSError, match='fixture publication failure'):
            api.invoke('files_allowlist_add', arguments)
    assert commands.POLICY_FILE.read_bytes() == before


TOOLS = {'files_allowlist_list': 'files:read', **{f'files_allowlist_{a}': 'files:write' for a in ('add', 'remove', 'replace')}}


@pytest.fixture
def state(tmp_path):
    rows = []
    for name in ('A', 'B'):
        root = tmp_path / name
        root.mkdir()
        rows.append(dict(name=name, root=str(root), enabled=True, authorized_by_user=True, mode='read-write'))
    manager.save_profiles(dict(schema_version='2.0', active_profile='A', profiles=rows))
    exe = tmp_path / ('original.exe' if os.name == 'nt' else 'original')
    shutil.copyfile(sys.executable, exe)
    exe.chmod(0o700)
    policies = {r['name']: dict(version=1, enabled=True, execution_mode='owner-account', acknowledge_host_access=True,
        profile_id=r['name'], root=r['root'], allowed_tools=['files_exec_command'], allowed_executables=[str(exe)],
        max_timeout_seconds=120, max_output_chars=10000) for r in rows}
    commands.POLICY_FILE.write_text(json.dumps(dict(version=2, profiles=policies)), encoding='utf-8')
    auth = AuthContext('principal', 'workspace', frozenset({'files:read', 'files:write', 'files:execute'}),
        frozenset(TOOLS) | {'files_exec_command'}, 'r1', time.time() + 600)
    grant = dict(scopes=list(auth.scopes), tools=list(auth.tools), files_resource=dict(kind='files',
        resource_id='fixture-resource', profile_id='A', allowed_profile_ids=['A', 'B'],
        device_id='fixture-device', installation_id='fixture-installation'))
    authorizer = ResourceAuthorizer(dict(workspace_id='workspace', policy_revision='r1', grants={'principal': grant}))
    return SimpleNamespace(auth=auth, authorizer=authorizer, grant=grant, exe=str(exe), root=tmp_path,
        placement=Placement('fixture-device', 'fixture-installation'), policies=policies)


async def call(s, tool, arguments):
    context = new_context(s.auth, s.placement, TOOLS[tool], tool, resource_authorizer=s.authorizer,
        selected_profile_id=selected_profile(tool, arguments))
    registry = object.__new__(MCPRegistry)
    registry.states = {'zagent_files': UpstreamState(service={'id': 'zagent_files'}, tools=[])}
    async def initialized(state):
        pass
    async def post(state, payload, **kwargs):
        p = payload['params']
        transport = SimpleNamespace(request_context=SimpleNamespace(
            request=SimpleNamespace(headers={'x-zagent-internal-token': os.environ['ZAGENT_INTERNAL_TOKEN']}), meta=p['_meta']))
        original = files.mcp.get_context
        files.mcp.get_context = lambda: transport
        try:
            result = await files.mcp.call_tool(p['name'], p['arguments'])
        except Exception as exc:
            result = {'content': [{'type': 'text', 'text': f'DEBUG: {type(exc).__name__}: {exc}'}], 'isError': True}
        finally:
            files.mcp.get_context = original
        if isinstance(result, list):
            result = {'content': [x.model_dump() if hasattr(x, 'model_dump') else x for x in result]}
        elif isinstance(result, tuple):
            structured = result[1] if len(result) > 1 else None
            result = {'content': [x.model_dump() if hasattr(x, 'model_dump') else x for x in result[0]]}
            if structured is not None:
                result['structuredContent'] = structured
        elif hasattr(result, 'model_dump'):
            result = result.model_dump(mode='json')
        return {'result': result}
    registry.ensure_initialized = initialized
    registry._post = post
    ctx = SimpleNamespace(execution_context=context, session_id=s.auth.owner, request_id=context['request_id'],
        task_id=context['task_id'], trace_id=context['trace_id'], idempotency_key='',
        resource_key='installation:fixture-installation', access_mode='write', priority=2, profile_id='',
        target_device_id='fixture-device')
    result = await registry.invoke('zagent_files', tool, deepcopy(arguments), ctx)
    assert not result.get('isError'), result
    if result.get('structuredContent'):
        return result['structuredContent']
    content = result['content'][0]
    if isinstance(content, str):
        return json.loads(content)
    return json.loads(content.get('text', json.dumps(content)))


def test_competing_writers_use_revision_cas(state):
    import hashlib
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from app.mcp import allowlist_tools as api
    before = json.loads(commands.POLICY_FILE.read_text())
    revision = hashlib.sha256(commands.POLICY_FILE.read_bytes()).hexdigest()
    candidates = []
    for index in range(2):
        path = state.root / (f'concurrent{index}.exe' if os.name == 'nt' else f'concurrent{index}')
        shutil.copyfile(sys.executable, path)
        path.chmod(0o700)
        candidates.append(str(path))
    ready = threading.Barrier(2)
    def write(executable):
        arguments = dict(profile_id='B', executable=executable, expected_revision=revision)
        with native_context(state, 'files_allowlist_add', arguments):
            ready.wait(timeout=10)
            try:
                return api.invoke('files_allowlist_add', arguments)['ok']
            except ValueError as exc:
                return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, candidates))
    assert results.count(True) == 1 and results.count('REVISION_CONFLICT') == 1
    after = json.loads(commands.POLICY_FILE.read_text())
    assert len(after['profiles']['B']['allowed_executables']) == 2
    assert len(set(candidates) & set(after['profiles']['B']['allowed_executables'])) == 1
    after['profiles']['B']['allowed_executables'] = before['profiles']['B']['allowed_executables']
    assert after == before


def test_native_errors_are_actionable_and_profile_lease_is_used(state, monkeypatch):
    from contextlib import asynccontextmanager
    original = files.read_lease
    entered = []
    @asynccontextmanager
    async def tracked_lease(*args, **kwargs):
        async with original(*args, **kwargs):
            entered.append(True)
            yield
    monkeypatch.setattr(files, 'read_lease', tracked_lease)
    before = commands.POLICY_FILE.read_bytes()
    async def run():
        with pytest.raises(AssertionError, match='REVISION_CONFLICT'):
            await call(state, 'files_allowlist_add', dict(profile_id='B',
                executable=state.exe, expected_revision='0' * 64))
    asyncio.run(run())
    assert entered == [True]
    assert commands.POLICY_FILE.read_bytes() == before


def test_registered_native_list_uses_permitted_nondefault_profile(state):
    async def run():
        catalog = await files.mcp.list_tools()
        assert set(TOOLS).issubset({t.name for t in catalog})
        result = await call(state, 'files_allowlist_list', {'profile_id': 'B'})
        assert result['ok'] is True
        assert result['profile_id'] == 'B'
        assert result['executables'] == [state.exe]
        assert len(result['revision']) == 64
    asyncio.run(run())


def command_grant(state, profile='B'):
    from app.core.execution_context import verify, TrustedMetadata
    context = new_context(state.auth, state.placement, 'files:execute', 'files_exec_command',
        resource_authorizer=state.authorizer, selected_profile_id=profile)
    authority = verify(TrustedMetadata({'zagent.execution_context': context}), 'files_exec_command', {})
    return commands.authorize_command_call('files_exec_command', {}, authority)


def test_remove_revokes_next_consumer_admission(state):
    async def run():
        new = state.root / ('other.exe' if os.name == 'nt' else 'other')
        shutil.copyfile(sys.executable, new)
        new.chmod(0o700)
        listed = await call(state, 'files_allowlist_list', {'profile_id': 'B'})
        added = await call(state, 'files_allowlist_add', dict(profile_id='B', executable=str(new), expected_revision=listed['revision']))
        removed = await call(state, 'files_allowlist_remove', dict(profile_id='B', executable=state.exe, expected_revision=added['revision']))
        assert removed['removed'] == [state.exe]
        grant = command_grant(state)
        with pytest.raises(PermissionError, match='EXECUTABLE_NOT_EXPLICITLY_APPROVED'):
            commands.resolve_executable(state.exe, grant)
        assert commands.resolve_executable(str(new), grant) == new
    asyncio.run(run())


def test_replace_is_one_commit_consumed_immediately(state, monkeypatch):
    async def run():
        from app.mcp import allowlist_tools as api
        new = state.root / ('replacement.exe' if os.name == 'nt' else 'replacement')
        shutil.copyfile(sys.executable, new)
        new.chmod(0o700)
        before = commands.POLICY_FILE.read_bytes()
        seen = []
        publish = api._publish
        def capture(path, raw, expected, revalidate):
            assert path.read_bytes() == before
            candidate = json.loads(raw)['profiles']['B']['allowed_executables']
            assert candidate == [str(new)]
            seen.append(raw)
            return publish(path, raw, expected, revalidate)
        monkeypatch.setattr(api, '_publish', capture)
        listed = await call(state, 'files_allowlist_list', {'profile_id': 'B'})
        result = await call(state, 'files_allowlist_replace', dict(profile_id='B', executable=state.exe,
            replacement_executable=str(new), expected_revision=listed['revision']))
        assert len(seen) == 1
        assert result['removed'] == [state.exe] and result['added'] == [str(new)]
        assert commands.resolve_executable(str(new), command_grant(state)) == new
        with pytest.raises(PermissionError):
            commands.resolve_executable(state.exe, command_grant(state))
    asyncio.run(run())


def test_add_publishes_to_real_command_consumer_without_other_changes(state):
    async def run():
        before = json.loads(commands.POLICY_FILE.read_text())
        new = state.root / ('added.exe' if os.name == 'nt' else 'added')
        shutil.copyfile(sys.executable, new)
        new.chmod(0o700)
        listed = await call(state, 'files_allowlist_list', {'profile_id': 'B'})
        result = await call(state, 'files_allowlist_add', dict(profile_id='B', executable=str(new), expected_revision=listed['revision']))
        assert result['changed'] is True
        after = json.loads(commands.POLICY_FILE.read_text())
        assert after['profiles']['B']['allowed_executables'] == [state.exe, str(new)]
        after['profiles']['B']['allowed_executables'] = before['profiles']['B']['allowed_executables']
        assert after == before
        from app.core.execution_context import verify, TrustedMetadata
        context = new_context(state.auth, state.placement, 'files:execute', 'files_exec_command',
            resource_authorizer=state.authorizer, selected_profile_id='B')
        authority = verify(TrustedMetadata({'zagent.execution_context': context}), 'files_exec_command', {})
        grant = commands.authorize_command_call('files_exec_command', {}, authority)
        assert commands.resolve_executable(str(new), grant) == new
    asyncio.run(run())
