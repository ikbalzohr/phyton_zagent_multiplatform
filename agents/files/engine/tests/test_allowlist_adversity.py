"""Synthetic Windows transactions, never installed policy or enrollment."""
import copy
import pytest
from test_allowlist_engine import env, sync, prepare_add, receipts, sign
from app.allowlist import protocol as p


def test_broker_ciphertext_digest_is_not_preimage_digest(env):
    e=env
    prepared=prepare_add(e)
    approval, backup=receipts(e,prepared)
    # Actual VPS BackupStore signs the at-rest ciphertext digest. The raw
    # preimage SHA256 is already authenticated separately by expected_revision.
    backup=sign(e['ed'],p.BACKUP,dict(backup['body'],backup_digest='f'*64))
    assert sync(e['engine'].commit(e['context'],prepared.challenge['operation_id'],approval,backup))['status']=='applied'

def test_internal_service_closed_arguments_and_matching_real_session(env):
    from app.allowlist.service import AllowlistService
    e=env
    service=AllowlistService(e['engine'])
    payload=dict(action='add',target_profile_id='fixture',executable=e['paths'][2])
    args=dict(payload=payload,session_id=e['fields']['session_id'])
    challenge=sync(service.dispatch('prepare',args,e['metadata']))
    assert set(challenge)==set(p.METADATA)|{'profile_generation','session_id','action','nonce','iat','exp','placement_risk'}
    sealed=sync(service.dispatch('backup',{'operation_id':challenge['operation_id']},e['metadata']))
    assert sealed['metadata']['operation_id']==challenge['operation_id']
    for bad in (dict(args,approved=True),dict(args,session_id='foreign-session')):
        with pytest.raises((ValueError,PermissionError)):
            sync(service.dispatch('prepare',bad,e['metadata']))
    with pytest.raises(PermissionError): sync(service.dispatch('prepare',args,dict(e['metadata'])))

@pytest.mark.parametrize('action',['remove','replace'])
def test_stale_old_executable_can_be_repaired(env, action):
    e=env
    from pathlib import Path
    Path(e['paths'][0]).unlink()
    payload=dict(action=action,target_profile_id='fixture')
    if action=='remove': payload['executable']=e['paths'][0]
    else: payload.update(old_executable=e['paths'][0],new_executable=e['paths'][2])
    prepared=sync(e['engine'].prepare(e['context'],payload))
    result=sync(e['engine'].commit(e['context'],prepared.challenge['operation_id'],*receipts(e,prepared)))
    assert result['status']=='applied'
    exes=p.loads(e['policy_path'].read_bytes())['allowed_executables']
    assert exes==([e['paths'][1]] if action=='remove' else [e['paths'][2],e['paths'][1]])


def test_reject_last_remove_and_casefold_duplicate(env):
    e=env
    doc=copy.deepcopy(e['policy']); doc['allowed_executables']=e['paths'][:1]
    e['policy_path'].write_bytes(p.canonical(doc))
    for payload in (dict(action='remove',target_profile_id='fixture',executable=e['paths'][0]),
                    dict(action='add',target_profile_id='fixture',executable=e['paths'][0].upper())):
        with pytest.raises(ValueError): sync(e['engine'].prepare(e['context'],payload))
    assert p.loads(e['policy_path'].read_bytes())==doc


def test_idempotency_exact_request_and_changed_key_reuse(env):
    e=env
    first=prepare_add(e,'stable')
    again=prepare_add(e,'stable')
    assert again.challenge==first.challenge
    changed=dict(action='remove',target_profile_id='fixture',executable=e['paths'][0])
    with pytest.raises(ValueError,match='IDEMPOTENCY_CONFLICT'):
        sync(e['engine'].prepare(e['context'],changed,p.sha(e['policy_path'].read_bytes()),'stable'))
    result=sync(e['engine'].commit(e['context'],first.challenge['operation_id'],*receipts(e,first)))
    replay=sync(e['engine'].prepare(e['context'],first.payload,first.challenge['expected_revision'],'stable'))
    assert replay.outcome==result


