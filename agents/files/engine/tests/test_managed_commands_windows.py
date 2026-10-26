"""Windows behavioral fixtures. NOT executed on the source-only authoring host."""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='owner-account Windows executor')
from app.core.execution_context import VerifiedContext, CURRENT
from app.mcp import managed_commands as m


@pytest.fixture
def approved(tmp_path, monkeypatch):
    root = tmp_path / 'work'
    root.mkdir()
    config = tmp_path / 'config'
    config.mkdir()
    monkeypatch.setattr(m, 'PROFILES_FILE', config / 'profiles.json')
    monkeypatch.setattr(m, 'POLICY_FILE', config / 'remote_execution_policy.json')
    monkeypatch.setattr(m, 'AUDIT_LOG', tmp_path / 'audit.jsonl')
    m.PROFILES_FILE.write_text(json.dumps({'profiles': [dict(name='appBridge', root=str(root), mode='read-write', enabled=True, authorized_by_user=True)]}))
    policy = dict(version=1, enabled=True, execution_mode='owner-account', acknowledge_host_access=True,
                  profile_id='appBridge', root=str(root), allowed_tools=sorted(m.COMMAND_TOOL_NAMES),
                  allowed_executables=[str(Path(sys.executable).resolve())], max_timeout_seconds=5, max_output_chars=1024)
    m.POLICY_FILE.write_text(json.dumps(policy))
    context = VerifiedContext(principal_id='p', workspace_id='w', public_tool='files_exec_command',
                              effective_access='write', required_scope='files:execute', scopes=['files:execute', 'files:write'],
                              expires_at=time.time() + 120, deadline=time.time() + 120,
                              effective_resources=[dict(kind='files', resource_id='f', profile_id='appBridge')])
    return root, policy, context


def test_explicit_context_and_exact_scope_required(approved):
    root, policy, context = approved
    args = dict(profile='appBridge')
    assert m.authorize_command_call('files_exec_command', args, context).root == root
    for authority in (dict(context), None):
        with pytest.raises(PermissionError):
            m.authorize_command_call('files_exec_command', args, authority)
    for changes in (dict(public_tool='files_git'), dict(scopes=['files:execute']),
                    dict(effective_access='read'), dict(expires_at=time.time()-1),
                    dict(effective_resources=[]), dict(effective_resources=context['effective_resources']*2)):
        with pytest.raises(PermissionError):
            m.authorize_command_call('files_exec_command', args, VerifiedContext(context, **changes))
    with pytest.raises(PermissionError):
        m.authorize_command_call('files_exec_command', dict(profile='other'), context)
    assert m.authorize_command_call('files_exec_command', {}, context).profile == 'appBridge'


def test_deadline_exact_marker_and_optional_identity(approved):
    root, policy, context = approved
    class Derived(VerifiedContext):
        pass
    with pytest.raises(PermissionError):
        m.authorize_command_call('files_exec_command', {}, Derived(context))
    with pytest.raises(PermissionError):
        m.authorize_command_call('files_exec_command', {}, VerifiedContext(context, deadline=time.time()-1))
    for field in ('device_id', 'installation_id'):
        resource = dict(context['effective_resources'][0], **{field: 'different'})
        with pytest.raises(PermissionError):
            m.authorize_command_call('files_exec_command', {}, VerifiedContext(context, effective_resources=[resource]))
        profiles = json.loads(m.PROFILES_FILE.read_text(encoding='utf-8'))
        profiles['profiles'][0][field] = 'different'
        m.PROFILES_FILE.write_text(json.dumps(profiles))
        with pytest.raises(PermissionError):
            m.authorize_command_call('files_exec_command', {}, context)
        del profiles['profiles'][0][field]
        m.PROFILES_FILE.write_text(json.dumps(profiles))


@pytest.mark.parametrize('tool', sorted(m.UNSUPPORTED_COMMAND_TOOLS))
def test_unsupported_tool_is_explicitly_fail_closed(approved, tool):
    root, policy, context = approved
    token = CURRENT.set(VerifiedContext(context, public_tool=tool))
    try:
        with pytest.raises(NotImplementedError, match='UNSUPPORTED_MANAGED_COMMAND'):
            asyncio.run(m.execute(tool, {}))
    finally:
        CURRENT.reset(token)


def test_capabilities_do_not_claim_batch_or_persistent_support(approved):
    root, policy, context = approved
    token = CURRENT.set(VerifiedContext(context, public_tool='files_command_capabilities'))
    try:
        result = asyncio.run(m.execute('files_command_capabilities', {}))
        assert not result['os_sandbox'] and not result['batch_wrappers']
        assert set(result['supports']) == m.SUPPORTED_COMMAND_TOOLS
        assert set(result['unsupported']) == m.UNSUPPORTED_COMMAND_TOOLS
    finally:
        CURRENT.reset(token)


