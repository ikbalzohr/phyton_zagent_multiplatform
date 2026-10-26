"""Windows-only Lane B regressions; run through disposable runner, not directly."""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

# Refuse product imports even during accidental collection on Linux.
if os.name != 'nt' or not os.environ.get('ZAGENT_COMMAND_MULTIPROFILE_FIXTURE_ROOT'):
    pytest.skip('NOT_RUN: disposable Windows runner required', allow_module_level=True)

_fixture_root = Path(os.environ['ZAGENT_COMMAND_MULTIPROFILE_FIXTURE_ROOT']).resolve()
for _key in ('DATA_ROOT', 'CONFIG_DIR', 'RUNTIME_DIR', 'LOG_DIR', 'BACKUP_ROOT', 'UPDATE_STATE_ROOT'):
    _path = Path(os.environ.get('ZAGENT_FILES_' + _key, '')).resolve()
    if _path != _fixture_root and _fixture_root not in _path.parents:
        pytest.skip('NOT_RUN: all product paths must be disposable', allow_module_level=True)

from app.core.execution_context import CURRENT, VerifiedContext
from app.mcp import managed_commands as m
from app.mcp.command_tools import register_command_tools
from app.profiles import manager


@pytest.fixture
def multi(tmp_path, monkeypatch):
    roots = {name: tmp_path / name for name in ('A', 'B')}
    for root in roots.values():
        root.mkdir()
    for attr, filename in (('POLICY_FILE', 'policy.json'), ('PROFILES_FILE', 'profiles.json'), ('AUDIT_LOG', 'audit.jsonl')):
        monkeypatch.setattr(m, attr, tmp_path / filename)
    monkeypatch.setattr(manager, 'PROFILES_FILE', m.PROFILES_FILE)
    policies = {name: dict(version=1, enabled=True, execution_mode='owner-account', acknowledge_host_access=True,
        profile_id=name, root=str(root), allowed_tools=sorted(m.COMMAND_TOOL_NAMES),
        allowed_executables=[str(Path(sys.executable).resolve())], max_timeout_seconds=30,
        max_output_chars=1024 if name == 'A' else 2048) for name, root in roots.items()}
    envelope = dict(version=2, profiles=policies)
    m.POLICY_FILE.write_text(json.dumps(envelope), encoding='utf-8')
    m.PROFILES_FILE.write_text(json.dumps(dict(schema_version='2.0', active_profile='A', profiles=[dict(name=name, root=str(root), enabled=True,
        authorized_by_user=True, mode='read-write') for name, root in roots.items()])), encoding='utf-8')
    def context(name, tool='files_exec_command', **changes):
        return VerifiedContext(dict(principal_id='same-owner', workspace_id='same-workspace', public_tool=tool,
            effective_access='write', required_scope='files:execute', scopes=['files:execute', 'files:write'],
            expires_at=time.time()+120, deadline=time.time()+120,
            effective_resources=[dict(kind='files', resource_id='same-resource', profile_id=name)]), **changes)
    assert not m._RECORDS
    yield roots, envelope, context
    assert not m._RECORDS


def save(envelope):
    m.POLICY_FILE.write_text(json.dumps(envelope), encoding='utf-8')


def test_command_generation_and_owner_namespace(multi):
    from app.profiles.administration import profile_generation
    roots, envelope, context = multi
    state = json.loads(m.PROFILES_FILE.read_text())
    row = next(p for p in state['profiles'] if p['name'] == 'A')
    authority = context('A')
    authority['effective_resources'][0]['profile_generation'] = profile_generation(row, state)
    first = m.authorize_command_call('files_exec_command', {}, authority)
    state['owner_management'] = {'version':1,'revision':'0'*64,'owners':{},'operations':[],
        'generations':{'A':'new-generation','B':'b-generation'}}
    m.PROFILES_FILE.write_text(json.dumps(state), encoding='utf-8')
    with pytest.raises(PermissionError, match='PROFILE_GENERATION_MISMATCH'):
        m.authorize_command_call('files_exec_command', {}, authority)
    authority['effective_resources'][0]['profile_generation'] = 'new-generation'
    assert m.authorize_command_call('files_exec_command', {}, authority).owner != first.owner
    del authority['effective_resources'][0]['profile_generation']
    with pytest.raises(PermissionError, match='PROFILE_GENERATION_MISMATCH'):
        m.authorize_command_call('files_exec_command', {}, authority)