def test_two_preparations_cas_and_cross_operation_receipt_replay(env):
    e=env
    first=prepare_add(e,'first')
    second=sync(e['engine'].prepare(e['context'],dict(action='remove',target_profile_id='fixture',executable=e['paths'][0])))
    with pytest.raises(PermissionError):
        sync(e['engine'].commit(e['context'],second.challenge['operation_id'],*receipts(e,first)))
    assert sync(e['engine'].commit(e['context'],first.challenge['operation_id'],*receipts(e,first)))['status']=='applied'
    assert sync(e['engine'].commit(e['context'],second.challenge['operation_id'],*receipts(e,second)))['status']=='conflict'


@pytest.mark.parametrize('field',['actor_user_id','chat_id','thread_id','device_id','session_id','nonce','profile_generation','expected_revision','payload_sha256'])
def test_signed_wrong_binding_never_publishes(env,field):
    e=env
    prepared=prepare_add(e)
    approval,backup=receipts(e,prepared)
    approval=sign(e['ed'],p.APPROVAL,dict(approval['body'],**{field:'foreign'}))
    before=e['policy_path'].read_bytes()
    with pytest.raises((ValueError,PermissionError)):
        sync(e['engine'].commit(e['context'],prepared.challenge['operation_id'],approval,backup))
    assert e['policy_path'].read_bytes()==before


@pytest.mark.parametrize('change',['revoked','profile','executable','expired'])
def test_revalidation_after_backup_round_trip(env,change):
    e=env
    prepared=prepare_add(e)
    approval,backup=receipts(e,prepared)
    before=e['policy_path'].read_bytes()
    if change=='revoked': e['fresh']['valid']=False
    elif change=='profile':
        doc=p.loads(e['profiles_path'].read_bytes())
        doc['profiles'][0]['enabled']=False
        e['profiles_path'].write_bytes(p.canonical(doc))
    elif change=='executable':
        from pathlib import Path
        Path(e['paths'][2]).unlink()
    else: e['engine'].clock=lambda:prepared.challenge['exp']
    if change=='expired':
        assert sync(e['engine'].commit(e['context'],prepared.challenge['operation_id'],approval,backup))['status']=='expired'
    else:
        with pytest.raises((ValueError,PermissionError)):
            sync(e['engine'].commit(e['context'],prepared.challenge['operation_id'],approval,backup))
    assert e['policy_path'].read_bytes()==before


def test_revalidation_after_waiting_for_profile_lease(env):
    import asyncio
    from app.profiles.administration import CatalogLeases
    e=env
    prepared=prepare_add(e)
    leases=CatalogLeases()
    e['engine']._lease_factory=lambda write:leases.write() if write else leases.read()
    async def scenario():
        async with leases.read():
            task=asyncio.create_task(e['engine'].commit(e['context'],prepared.challenge['operation_id'],*receipts(e,prepared)))
            while leases.waiting==0: await asyncio.sleep(0)
            e['fresh']['valid']=False
        with pytest.raises(PermissionError): await task
    sync(scenario())
    assert p.sha(e['policy_path'].read_bytes())==prepared.challenge['expected_revision']


@pytest.mark.parametrize('after_replace',[True,False])
def test_interrupted_publication_reconciles_exact_bytes(env,monkeypatch,after_replace):
    from app.allowlist import engine as module
    from app.allowlist.engine import AllowlistEngine
    e=env
    prepared=prepare_add(e)
    original=module._atomic
    def interrupted(path,raw):
        if path==e['policy_path']:
            if after_replace: original(path,raw)
            raise OSError('synthetic interrupted publication')
        original(path,raw)
    monkeypatch.setattr(module,'_atomic',interrupted)
    with pytest.raises(OSError):
        sync(e['engine'].commit(e['context'],prepared.challenge['operation_id'],*receipts(e,prepared)))
    restarted=AllowlistEngine(e['policy_path'],e['profiles_path'],e['tmp']/'journal',enrollment=e['enrollment'])
    result=sync(restarted.operation(e['context'],prepared.challenge['operation_id']))
    assert result['status']==('applied' if after_replace else 'failed')
    assert sync(restarted.operation(e['context'],prepared.challenge['operation_id']))==result
    assert not list(e['policy_path'].parent.glob('*.candidate-*'))