@pytest.mark.parametrize('change', [dict(version=2), dict(enabled=False), dict(acknowledge_host_access=False),
    dict(execution_mode='sandbox'), dict(max_timeout_seconds=True), dict(max_timeout_seconds=1801),
    dict(max_output_chars=200001), dict(allowed_executables=['python.exe']), dict(unknown=True)])
def test_policy_fail_closed(approved, change):
    root, policy, context = approved
    m.POLICY_FILE.write_text(json.dumps(dict(policy, **change)))
    with pytest.raises(PermissionError):
        m.authorize_command_call('files_exec_command', {}, context)


def test_missing_malformed_policy_and_local_revocation(approved):
    root, policy, context = approved
    for data in ('', '{', 'null', '{}'):
        m.POLICY_FILE.write_text(data)
        with pytest.raises(PermissionError):
            m.authorize_command_call('files_exec_command', {}, context)
    m.POLICY_FILE.unlink()
    with pytest.raises(PermissionError):
        m.authorize_command_call('files_exec_command', {}, context)
    m.POLICY_FILE.write_text(json.dumps(policy))
    m.PROFILES_FILE.write_text(json.dumps({'profiles': [dict(name='appBridge', root=str(root), mode='read-only', enabled=True, authorized_by_user=True)]}))
    with pytest.raises(PermissionError):
        m.authorize_command_call('files_exec_command', {}, context)


def test_resolver_environment_and_root(approved, monkeypatch):
    root, policy, context = approved
    grant = m.authorize_command_call('files_exec_command', {}, context)
    assert m.resolve_executable('python.exe', grant) == Path(sys.executable).resolve()
    with pytest.raises(PermissionError):
        m.resolve_executable(str(root / 'python.exe'), grant)
    with pytest.raises(PermissionError):
        m.resolve_cwd(grant, '..')
    monkeypatch.setenv('ZAGENT_INTERNAL_TOKEN', 'never-in-child')
    monkeypatch.setenv('OAUTH_CLIENT_SECRET', 'never-in-child')
    monkeypatch.setenv('PATH', str(root))
    env = m.child_environment(grant)
    assert not any('ZAGENT' in k.upper() or 'SECRET' in k.upper() or 'OAUTH' in k.upper() for k in env)
    assert str(root) not in env['PATH'].split(os.pathsep)


def test_owner_record_never_accepts_pid_or_session_as_authority(approved):
    root, policy, context = approved
    grant = m.authorize_command_call('files_exec_command', {}, context)
    with pytest.raises(PermissionError):
        m.owned_record('unknown', grant)
    assert m.list_owned(grant) == []


def test_bounded_output_and_no_ambient_secrets(approved, monkeypatch):
    root, policy, context = approved
    monkeypatch.setenv('ZAGENT_INTERNAL_TOKEN', 'secret-never-forward')
    token = CURRENT.set(context)
    try:
        result = asyncio.run(m.execute('files_exec_command', dict(executable=sys.executable, args=['-c',
            "import os,sys; print(os.getenv('ZAGENT_INTERNAL_TOKEN')); sys.stdout.write('x'*1000000); sys.stderr.write('e'*1000000)"])))
        assert result['ok'] and len(result['stdout']) <= 1024 and len(result['stderr']) <= 1024
        assert result['stdout_truncated'] and result['stderr_truncated']
        assert result['stdout'].startswith('None')
        assert 'secret-never-forward' not in m.AUDIT_LOG.read_text(encoding='utf-8')
    finally:
        CURRENT.reset(token)


def test_persistent_start_fails_closed(approved):
    root, policy, context = approved
    context['public_tool'] = 'files_process_start'
    token = CURRENT.set(context)
    try:
        with pytest.raises(NotImplementedError):
            asyncio.run(m.execute('files_process_start', dict(executable=sys.executable, args=[])))
    finally:
        CURRENT.reset(token)


def _still_running(pid):
    import ctypes
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
    kernel.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        assert ctypes.get_last_error() == 87, 'unexpected process query error'
        return False
    try:
        code = w.DWORD()
        assert kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        return code.value == 259
    finally:
        kernel.CloseHandle(handle)


def test_timeout_kills_descendants_without_pipe_deadlock(approved):
    root, policy, context = approved
    child_pid = root / 'child.pid'
    script = ("import subprocess,sys,time,pathlib; "
              "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(90)']); "
              "pathlib.Path('child.pid').write_text(str(p.pid)); time.sleep(90)")
    token = CURRENT.set(context)
    try:
        with pytest.raises(TimeoutError):
            asyncio.run(m.execute('files_exec_command', dict(executable=sys.executable, args=['-c', script], timeout_seconds=2)))
        assert child_pid.exists(), 'child must start before timeout; increase timeout if Windows host is slow'
        pid = int(child_pid.read_text(encoding='utf-8'))
        until = time.monotonic() + 5
        while _still_running(pid) and time.monotonic() < until:
            time.sleep(0.02)
        assert not _still_running(pid)
        assert not m._RECORDS
    finally:
        CURRENT.reset(token)