def test_v2_selected_resource_not_first_and_v1_read_only(multi):
    roots, envelope, context = multi
    before = m.POLICY_FILE.read_bytes()
    for name in ('B', 'A'):
        grant = m.authorize_command_call('files_exec_command', {}, context(name))
        assert grant.profile == name and grant.root == roots[name]
        omitted = m.authorize_command_call('files_exec_command', {'profile': None}, context(name))
        assert omitted.profile == name and omitted.root == roots[name]
        with pytest.raises(PermissionError, match='PROFILE_NOT_IN_RESOURCE_SCOPE'):
            m.authorize_command_call('files_exec_command', {'profile': 'A' if name == 'B' else 'B'}, context(name))
    assert m.POLICY_FILE.read_bytes() == before
    save(envelope['profiles']['B'])
    legacy = m.POLICY_FILE.read_bytes()
    assert m.authorize_command_call('files_exec_command', {}, context('B')).root == roots['B']
    with pytest.raises(PermissionError):
        m.authorize_command_call('files_exec_command', {}, context('A'))
    assert m.POLICY_FILE.read_bytes() == legacy


@pytest.mark.parametrize('change', ['extra', 'empty', 'oversize', 'wildcard', 'mismatch', 'entry_extra', 'entry_v2', 'bool_version', 'missing'])
def test_strict_envelope(multi, change):
    roots, envelope, context = multi
    if change == 'extra': envelope['default_profile_id'] = 'A'
    if change == 'empty': envelope['profiles'] = {}
    if change == 'oversize': envelope['profiles'] = {str(i): dict(envelope['profiles']['A'], profile_id=str(i)) for i in range(129)}
    if change == 'wildcard': envelope['profiles']['*'] = dict(envelope['profiles']['A'], profile_id='*')
    if change == 'mismatch': envelope['profiles']['A']['profile_id'] = 'B'
    if change == 'entry_extra': envelope['profiles']['A']['lease'] = {}
    if change == 'entry_v2': envelope['profiles']['A']['version'] = 2
    if change == 'bool_version': envelope['version'] = True
    if change == 'missing': del envelope['profiles']['B']
    save(envelope)
    with pytest.raises(PermissionError):
        m.authorize_command_call('files_exec_command', {}, context('B'))


def test_duplicate_keys_rejected(multi):
    _, envelope, context = multi
    m.POLICY_FILE.write_text('{"version":2,"profiles":{},"profiles":'+json.dumps(envelope['profiles'])+'}', encoding='utf-8')
    with pytest.raises(PermissionError):
        m.authorize_command_call('files_exec_command', {}, context('B'))


@pytest.mark.parametrize('change', [dict(enabled=False), dict(root='missing'), dict(acknowledge_host_access=False), dict(max_timeout_seconds=True)])
def test_reload_and_selected_entry_denial_leaves_other_profile_valid(multi, change):
    _, envelope, context = multi
    assert m.authorize_command_call('files_exec_command', {}, context('A'))
    envelope['profiles']['A'].update(change)
    save(envelope)
    with pytest.raises(PermissionError):
        m.authorize_command_call('files_exec_command', {}, context('A'))
    assert m.authorize_command_call('files_exec_command', {}, context('B')).profile == 'B'


def test_profile_removed_local_approval_expiry_scopes_and_root(multi):
    roots, envelope, context = multi
    for changes in (dict(expires_at=time.time()-1), dict(scopes=['files:execute']),
                    dict(effective_resources=[dict(kind='files', resource_id='same-resource', profile_id='B', revoked=True)])):
        with pytest.raises(PermissionError):
            m.authorize_command_call('files_exec_command', {}, context('B', **changes))
    envelope['profiles']['B']['root'] = str(roots['A'])
    save(envelope)
    with pytest.raises(PermissionError, match='COMMAND_POLICY_ROOT_MISMATCH'):
        m.authorize_command_call('files_exec_command', {}, context('B'))
    envelope['profiles']['B']['root'] = str(roots['B'])
    save(envelope)
    rows = json.loads(m.PROFILES_FILE.read_text())
    rows['profiles'] = rows['profiles'][:1]
    m.PROFILES_FILE.write_text(json.dumps(rows))
    with pytest.raises(PermissionError, match='LOCAL_PROFILE_REQUIRED'):
        m.authorize_command_call('files_exec_command', {}, context('B'))


