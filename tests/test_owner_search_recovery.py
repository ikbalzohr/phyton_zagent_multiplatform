"""Disposable journal tests; never Windows owner/ACL acceptance."""
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'packaging/scripts/owner_search_recovery.py'


def load():
    assert SCRIPT.exists(), 'owner-local recovery implementation missing'
    spec = importlib.util.spec_from_file_location('owner_search_recovery', SCRIPT)
    m = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(m)
    return m


def digest(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


@pytest.fixture
def fixture(tmp_path):
    # Exact producer schema (including migration-added execution_context_json).
    import ast
    source = (SCRIPT.parents[2] / 'agents/tunnel/engine/router/orchestration.py').read_text()
    tree = ast.parse(source)
    schema = next(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and 'CREATE TABLE IF NOT EXISTS tasks (' in n.value)
    path = tmp_path / 'tasks.db'
    conn = sqlite3.connect(path)
    conn.execute(schema)
    conn.execute("ALTER TABLE tasks ADD COLUMN execution_context_json TEXT NOT NULL DEFAULT '{}'")
    authority = dict(principal_id='fixture-principal', workspace_id='fixture-workspace', device_id='fixture-device', installation_id='fixture-installation', owner_sid='S-1-fixture')
    authority['resource_id'] = 'files-fixture'
    ctx = dict(context_version=1, **{k:v for k,v in authority.items() if k not in {'owner_sid','resource_id'}},  request_id='req_fixture', trace_id='trc_fixture', task_id='tsk_fixture', operation_id='op_fixture', policy_revision='revision', required_scope='files:read', public_tool='files_search', effective_access='read', scopes=['files:read'], deadline=1, effective_resources=[dict(resource_id='files-fixture', kind='files', profile_id='agentRoot')])
    row = dict(task_id='tsk_fixture', session_id='owner_v1_'+digest([authority['principal_id'], authority['workspace_id']]), request_id=ctx['request_id'], trace_id=ctx['trace_id'], service_id='zagent_files', tool_name='files_search', arguments_json=json.dumps(dict(max_results=100, path='phyton_zagent_multiplatform', profile_id='agentRoot', query='allowedExecutables')), resource_key='installation:fixture-installation', access_mode='write', priority=2, state='orphaned', progress=0.1, error='RECOVERY_REQUIRED', created_at=1, updated_at=2, started_at=1.5, execution_context_json=json.dumps(ctx), target_device_id=ctx['device_id'], executed_on=ctx['device_id'])
    conn.execute('INSERT INTO tasks ('+','.join(row)+') VALUES ('+','.join('?' for _ in row)+')',tuple(row.values()))
    conn.commit(); conn.close()
    return path, authority


def rows(path):
    with sqlite3.connect(path) as c:
        c.row_factory = sqlite3.Row
        return [dict(r) for r in c.execute('SELECT * FROM tasks ORDER BY task_id')]


def test_plan_no_writes_and_apply_preserves_evidence(fixture):
    m = load(); path, authority = fixture
    before = path.read_bytes(); original = rows(path)[0]
    guard = lambda: authority
    plan = m.recover(path, 'tsk_fixture', guard=guard)
    assert plan['state'] == 'plan_only'
    assert path.read_bytes() == before
    assert list(path.parent.iterdir()) == [path]
    result = m.recover(path, 'tsk_fixture', guard=guard, apply=True, expected_plan=plan['plan_sha256'])
    assert result['state'] == 'failed'
    after = rows(path)[0]
    for key in set(original) - {'state','updated_at','finished_at','recovered_at'}:
        assert after[key] == original[key], key
    assert after['state'] == 'failed' and after['recovered_at']
    with sqlite3.connect(path) as c:
        audit = c.execute('SELECT before_json, after_json, owner_sid FROM owner_search_recovery_audit').fetchone()
        assert json.loads(audit[0]) == original
        assert json.loads(audit[1]) == after
        assert audit[2] == authority['owner_sid']
        # This is the scheduler's existing quarantine predicate, not a replacement.
        assert not c.execute("SELECT 1 FROM tasks WHERE resource_key=? AND state='orphaned' AND started_at IS NOT NULL", (original['resource_key'],)).fetchone()

def test_orphan_with_existing_finish_time_is_recoverable(fixture):
    m = load(); path, authority = fixture
    with sqlite3.connect(path) as c:
        c.execute('UPDATE tasks SET finished_at=3')
    original = rows(path)[0]
    plan = m.recover(path, 'tsk_fixture', guard=lambda: authority)
    m.recover(path, 'tsk_fixture', guard=lambda: authority, apply=True,
              expected_plan=plan['plan_sha256'])
    after = rows(path)[0]
    assert after['state'] == 'failed'
    assert after['finished_at'] == original['finished_at']
    with sqlite3.connect(path) as c:
        audit = c.execute('SELECT before_json FROM owner_search_recovery_audit').fetchone()
        assert json.loads(audit[0]) == original


@pytest.mark.parametrize('field,value', [
    ('state','running'), ('state','queued'), ('tool_name','files_write'),
    ('service_id','unknown'), ('session_id','owner_v1_other'),
    ('resource_key','installation:other'), ('target_device_id','other'),
    ('access_mode','read'), ('result_json','{}'), ('finished_at',-1),
    ('recovered_at',3), ('started_at',None),
    ('arguments_json','{"path":"x"}'), ('execution_context_json','[]'),
])
def test_rejects_unproven_task(fixture, field, value):
    m=load(); path, authority=fixture
    with sqlite3.connect(path) as c:
        c.execute('UPDATE tasks SET '+field+'=?', (value,))
    before=path.read_bytes()
    with pytest.raises(m.RecoveryDenied):
        m.recover(path,'tsk_fixture',guard=lambda:authority)
    assert path.read_bytes()==before


@pytest.mark.parametrize('field,value', [
    ('effective_access','write'), ('public_tool','files_exec_command'),
    ('principal_id','other'), ('workspace_id','other'), ('installation_id','other'),
    ('device_id','other'), ('effective_resources',[]), ('scopes',[]),
    ('required_scope','files:write'), ('context_version',True),
])
def test_rejects_unproven_context(fixture, field, value):
    m=load(); path, authority=fixture
    with sqlite3.connect(path) as c:
        ctx=json.loads(c.execute('SELECT execution_context_json FROM tasks').fetchone()[0])
        ctx[field]=value
        c.execute('UPDATE tasks SET execution_context_json=?',(json.dumps(ctx),))
    with pytest.raises(m.RecoveryDenied):
        m.recover(path,'tsk_fixture',guard=lambda:authority)


def test_active_other_owner_blocks_and_other_orphan_remains_quarantined(fixture):
    m=load(); path, authority=fixture
    with sqlite3.connect(path) as c:
        c.execute("INSERT INTO tasks SELECT 'other',session_id,request_id,trace_id,idempotency_key,profile_id,target_device_id,executed_on,operator_alias,binding_revision,binding_source,service_id,'files_write',arguments_json,resource_key,access_mode,priority,'running',progress,result_json,error,created_at,updated_at,started_at,finished_at,heartbeat_at,retry_count,queued_at,recovered_at,execution_context_json FROM tasks")
    with pytest.raises(m.RecoveryDenied,match='ACTIVE_TASKS'):
        m.recover(path,'tsk_fixture',guard=lambda:authority)
    with sqlite3.connect(path) as c: c.execute("UPDATE tasks SET state='orphaned' WHERE task_id='other'")
    other=rows(path)[0]
    plan=m.recover(path,'tsk_fixture',guard=lambda:authority)
    result=m.recover(path,'tsk_fixture',guard=lambda:authority,apply=True,expected_plan=plan['plan_sha256'])
    assert result['remaining_quarantine_tasks']==1
    assert rows(path)[0]==other


def test_raced_plan_and_repeat_denied(fixture):
    m=load(); path, authority=fixture
    plan=m.recover(path,'tsk_fixture',guard=lambda:authority)
    with sqlite3.connect(path) as c: c.execute('UPDATE tasks SET updated_at=123')
    with pytest.raises(m.RecoveryDenied,match='PLAN_CHANGED'):
        m.recover(path,'tsk_fixture',guard=lambda:authority,apply=True,expected_plan=plan['plan_sha256'])
    plan=m.recover(path,'tsk_fixture',guard=lambda:authority)
    m.recover(path,'tsk_fixture',guard=lambda:authority,apply=True,expected_plan=plan['plan_sha256'])
    with pytest.raises(m.RecoveryDenied):
        m.recover(path,'tsk_fixture',guard=lambda:authority,apply=True,expected_plan=plan['plan_sha256'])
    with sqlite3.connect(path) as c:
        assert c.execute('SELECT COUNT(*) FROM owner_search_recovery_audit').fetchone()[0]==1


def test_guard_failure_after_update_rolls_back_task_and_audit(fixture):
    m=load(); path, authority=fixture
    plan=m.recover(path,'tsk_fixture',guard=lambda:authority)
    before=rows(path)
    calls=[]
    def guard():
        calls.append(1)
        if len(calls)==3: raise m.RecoveryDenied('STOPPED_PRODUCERS')
        return authority
    with pytest.raises(m.RecoveryDenied,match='STOPPED_PRODUCERS'):
        m.recover(path,'tsk_fixture',guard=guard,apply=True,expected_plan=plan['plan_sha256'])
    assert rows(path)==before
    with sqlite3.connect(path) as c:
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='owner_search_recovery_audit'").fetchone()


def test_exclusive_transaction_blocks_competing_writer(fixture):
    m=load(); path, authority=fixture
    plan=m.recover(path,'tsk_fixture',guard=lambda:authority)
    calls=[]
    def guard():
        calls.append(1)
        if len(calls)==2:
            with sqlite3.connect(path,timeout=0) as c:
                with pytest.raises(sqlite3.OperationalError,match='locked'):
                    c.execute("UPDATE tasks SET state='running'")
        return authority
    m.recover(path,'tsk_fixture',guard=guard,apply=True,expected_plan=plan['plan_sha256'])


def test_native_entrypoint_fails_closed_off_windows(fixture):
    m=load(); path, authority=fixture
    import os
    if os.name=='nt': pytest.skip('Linux denial test')
    with pytest.raises(m.RecoveryDenied,match='OWNER_CONSOLE'):
        m.windows_guard(path.parent,path.parent,'fixture-principal',Path('/not-used'))


@pytest.mark.parametrize('change', ['resource','unknown_context','missing_plan','trigger','wal','authority'])
def test_additional_closed_guards(fixture,change):
    m=load(); path,authority=fixture
    if change=='resource':
        authority['resource_id']='different-resource'
    if change=='unknown_context':
        with sqlite3.connect(path) as c:
            ctx=json.loads(c.execute('SELECT execution_context_json FROM tasks').fetchone()[0]);ctx['unknown_authority']='x'
            c.execute('UPDATE tasks SET execution_context_json=?',(json.dumps(ctx),))
    if change=='wal':
        Path(str(path)+'-wal').write_bytes(b'uncertain-wal')
    if change in {'resource','unknown_context','wal'}:
        with pytest.raises(m.RecoveryDenied): m.recover(path,'tsk_fixture',guard=lambda:authority)
        return
    if change=='trigger':
        with sqlite3.connect(path) as c: c.execute('CREATE TRIGGER unexpected AFTER UPDATE ON tasks BEGIN DELETE FROM tasks; END')
    plan=m.recover(path,'tsk_fixture',guard=lambda:authority)
    before=rows(path)
    calls=[]
    def guard():
        calls.append(1)
        if change=='authority' and len(calls)>1: return dict(authority,owner_sid='other')
        return authority
    with pytest.raises(m.RecoveryDenied):
        m.recover(path,'tsk_fixture',guard=guard,apply=True,expected_plan=None if change=='missing_plan' else plan['plan_sha256'])
    assert rows(path)==before


def test_hot_rollback_journal_is_not_ignored(fixture):
    m=load(); path,authority=fixture
    Path(str(path)+'-journal').write_bytes(b'unknown-rollback-evidence')
    before=path.read_bytes()
    with pytest.raises(m.RecoveryDenied): m.recover(path,'tsk_fixture',guard=lambda:authority)
    assert path.read_bytes()==before