def test_unowned_stop_never_launches_host_killer(approved):
    root, policy, context = approved
    context['public_tool'] = 'files_process_stop'
    token = CURRENT.set(context)
    try:
        for unmanaged in (False, True):
            with pytest.raises(PermissionError):
                asyncio.run(m.execute('files_process_stop', dict(pid=os.getpid(), confirm_unmanaged=unmanaged)))
    finally:
        CURRENT.reset(token)


def test_batch_wrapper_and_metacharacters_are_not_shell_wrapped(approved):
    root, policy, context = approved
    batch = root / 'npm.cmd'
    batch.write_text('@exit /b 0')
    policy['allowed_executables'].append(str(batch))
    m.POLICY_FILE.write_text(json.dumps(policy))
    grant = m.authorize_command_call('files_exec_command', {}, context)
    with pytest.raises(NotImplementedError):
        m._command('files_exec_command', dict(executable=str(batch), args=['&', 'whoami']), grant)


@pytest.fixture
def npm_distribution(approved):
    root, policy, context = approved
    distribution = root / 'approved-node'
    distribution.mkdir()
    node = distribution / 'node.exe'
    node.write_bytes(b'fixture-path-only-not-executed')
    for name in ('npm.cmd', 'npx.cmd'):
        (distribution / name).write_text('@echo shim-must-never-run')
    cli_dir = distribution / 'node_modules' / 'npm' / 'bin'
    cli_dir.mkdir(parents=True)
    for name in ('npm-cli.js', 'npx-cli.js'):
        (cli_dir / name).write_text('// path-resolution fixture, not actual npm')
    policy['allowed_executables'].extend(str(distribution / name) for name in ('node.exe', 'npm.cmd', 'npx.cmd'))
    m.POLICY_FILE.write_text(json.dumps(policy))
    return approved, distribution


@pytest.mark.parametrize('tool,args,filename,tail', [
    ('files_npm', {'args': ['--version', '&', 'whoami']}, 'npm-cli.js', ['--version', '&', 'whoami']),
    ('files_npx', {'args': ['--version']}, 'npx-cli.js', ['--version']),
    ('files_build', {}, 'npm-cli.js', ['run', 'build']),
    ('files_test', {'script': 'test:unit'}, 'npm-cli.js', ['run', 'test:unit']),
])
def test_npm_dispatch_uses_fixed_cli_no_shell(npm_distribution, tool, args, filename, tail):
    (root, policy, context), distribution = npm_distribution
    grant = m.authorize_command_call(tool, {}, VerifiedContext(context, public_tool=tool))
    exe, argv = m._command(tool, args, grant)
    assert exe == distribution / 'node.exe'
    assert argv == [str(distribution / 'node_modules' / 'npm' / 'bin' / filename), *tail]
    assert not any(str(distribution / name) in argv for name in ('npm.cmd', 'npx.cmd'))


def test_npm_requires_both_approvals_and_existing_fixed_cli(npm_distribution):
    (root, policy, context), distribution = npm_distribution
    for missing in ('node.exe', 'npm.cmd'):
        reduced = dict(policy, allowed_executables=[p for p in policy['allowed_executables'] if Path(p).name != missing])
        m.POLICY_FILE.write_text(json.dumps(reduced))
        grant = m.authorize_command_call('files_exec_command', {}, context)
        with pytest.raises(PermissionError):
            m._command('files_npm', {'args': []}, grant)
    m.POLICY_FILE.write_text(json.dumps(policy))
    grant = m.authorize_command_call('files_exec_command', {}, context)
    (distribution / 'node_modules/npm/bin/npm-cli.js').unlink()
    with pytest.raises(PermissionError, match='APPROVED_NPM_DISTRIBUTION_CLI_UNAVAILABLE_OR_REPARSE'):
        m._command('files_npm', {'args': []}, grant)


@pytest.mark.parametrize('script', ['', '-x', 'build & whoami', '../build', 'x'*129, None])
def test_npm_script_name_is_bounded(npm_distribution, script):
    (root, policy, context), distribution = npm_distribution
    grant = m.authorize_command_call('files_exec_command', {}, context)
    with pytest.raises(ValueError, match='BOUNDED_NPM_SCRIPT_NAME_REQUIRED'):
        m._command('files_build', {'script': script}, grant)