def test_per_profile_executable_and_cwd_bounds(multi):
    roots, envelope, context = multi
    # Path-only allowlist fixture: this file must never be launched.
    only_a = roots['A'] / 'approved-only-a.exe'
    only_a.write_bytes(b'path-validation-fixture-not-executed')
    envelope['profiles']['A']['allowed_executables'].append(str(only_a))
    save(envelope)
    grants = {name: m.authorize_command_call('files_exec_command', {}, context(name)) for name in ('A', 'B')}
    assert m.resolve_executable(str(only_a), grants['A']) == only_a
    with pytest.raises(PermissionError, match='EXECUTABLE_NOT_EXPLICITLY_APPROVED'):
        m.resolve_executable(str(only_a), grants['B'])
    for name, grant in grants.items():
        assert m.resolve_cwd(grant, '.') == roots[name]
        with pytest.raises(PermissionError, match='WORKING_DIRECTORY_OUTSIDE_RESOURCE'):
            m.resolve_cwd(grant, '..')


def test_public_omission_derives_selected_profile(multi):
    _, _, context = multi
    class Catalog:
        tools = {}
        def tool(self):
            def register(fn):
                self.tools[fn.__name__] = fn
                return fn
            return register
    catalog = Catalog()
    register_command_tools(catalog)
    token = CURRENT.set(context('B'))
    try:
        result = asyncio.run(catalog.tools['files_exec_command'](sys.executable, ['-c', 'import os; print(os.getcwd())']))
        assert result['ok'] and result['profile'] == 'B'
    finally:
        CURRENT.reset(token)


def test_concurrent_owned_list_cancel_stop_isolation(multi, monkeypatch):
    roots, _, context = multi
    processes = {}
    original = m.subprocess.Popen
    def create(*args, **kwargs):
        proc = original(*args, **kwargs)
        processes[kwargs['cwd']] = proc
        return proc
    monkeypatch.setattr(m.subprocess, 'Popen', create)
    async def invoke(name, tool, args, **changes):
        token = CURRENT.set(context(name, tool, **changes))
        try:
            return await m.execute(tool, args)
        finally:
            CURRENT.reset(token)
    async def scenario():
        tasks = {name: asyncio.create_task(invoke(name, 'files_exec_command', dict(executable=sys.executable,
            args=['-c', 'import time; time.sleep(90)']), operation_id='lane-b-'+name)) for name in ('A', 'B')}
        try:
            until = time.monotonic()+10
            while len(m._RECORDS) < 2 and time.monotonic() < until:
                await asyncio.sleep(.02)
            assert set(m._RECORDS) == {'lane-b-A', 'lane-b-B'}
            listings = {name: (await invoke(name, 'files_process_list', {}))['processes'] for name in ('A', 'B')}
            for name in ('A', 'B'):
                assert len(listings[name]) == 1 and listings[name][0]['profile'] == name
            with pytest.raises(PermissionError, match='OWNED_COMMAND_RECORD_REQUIRED'):
                await invoke('A', 'files_command_cancel', dict(task_id='lane-b-B'))
            with pytest.raises(PermissionError, match='OWNED_COMMAND_RECORD_REQUIRED'):
                await invoke('A', 'files_process_stop', dict(pid=listings['B'][0]['pid']))
            await invoke('A', 'files_command_cancel', dict(task_id='lane-b-A'))
            await asyncio.gather(tasks['A'], return_exceptions=True)
            assert processes[str(roots['A'])].poll() is not None
            assert processes[str(roots['B'])].poll() is None
            assert not m._RECORDS['lane-b-B']['cancel'].is_set()
            await invoke('B', 'files_process_stop', dict(pid=listings['B'][0]['pid']))
        finally:
            for task in tasks.values():
                if not task.done(): task.cancel()
            await asyncio.gather(*tasks.values(), return_exceptions=True)
        assert not m._RECORDS
        assert all(proc.poll() is not None for proc in processes.values())
    asyncio.run(scenario())