def test_windows_interprocess_writer_lock(env):
    import subprocess,sys
    e=env
    script="import sys,msvcrt;f=open(sys.argv[1]+'.allowlist.lock','a+b');f.write(b'0');f.flush();f.seek(0);msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1);print('locked',flush=True);sys.stdin.readline()"
    child=subprocess.Popen([sys.executable,'-c',script,str(e['policy_path'])],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    try:
        assert child.stdout.readline().strip()=='locked'
        with pytest.raises(BlockingIOError): prepare_add(e)
    finally:
        stdout,stderr=child.communicate('release',timeout=10)
    assert child.returncode==0,stderr
    assert prepare_add(e).challenge['operation_id']


@pytest.mark.parametrize('version',[1,2])
def test_real_consumer_authorization_and_sibling_preservation(env,monkeypatch,version):
    from app.mcp import managed_commands as consumer
    from app.core.execution_context import VerifiedContext
    e=env
    original=copy.deepcopy(e['policy'])
    sibling=dict(copy.deepcopy(original),profile_id='untouched',enabled=False)
    doc=original if version==1 else dict(version=2,profiles={'fixture':original,'untouched':sibling})
    e['policy_path'].write_bytes(p.canonical(doc))
    prepared=prepare_add(e)
    result=sync(e['engine'].commit(e['context'],prepared.challenge['operation_id'],*receipts(e,prepared)))
    assert result['status']=='applied'
    actual=p.loads(e['policy_path'].read_bytes())
    target=actual if version==1 else actual['profiles']['fixture']
    assert {k:v for k,v in target.items() if k!='allowed_executables'}=={k:v for k,v in original.items() if k!='allowed_executables'}
    if version==2: assert actual['profiles']['untouched']==sibling
    monkeypatch.setattr(consumer,'POLICY_FILE',e['policy_path'])
    monkeypatch.setattr(consumer,'PROFILES_FILE',e['profiles_path'])
    import time
    authority=VerifiedContext(dict(public_tool='files_exec_command',scopes=['files:execute','files:write'],effective_access='write',required_scope='files:execute',expires_at=time.time()+100,
        principal_id='fixture',workspace_id='fixture',profile_id='fixture',effective_resources=[dict(kind='files',profile_id='fixture',resource_id='fixture',profile_generation=e['fields']['profile_generation'])]))
    grant=consumer.authorize_command_call('files_exec_command',{},authority)
    assert [str(v) for v in grant.executables]==e['paths']
    assert str(consumer.resolve_executable(e['paths'][2],grant))==e['paths'][2]

def test_uncertain_journal_blocks_new_mutation(env):
    e=env
    prepared=prepare_add(e)
    path=e['tmp']/'journal'/(prepared.challenge['operation_id']+'.json')
    record=p.loads(path.read_bytes()); record['state']='committing'
    path.write_bytes(p.canonical(record))
    e['policy_path'].write_bytes(e['policy_path'].read_bytes()+b' ')
    assert sync(e['engine'].operation(e['context'],prepared.challenge['operation_id']))['status']=='uncertain'
    with pytest.raises(PermissionError,match='UNRESOLVED_POLICY_PUBLICATION'):
        prepare_add(e,'new-key')

def test_unknown_journal_field_rejected_without_publication(env):
    e=env
    prepared=prepare_add(e)
    path=e['tmp']/'journal'/(prepared.challenge['operation_id']+'.json')
    record=p.loads(path.read_bytes());record['injected']='not-part-of-schema'
    path.write_bytes(p.canonical(record))
    with pytest.raises(ValueError,match='INVALID_OPERATION_JOURNAL'):
        sync(e['engine'].operation(e['context'],prepared.challenge['operation_id']))
    assert p.sha(e['policy_path'].read_bytes())==prepared.challenge['expected_revision']

def test_unicode_casefold_duplicate_denied(env):
    e=env
    doc=copy.deepcopy(e['policy'])
    old=str(e['tmp']/'Straße.exe')
    new=str(e['tmp']/'STRASSE.exe')
    doc['allowed_executables']=[old]
    e['policy_path'].write_bytes(p.canonical(doc))
    e['engine'].path_validator=lambda literal:literal
    with pytest.raises(ValueError,match='DUPLICATE_EXECUTABLE'):
        sync(e['engine'].prepare(e['context'],dict(action='add',target_profile_id='fixture',executable=new)))

@pytest.mark.parametrize('literal',[
    'python.exe', r'C:python.exe', r'\\server\share\file.exe',
    r'\\?\C:\file.exe', r'\\.\C:\file.exe', r'C:\file.exe:stream',
    r'%LOCALAPPDATA%\file.exe', r'C:\folder\..\file.exe',
    r'C:\folder.\file.exe', r'C:\folder \file.exe',
    'C:/folder/file.exe', r'C:\folder\*.exe', r'C:\folder\missing.exe',
])
def test_exact_windows_path_validation_rejects_unsafe_literals(literal):
    from app.allowlist.engine import validate_executable
    with pytest.raises((ValueError,PermissionError)):
        validate_executable(literal)


@pytest.mark.parametrize('extra',['owner_management','capability','revision'])
def test_policy_schema_cannot_gain_authority_metadata(env,extra):
    e=env
    doc=copy.deepcopy(e['policy']);doc[extra]={}
    e['policy_path'].write_bytes(p.canonical(doc))
    with pytest.raises(PermissionError): sync(e['engine'].list(e['context']))


@pytest.mark.parametrize('mutation',['timeout','tools','duplicate','empty'])
def test_invalid_consumer_policy_denied_before_backup(env,mutation):
    e=env
    doc=copy.deepcopy(e['policy'])
    if mutation=='timeout':doc['max_timeout_seconds']=True
    elif mutation=='tools':doc['allowed_tools']=['not_a_command_tool']
    elif mutation=='duplicate':doc['allowed_executables']=[e['paths'][0],e['paths'][0].upper()]
    else:doc['allowed_executables']=[]
    raw=p.canonical(doc);e['policy_path'].write_bytes(raw)
    with pytest.raises((ValueError,PermissionError)):prepare_add(e)
    assert not (e['tmp']/'journal').exists()
    assert e['policy_path'].read_bytes()==raw


def test_internal_service_full_signed_wire_flow_and_status_owner(env):
    from app.allowlist.service import AllowlistService
    from app.allowlist.engine import Prepared
    from app.allowlist import authority as a
    from app.core.execution_context import TrustedMetadata
    e=env
    service=AllowlistService(e['engine'])
    payload=dict(action='add',target_profile_id='fixture',executable=e['paths'][2])
    c=sync(service.dispatch('prepare',dict(payload=payload,session_id=e['fields']['session_id']),e['metadata']))
    signed=receipts(e,Prepared(c,None,payload))
    # Backup timeout/unavailable/unsigned means no publish, not a queued success.
    with pytest.raises(ValueError):
        sync(service.dispatch('commit',dict(operation_id=c['operation_id'],approval=signed[0],backup_receipt={}),e['metadata']))
    assert sync(service.dispatch('operation',{'operation_id':c['operation_id']},e['metadata']))['status']=='pending'
    result=sync(service.dispatch('commit',dict(operation_id=c['operation_id'],approval=signed[0],backup_receipt=signed[1]),e['metadata']))
    assert sync(service.dispatch('operation',{'operation_id':c['operation_id']},e['metadata']))==result
    assert result['status']=='applied'
    foreign=TrustedMetadata({a.META:dict(e['fields'],session_id='different-real-session')})
    with pytest.raises(PermissionError):
        sync(service.dispatch('operation',{'operation_id':c['operation_id']},foreign))


def test_no_laptop_preimage_file_or_sensitive_receipt_journal(env):
    e=env
    before=e['policy_path'].read_bytes()
    prepared=prepare_add(e)
    signed=receipts(e,prepared)
    sync(e['engine'].commit(e['context'],prepared.challenge['operation_id'],*signed))
    for path in e['tmp'].rglob('*'):
        if not path.is_file():continue
        assert before not in path.read_bytes()
        if path.parent.name=='journal':
            raw=path.read_bytes()
            assert b'allowed_executables' not in raw
            assert b'signature' not in raw
            assert b'actor_user_id' not in raw


def test_real_windows_junction_ancestor_is_rejected(env):
    """Create disposable NTFS junction with Win32 API, not a shell/executable."""
    import ctypes,struct
    from ctypes import wintypes as w
    from pathlib import Path
    from app.allowlist.engine import validate_executable
    e=env
    outside=e['tmp']/'outside';outside.mkdir()
    (outside/'new.exe').write_bytes(b'not executed')
    junction=e['tmp']/'junction';junction.mkdir()
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
    kernel.CreateFileW.restype=w.HANDLE
    kernel.DeviceIoControl.argtypes=[w.HANDLE,w.DWORD,ctypes.c_void_p,w.DWORD,ctypes.c_void_p,w.DWORD,ctypes.POINTER(w.DWORD),ctypes.c_void_p]
    kernel.DeviceIoControl.restype=w.BOOL
    kernel.CloseHandle.argtypes=[w.HANDLE]
    handle=kernel.CreateFileW(str(junction),0x40000000,7,None,3,0x02200000,None)
    assert handle!=w.HANDLE(-1).value,ctypes.get_last_error()
    # NT namespace prefix has exactly one leading and one trailing backslash.
    substitute=(chr(92)+'??'+chr(92)+str(outside)).encode('utf-16-le')
    display=str(outside).encode('utf-16-le')
    names=substitute+bytes(2)+display+bytes(2)
    data=struct.pack('<IHHHHHH',0xA0000003,len(names)+8,0,0,len(substitute),len(substitute)+2,len(display))+names
    buffer=ctypes.create_string_buffer(data)
    returned=w.DWORD()
    try:
        assert kernel.DeviceIoControl(handle,0x000900A4,buffer,len(data),None,0,ctypes.byref(returned),None),ctypes.get_last_error()
    finally:kernel.CloseHandle(handle)
    try:
        assert (junction/'new.exe').is_file()
        with pytest.raises(PermissionError,match='REPARSE_ADMIN_PATH'):
            validate_executable(str(junction/'new.exe'))
    finally:junction.rmdir()

def test_emitted_policy_allows_one_harmless_real_windows_command(env,monkeypatch):
    import sys,time
    from app.mcp import managed_commands as consumer
    from app.core.execution_context import VerifiedContext,CURRENT
    e=env
    payload=dict(action='add',target_profile_id='fixture',executable=sys.executable)
    prepared=sync(e['engine'].prepare(e['context'],payload))
    assert sync(e['engine'].commit(e['context'],prepared.challenge['operation_id'],*receipts(e,prepared)))['status']=='applied'
    monkeypatch.setattr(consumer,'POLICY_FILE',e['policy_path'])
    monkeypatch.setattr(consumer,'PROFILES_FILE',e['profiles_path'])
    monkeypatch.setattr(consumer,'AUDIT_LOG',e['tmp']/'audit.jsonl')
    authority=VerifiedContext(dict(public_tool='files_exec_command',scopes=['files:execute','files:write'],effective_access='write',required_scope='files:execute',expires_at=time.time()+100,
        principal_id='fixture',workspace_id='fixture',profile_id='fixture',effective_resources=[dict(kind='files',profile_id='fixture',resource_id='fixture',profile_generation=e['fields']['profile_generation'])]))
    token=CURRENT.set(authority)
    try:
        result=sync(consumer.execute('files_exec_command',dict(executable=sys.executable,args=['-c',"print('allowlist-disposable-smoke')"])))
    finally:CURRENT.reset(token)
    assert result['ok'] and result['exit_code']==0
    assert result['stdout'].strip()=='allowlist-disposable-smoke'
    assert not consumer._RECORDS