def test_npm_cli_symlink_is_rejected(npm_distribution):
    (root, policy, context), distribution = npm_distribution
    cli = distribution / 'node_modules/npm/bin/npm-cli.js'
    outside = root / 'outside.js'
    outside.write_text('// must not be followed')
    cli.unlink()
    try:
        cli.symlink_to(outside)
    except OSError:
        pytest.skip('Windows symlink creation requires owner Developer Mode or privilege')
    grant = m.authorize_command_call('files_exec_command', {}, context)
    with pytest.raises(PermissionError, match='APPROVED_NPM_DISTRIBUTION_CLI_UNAVAILABLE_OR_REPARSE'):
        m._command('files_npm', {'args': []}, grant)


def test_real_installed_npm_build_and_test_without_shim_execution(approved):
    import shutil
    root, policy, context = approved
    node, shim = shutil.which('node.exe'), shutil.which('npm.cmd')
    if not node or not shim:
        pytest.skip('Real Windows node.exe/npm.cmd installation required for npm smoke gate')
    cli = Path(shim).parent / 'node_modules/npm/bin/npm-cli.js'
    if not cli.is_file():
        pytest.skip('Installed npm has no supported fixed sibling CLI layout')
    policy['allowed_executables'].extend([str(Path(node).resolve()), str(Path(shim).resolve())])
    policy['max_timeout_seconds'] = 30
    m.POLICY_FILE.write_text(json.dumps(policy))
    (root / 'package.json').write_text(json.dumps(dict(name='zagent-disposable-npm-fixture', version='1.0.0',
        scripts={'build': 'node -e "require(\'fs\').writeFileSync(\'built.txt\',\'ok\')"',
                 'test': 'node -e "if(require(\'fs\').readFileSync(\'built.txt\',\'utf8\')!==\'ok\')process.exit(1)"'})))
    for tool in ('files_build', 'files_test'):
        token = CURRENT.set(VerifiedContext(context, public_tool=tool))
        try:
            result = asyncio.run(m.execute(tool, {}))
            assert result['ok'], result['stderr']
        finally:
            CURRENT.reset(token)
    assert (root / 'built.txt').read_text(encoding='utf-8') == 'ok'


def test_registry_is_principal_workspace_profile_resource_scoped(approved):
    root, policy, context = approved
    grant = m.authorize_command_call('files_exec_command', {}, context)
    with m._LOCK:
        m._RECORDS['fixture'] = dict(owner=grant.owner, pid=1)
    try:
        assert m.owned_record('fixture', grant)['pid'] == 1
        for changes in (dict(principal_id='other'), dict(workspace_id='other'),
                        dict(effective_resources=[dict(kind='files', resource_id='other', profile_id='appBridge')])):
            other = m.authorize_command_call('files_exec_command', {}, VerifiedContext(context, **changes))
            assert m.list_owned(other) == []
            with pytest.raises(PermissionError):
                m.owned_record('fixture', other)
    finally:
        with m._LOCK:
            del m._RECORDS['fixture']


def test_cancel_does_not_trust_session_or_unrelated_owner(approved):
    root, policy, context = approved
    context['task_id'] = 'owned-task'
    async def scenario():
        token = CURRENT.set(context)
        try:
            running = asyncio.create_task(m.execute('files_exec_command', dict(executable=sys.executable,
                args=['-c', 'import time; time.sleep(90)'])))
            until = time.monotonic() + 3
            while not m._RECORDS and time.monotonic() < until:
                await asyncio.sleep(0.01)
            assert 'owned-task' in m._RECORDS
            other = VerifiedContext(context, principal_id='other', public_tool='files_command_cancel')
            CURRENT.set(other)
            with pytest.raises(PermissionError):
                await m.execute('files_command_cancel', dict(task_id='owned-task', session_id='fake-owner'))
            CURRENT.set(VerifiedContext(context, public_tool='files_command_cancel'))
            result = await m.execute('files_command_cancel', dict(task_id='owned-task', session_id='not-authority'))
            assert result['process_tree_termination_requested']
            try:
                result = await running
                assert not result['ok']
            except InterruptedError:
                pass
            assert not m._RECORDS
        finally:
            CURRENT.reset(token)
    asyncio.run(scenario())


def test_job_assignment_failure_never_runs_child(approved, monkeypatch):
    root, policy, context = approved
    marker = root / 'should-not-exist'
    def deny(self, proc):
        raise OSError('test assignment denial before resume')
    monkeypatch.setattr(m._WindowsJob, 'assign_and_resume', deny)
    token = CURRENT.set(context)
    try:
        with pytest.raises(OSError):
            asyncio.run(m.execute('files_exec_command', dict(executable=sys.executable,
                args=['-c', "from pathlib import Path; Path('should-not-exist').touch()"])))
        assert not marker.exists()
        assert not m._RECORDS
    finally:
        CURRENT.reset(token)
