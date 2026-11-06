"""Windows owner-account execution-mode regression with disposable files."""
from __future__ import annotations
import asyncio
import json
import os
from pathlib import Path
import sys
import time

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Windows owner job required')

from app.core.execution_context import CURRENT, VerifiedContext
from app.mcp import managed_commands as m


@pytest.fixture
def profile(tmp_path, monkeypatch):
    root = tmp_path / 'repo'
    root.mkdir()
    config = tmp_path / 'config'
    config.mkdir()
    monkeypatch.setattr(m, 'PROFILES_FILE', config / 'profiles.json')
    monkeypatch.setattr(m, 'POLICY_FILE', config / 'no-command-policy.json')
    monkeypatch.setattr(m, 'AUDIT_LOG', tmp_path / 'audit.jsonl')
    row = dict(name='dev', root=str(root), mode='read-write', enabled=True,
               authorized_by_user=True, execution_access='developer')
    def save():
        m.PROFILES_FILE.write_text(json.dumps({'profiles': [row]}), encoding='utf-8')
    save()
    ctx = VerifiedContext(principal_id='owner', workspace_id='test',
        public_tool='files_git', effective_access='write', required_scope='files:execute',
        scopes=['files:execute', 'files:write'], expires_at=time.time()+120,
        deadline=time.time()+120,
        effective_resources=[dict(kind='files',resource_id='owned-dev',profile_id='dev')])
    return root,row,save,ctx


def scoped(ctx, tool):
    return VerifiedContext(ctx, public_tool=tool)


def test_developer_mode_without_manual_policy(profile):
    root,row,save,ctx=profile
    grant=m.authorize_command_call('files_git', {'cwd':'.'},ctx)
    assert grant.mode == 'developer'
    assert grant.root == root and grant.timeout == 900
    assert not m.POLICY_FILE.exists()


def test_developer_denies_powershell_and_other_owner_commands(profile):
    root,row,save,ctx=profile
    for tool in ('files_powershell_run', 'files_process_start'):
        with pytest.raises(PermissionError,match='TOOL_NOT_AVAILABLE_IN_PROFILE_MODE'):
            m.authorize_command_call(tool, {},scoped(ctx,tool))


def test_disabled_read_only_and_owner_preconditions(profile):
    root,row,save,ctx=profile
    row['execution_access']='disabled'
    save()
    with pytest.raises(PermissionError,match='PROFILE_EXECUTION_DISABLED'):
        m.authorize_command_call('files_git',{},ctx)
    row['execution_access']='developer'
    row['mode']='read-only'
    save()
    with pytest.raises(PermissionError,match='LOCALLY_APPROVED_READ_WRITE_PROFILE_REQUIRED'):
        m.authorize_command_call('files_git',{},ctx)
    row['mode']='read-write'
    row['authorized_by_user']=False
    save()
    with pytest.raises(PermissionError,match='LOCALLY_APPROVED_READ_WRITE_PROFILE_REQUIRED'):
        m.authorize_command_call('files_git',{},ctx)


def test_invalid_mode_and_missing_scopes_fail_closed(profile):
    root,row,save,ctx=profile
    row['execution_access']='arbitrary'
    save()
    with pytest.raises(PermissionError,match='PROFILE_EXECUTION_DISABLED'):
        m.authorize_command_call('files_git',{},ctx)
    row['execution_access']='developer'
    save()
    with pytest.raises(PermissionError,match='COMMAND_EXECUTE_AND_WRITE_SCOPES_REQUIRED'):
        m.authorize_command_call('files_git',{},VerifiedContext(ctx,scopes=['files:execute']))


def test_full_requires_owner_mode_and_accepts_absolute_installed_exe(profile):
    root,row,save,ctx=profile
    row['execution_access']='full'
    save()
    grant=m.authorize_command_call('files_exec_command',{},
        scoped(ctx,'files_exec_command'))
    assert grant.mode=='full'
    assert 'files_powershell_run' in m._mode_tools(grant.mode)
    path=m.resolve_executable(sys.executable,grant)
    assert path.is_file() and path.suffix.casefold()=='.exe'
    row['execution_access']='developer'
    save()
    other=m.authorize_command_call('files_exec_command',{},
        scoped(ctx,'files_exec_command'))
    # python.exe is a recognized Developer binary only if discovered; an
    # unrelated installed native executable must not be allowed by path.
    outside=Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32/cmd.exe'
    if outside.is_file():
        with pytest.raises(PermissionError,match='EXECUTABLE_NOT_EXPLICITLY_APPROVED'):
            m.resolve_executable(str(outside),other)


def test_developer_binary_resolution_ignores_untrusted_path(profile,monkeypatch,tmp_path):
    root,row,save,ctx=profile
    imposter=tmp_path/'git.exe'
    imposter.write_bytes(b'not an executable')
    monkeypatch.setenv('PATH',str(tmp_path))
    grant=m.authorize_command_call('files_git',{},ctx)
    assert imposter not in grant.executables
    if any(p.name.lower()=='git.exe' for p in grant.executables):
        assert m.resolve_executable('git',grant)!=imposter


def test_windows_git_read_only_smoke(profile):
    root,row,save,ctx=profile
    if not any(x.name.casefold()=='git.exe' for x in m._trusted_executables('developer')):
        pytest.skip('Git is not installed in recognized Windows locations')
    token=CURRENT.set(ctx)
    try:
        result=asyncio.run(m.execute('files_git',{'args':['--version'],
                      'cwd':'.','timeout_seconds':20}))
        assert result['ok'],result['stderr']
        assert 'git version' in result['stdout'].lower()
        assert (m.AUDIT_LOG).is_file()
    finally:
        CURRENT.reset(token)


def test_native_full_exec_smoke(profile):
    root,row,save,ctx=profile
    row['execution_access']='full'
    save()
    current=scoped(ctx,'files_exec_command')
    token=CURRENT.set(current)
    try:
        result=asyncio.run(m.execute('files_exec_command',
            {'executable':sys.executable,'args':['--version'],'timeout_seconds':15}))
        assert result['ok'],result['stderr']
        assert 'Python' in result['stdout'] or 'Python' in result['stderr']
    finally:
        CURRENT.reset(token)


def test_developer_python_node_npm_build_test(profile):
    root,row,save,ctx=profile
    names={p.name.casefold() for p in m._trusted_executables('developer')}
    if not {'python.exe','node.exe','npm.cmd'}.issubset(names):
        pytest.skip('Python, Node, and npm require recognized installed paths')
    (root/'package.json').write_text(json.dumps(dict(
        name='zagent-profile-execution-disposable',version='1.0.0',
        scripts={'build':'node -e "require(\'fs\').writeFileSync(\'build-ok.txt\',\'yes\')"',
                 'test':'node -e "if(require(\'fs\').readFileSync(\'build-ok.txt\',\'utf8\')!==\'yes\')process.exit(1)"'})),
        encoding='utf-8')
    operations=[
        ('files_exec_command',{'executable':'python','args':['--version'],'timeout_seconds':20}),
        ('files_node',{'args':['--version'],'timeout_seconds':20}),
        ('files_build',{'script':'build','timeout_seconds':40}),
        ('files_test',{'script':'test','timeout_seconds':40}),
    ]
    for tool,args in operations:
        token=CURRENT.set(scoped(ctx,tool))
        try:
            result=asyncio.run(m.execute(tool,args))
            assert result['ok'],(tool,result.get('stderr'))
        finally:
            CURRENT.reset(token)
    assert (root/'build-ok.txt').read_text(encoding='utf-8')=='yes'