def test_output_limits_and_secrets_per_profile(multi, monkeypatch):
    _, _, context = multi
    monkeypatch.setenv('ZAGENT_INTERNAL_TOKEN', 'lane-b-never-export')
    for name, limit in (('A', 1024), ('B', 2048)):
        token = CURRENT.set(context(name))
        try:
            result = asyncio.run(m.execute('files_exec_command', dict(executable=sys.executable,
                args=['-c', "import os; print(os.getenv('ZAGENT_INTERNAL_TOKEN')); print('x'*5000)"])))
            assert result['ok'] and result['stdout'].startswith('None')
            assert len(result['stdout']) == limit and result['stdout_truncated']
        finally:
            CURRENT.reset(token)
    assert 'lane-b-never-export' not in m.AUDIT_LOG.read_text()


@pytest.mark.parametrize('phase', ['worker', 'suspended'])
@pytest.mark.parametrize('change', ['disable', 'root', 'limits', 'local_revoke', 'default_change'])
def test_queued_and_pre_resume_approval_revalidation(multi, monkeypatch, phase, change):
    roots, envelope, context = multi
    authority = context('A')
    grant = m.authorize_command_call('files_exec_command', {}, authority)
    def mutate():
        if change == 'local_revoke':
            rows = json.loads(m.PROFILES_FILE.read_text())
            rows['profiles'][0]['authorized_by_user'] = False
            m.PROFILES_FILE.write_text(json.dumps(rows))
        elif change == 'default_change':
            # Local session default is not this queued operation's authority.
            rows = json.loads(m.PROFILES_FILE.read_text())
            rows['active_profile'] = 'B'
            m.PROFILES_FILE.write_text(json.dumps(rows))
            assert manager.default_profile_name() == 'B'
        else:
            envelope['profiles']['A'].update({'disable': dict(enabled=False),
                'root': dict(root=str(roots['B'])), 'limits': dict(max_output_chars=512)}[change])
            save(envelope)
    if phase == 'worker':
        mutate()
    else:
        original = m.subprocess.Popen
        def create(*args, **kwargs):
            proc = original(*args, **kwargs)
            mutate()
            return proc
        monkeypatch.setattr(m.subprocess, 'Popen', create)
    import threading
    args = dict(executable=sys.executable, args=['-c', "from pathlib import Path; Path('queued-marker').touch()"])
    if change == 'default_change':
        result = m._run_owned('files_exec_command', args, grant, threading.Event(), 'lane-b-queued', authority)
        assert result['ok'] and result['profile'] == 'A'
        assert (roots['A'] / 'queued-marker').exists() and not (roots['B'] / 'queued-marker').exists()
    else:
        with pytest.raises(PermissionError):
            m._run_owned('files_exec_command', args, grant, threading.Event(), 'lane-b-queued', authority)
        assert not (roots['A'] / 'queued-marker').exists() and not (roots['B'] / 'queued-marker').exists()
    assert not m._RECORDS


def test_assignment_failure_no_child_and_other_profile_survives(multi, monkeypatch):
    roots, _, context = multi
    original = m._WindowsJob.assign_and_resume
    def deny(self, proc):
        raise OSError('lane-b-before-resume-denial')
    monkeypatch.setattr(m._WindowsJob, 'assign_and_resume', deny)
    token = CURRENT.set(context('A'))
    try:
        with pytest.raises(OSError, match='lane-b-before-resume-denial'):
            asyncio.run(m.execute('files_exec_command', dict(executable=sys.executable,
                args=['-c', "from pathlib import Path; Path('never-created').touch()"])))
    finally:
        CURRENT.reset(token)
    assert not (roots['A'] / 'never-created').exists() and not m._RECORDS
    monkeypatch.setattr(m._WindowsJob, 'assign_and_resume', original)
    token = CURRENT.set(context('B'))
    try:
        assert asyncio.run(m.execute('files_exec_command', dict(executable=sys.executable, args=['-c', 'pass'])))['ok']
    finally:
        CURRENT.reset(token)
