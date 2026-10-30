"""Disposable Windows owner-loader and private HTTP fixtures; no installed paths."""
import asyncio
import copy
import os
import time
from dataclasses import replace
import pytest
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from test_allowlist_engine import env, receipts
from app.allowlist import protocol as p, authority as a


def test_adapter_is_inert_and_has_explicit_owner_loader():
    import importlib.util
    assert importlib.util.find_spec('app.allowlist.owner_loader') is not None
    assert importlib.util.find_spec('app.allowlist.adapter') is not None


def protect(path, *, public_sid=None, public_mask=0):
    import win32security as s
    from app.allowlist.owner_loader import process_sid, SYSTEM, ADMINS
    acl=s.ACL()
    flags=3 if path.is_dir() else 0
    for sid in (process_sid(),SYSTEM,ADMINS):
        acl.AddAccessAllowedAceEx(s.ACL_REVISION,flags,0x1f01ff,s.ConvertStringSidToSid(sid))
    if public_sid:
        acl.AddAccessAllowedAceEx(s.ACL_REVISION,flags,public_mask,s.ConvertStringSidToSid(public_sid))
    s.SetNamedSecurityInfo(str(path),s.SE_FILE_OBJECT,
        s.DACL_SECURITY_INFORMATION|s.PROTECTED_DACL_SECURITY_INFORMATION,None,None,acl,None)


@pytest.fixture
def tmp_path():
    # This machine's general Temp grants an additional untrusted SID modify.
    # Do NOT relax the loader or edit that ACL. Use an isolated temporary child
    # of Local, whose existing ancestor ACLs pass the real native checks.
    import tempfile
    from pathlib import Path
    from win32com.shell import shell,shellcon
    local=shell.SHGetFolderPath(0,shellcon.CSIDL_LOCAL_APPDATA,0,0)
    with tempfile.TemporaryDirectory(prefix='Zagent-Allowlist-Fixture-',dir=local) as folder:
        root=Path(folder);protect(root)
        yield root


@pytest.fixture
def owner_env(env):
    from app.allowlist.owner_loader import OwnerConfiguration,load_owner,process_sid
    from app.allowlist.adapter import make_private_app
    e=env
    root=e['tmp']/'private';root.mkdir();protect(root)
    config=root/'config';config.mkdir();protect(config)
    policy=config/'policy.json';policy.write_bytes(e['policy_path'].read_bytes())
    profiles=config/'profiles.json';profiles.write_bytes(e['profiles_path'].read_bytes())
    journal=root/'journal';journal.mkdir()
    replay=root/'replay';replay.mkdir()
    request_key=Ed25519PrivateKey.generate()
    raws=[key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
          for key in (e['ed'],e['x'],request_key)]
    keypaths=[]
    for name,raw in zip(('approval','backup','request'),raws):
        path=config/(name+'.pub');path.write_bytes(raw);keypaths.append(path)
    source=config/'enrollment.json'
    doc=dict(version=1,capability=a.CAPABILITY,placement=dict(e['enrollment'].placement),
             actions=sorted(e['enrollment'].actions),key_id='test-key',request_key_id='transport-key',
             capability_revision='cap-1',expires_at=int(time.time())+3600,revoked=False)
    source.write_bytes(p.canonical(doc))
    for v in (config,policy,profiles,journal,replay,source,*keypaths):protect(v)
    c=OwnerConfiguration(root,source,policy,profiles,journal,replay,*keypaths,
        process_sid(),process_sid(),dict(e['enrollment'].placement),e['enrollment'].actions,
        'test-key','transport-key','cap-1',*[p.sha(raw) for raw in raws])
    runtime={k:e['fields'][k] for k in ('session_id','profile_generation','actor_user_id','chat_id','thread_id')}
    state={'valid':True}
    callbacks=dict(oauth_current=lambda _:state['valid'],resolve_runtime=lambda _:dict(runtime))
    from app.allowlist.owner_loader import LoadedOwner
    owner=LoadedOwner(c,**callbacks)
    return dict(e=e,config=c,owner=owner,app=make_private_app(owner),request_key=request_key,
                doc=doc,runtime=runtime,state=state,callbacks=callbacks)


def request(o,method='list',arguments=None,**overrides):
    from app.allowlist.adapter import KIND,AUDIENCE
    args={} if arguments is None else arguments
    now=int(time.time())
    fields=dict(o['e']['fields'],deadline=now+50)
    body=dict(method=method,arguments_sha256=p.sha(p.canonical(args)),context=fields,
              nonce=p.b64(os.urandom(32)),iat=now,exp=now+60,audience=AUDIENCE)
    body.update(overrides)
    unsigned=dict(version=1,kind=KIND,key_id='transport-key',body=body)
    return dict(unsigned,arguments=args,signature=p.b64(o['request_key'].sign(p.canonical(unsigned))))


def resign(o,r):
    signed={k:r[k] for k in ('version','kind','key_id','body')}
    r['signature']=p.b64(o['request_key'].sign(p.canonical(signed)))
    return r


async def post(o,r,headers=None):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=o['app']),base_url='https://private') as client:
        return await client.post('/',content=p.canonical(r),headers=headers)


def test_real_windows_acl_loader_and_authenticated_http_list(owner_env):
    o=owner_env
    r=asyncio.run(post(o,request(o)))
    assert r.status_code==200,r.text
    assert r.json()['allowed_executables']==o['e']['paths'][:2]
    assert r.headers['cache-control']=='no-store'
    from app.allowlist.owner_loader import load_owner
    assert load_owner(o['config'],**o['callbacks']).current_fields(request(o)['body']['context']) is True
    with pytest.raises(PermissionError,match='^OWNER_LOADER_DENIED$'):load_owner(o['config'])


@pytest.mark.parametrize('spoof',['_meta','internal-token','execution-context','fake-approved'])
def test_ordinary_authority_never_authenticates_http(owner_env,spoof):
    o=owner_env
    bodies={'_meta':{a.META:o['e']['fields']},'internal-token':{},
            'execution-context':{'zagent.execution_context':o['e']['fields']},
            'fake-approved':{'approved':True,'method':'list','arguments':{}}}
    r=asyncio.run(post(o,bodies[spoof],{'x-zagent-internal-token':'ordinary-fixture-token'}))
    assert r.status_code==403
    assert r.content==b'{"error":"ALLOWLIST_REQUEST_DENIED"}'
    assert list(o['config'].replay_dir.iterdir())==[]


@pytest.mark.parametrize('fault',['signature','method','args','placement','session','actor','chat','topic',
    'generation','revision','expired','future','audience','key-id','extra-field','session-argument'])
def test_signed_request_exact_binding_denials(owner_env,fault):
    o=owner_env;r=request(o)
    if fault=='signature':r['signature']=p.b64(os.urandom(64))
    elif fault=='method':r['body']['method']='operation'  # do NOT re-sign; method is bound.
    elif fault=='args':r['arguments']={'operation_id':'0'*32}
    elif fault in ('placement','session','actor','chat','topic','generation','revision'):
        field={'placement':'device_id','session':'session_id','actor':'actor_user_id','chat':'chat_id',
               'topic':'thread_id','generation':'profile_generation','revision':'capability_revision'}[fault]
        r['body']['context'][field]='wrong';resign(o,r)
    elif fault=='expired':r=request(o,iat=int(time.time())-100,exp=int(time.time())-1)
    elif fault=='future':r=request(o,iat=int(time.time())+10,exp=int(time.time())+50)
    elif fault=='audience':r=request(o,audience='zagent.allowlist.admin')
    elif fault=='key-id':r['key_id']='untrusted-key';resign(o,r)
    elif fault=='extra-field':r['approved']=True
    elif fault=='session-argument':
        r=request(o,'prepare',dict(payload=dict(action='add',target_profile_id='fixture',
            executable=o['e']['paths'][2]),session_id='wrong'))
    result=asyncio.run(post(o,r))
    assert result.status_code==403
    assert result.content==b'{"error":"ALLOWLIST_REQUEST_DENIED"}'


@pytest.mark.parametrize('fault',['oauth','truthy-oauth','revoked','expired','placement','revision','actions',
                                 'key-id','request-key-id','version','source-path','key-pin','service-sid'])
def test_local_source_and_current_oauth_are_independent(owner_env,fault):
    o=owner_env;c=o['config']
    if fault=='oauth':o['state']['valid']=False
    elif fault=='truthy-oauth':o['state']['valid']='yes'
    elif fault=='key-pin':c.request_key_path.write_bytes(os.urandom(32))
    elif fault=='source-path':c.source_path.unlink()
    elif fault=='service-sid':
        from app.allowlist.owner_loader import load_owner
        with pytest.raises(PermissionError,match='^OWNER_LOADER_DENIED$'):
            load_owner(replace(c,service_sid='S-1-5-18'),**o['callbacks'])
        return
    else:
        doc=copy.deepcopy(o['doc'])
        if fault=='revoked':doc['revoked']=True
        elif fault=='expired':doc['expires_at']=int(time.time())-1
        elif fault=='placement':doc['placement']['device_id']='wrong'
        elif fault=='revision':doc['capability_revision']='changed'
        elif fault=='actions':doc['actions']=['list']
        elif fault=='key-id':doc['key_id']='changed'
        elif fault=='request-key-id':doc['request_key_id']='changed'
        elif fault=='version':doc['version']=2
        c.source_path.write_bytes(p.canonical(doc))
    result=asyncio.run(post(o,request(o)))
    assert result.status_code==403
    assert result.content==b'{"error":"ALLOWLIST_REQUEST_DENIED"}'


def test_replay_survives_reconstruction_and_parallel_admission(owner_env):
    from app.allowlist.adapter import make_private_app
    from app.allowlist.owner_loader import load_owner
    o=owner_env
    async def exercise():
        signed=request(o)
        results=await asyncio.gather(post(o,signed),post(o,signed))
        assert sorted(r.status_code for r in results)==[200,403]
        o['app']=make_private_app(load_owner(o['config'],**o['callbacks']))
        assert (await post(o,signed)).status_code==403
    asyncio.run(exercise())


def make_junction(alias,target):
    import ctypes,struct
    from ctypes import wintypes as w
    alias.mkdir()
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
    kernel.CreateFileW.restype=w.HANDLE
    kernel.DeviceIoControl.argtypes=[w.HANDLE,w.DWORD,ctypes.c_void_p,w.DWORD,ctypes.c_void_p,w.DWORD,ctypes.POINTER(w.DWORD),ctypes.c_void_p]
    kernel.DeviceIoControl.restype=w.BOOL
    kernel.CloseHandle.argtypes=[w.HANDLE]
    handle=kernel.CreateFileW(str(alias),0x40000000,7,None,3,0x02200000,None)
    assert handle!=w.HANDLE(-1).value
    substitute=(chr(92)+'??'+chr(92)+str(target)).encode('utf-16-le')
    display=str(target).encode('utf-16-le')
    names=substitute+bytes(2)+display+bytes(2)
    data=struct.pack('<IHHHHHH',0xA0000003,len(names)+8,0,0,len(substitute),len(substitute)+2,len(display))+names
    buf=ctypes.create_string_buffer(data);count=w.DWORD()
    try:assert kernel.DeviceIoControl(handle,0x000900A4,buf,len(data),None,0,ctypes.byref(count),None)
    finally:kernel.CloseHandle(handle)


@pytest.mark.parametrize('fault',['private-read','private-write','ancestor-write','null-dacl',
    'root-overlap','descendant-root','relative-source','journal-outside','key-alias','public-root-junction'])
def test_unsafe_private_selection_or_acl_denies(owner_env,fault):
    from app.allowlist.owner_loader import load_owner
    o=owner_env;c=o['config']
    if fault in ('private-read','private-write'):
        protect(c.policy_path,public_sid='S-1-1-0',public_mask=0x120089 if fault=='private-read' else 0x1f01ff)
    elif fault=='ancestor-write':protect(c.policy_path.parent,public_sid='S-1-1-0',public_mask=2)
    elif fault=='null-dacl':
        import win32security as s
        s.SetNamedSecurityInfo(str(c.policy_path),s.SE_FILE_OBJECT,s.DACL_SECURITY_INFORMATION,
                               None,None,None,None)
    elif fault in ('root-overlap','descendant-root'):
        doc=p.loads(c.profiles_path.read_bytes())
        doc['profiles'][0]['root']=str(c.data_root if fault=='root-overlap' else c.journal_dir)
        c.profiles_path.write_bytes(p.canonical(doc))
    elif fault=='relative-source':c=replace(c,source_path='config/enrollment.json')
    elif fault=='journal-outside':c=replace(c,journal_dir=o['e']['tmp'])
    elif fault=='key-alias':c=replace(c,request_key_path=c.approval_key_path)
    elif fault=='public-root-junction':
        alias=o['e']['tmp']/'public-alias'
        make_junction(alias,c.data_root)
        doc=p.loads(c.profiles_path.read_bytes());doc['profiles'][0]['root']=str(alias)
        c.profiles_path.write_bytes(p.canonical(doc))
    try:
        with pytest.raises(PermissionError,match='^OWNER_LOADER_DENIED$'):load_owner(c,**o['callbacks'])
    finally:
        if fault=='null-dacl':protect(c.policy_path)
        if fault=='public-root-junction':os.rmdir(alias)


async def prepared_http_operation(o):
    from types import SimpleNamespace
    payload=dict(action='add',target_profile_id='fixture',executable=o['e']['paths'][2])
    arguments=dict(payload=payload,session_id=o['e']['fields']['session_id'])
    response=await post(o,request(o,'prepare',arguments))
    assert response.status_code==200,response.text
    challenge=response.json()
    assert challenge['payload_sha256']==p.sha(p.canonical(payload))
    backup=await post(o,request(o,'backup',{'operation_id':challenge['operation_id']}))
    assert backup.status_code==200,backup.text
    assert backup.json()['metadata']['expected_revision']==challenge['expected_revision']
    # Synthetic ephemeral signer fixture: actual VPS durable crypto gate is
    # tested separately. This fixture tests the full HTTP dispatch/lease seam.
    approval,receipt=receipts(o['e'],SimpleNamespace(challenge=challenge,payload=payload))
    return challenge,dict(operation_id=challenge['operation_id'],approval=approval,backup_receipt=receipt)


def test_full_http_prepare_backup_commit_and_exact_status(owner_env,monkeypatch):
    from app.profiles import administration
    monkeypatch.setattr(administration,'LEASES',administration.CatalogLeases())
    o=owner_env;c=o['config']
    before=c.policy_path.read_bytes()
    async def scenario():
        challenge,args=await prepared_http_operation(o)
        assert c.policy_path.read_bytes()==before
        invalid=dict(args,approval=None,backup_receipt=None)
        denied=await post(o,request(o,'commit',invalid))
        assert denied.status_code==403
        assert c.policy_path.read_bytes()==before
        response=await asyncio.wait_for(post(o,request(o,'commit',args)),3)
        assert response.status_code==200,response.text
        outcome=response.json()
        assert outcome['status']=='applied'
        status=await post(o,request(o,'operation',{'operation_id':challenge['operation_id']}))
        assert status.status_code==200
        assert status.json()==outcome
        assert outcome['revision']==p.sha(c.policy_path.read_bytes())
        assert p.loads(c.policy_path.read_bytes())['allowed_executables']==o['e']['paths']
        assert administration.LEASES.readers==0
        assert administration.LEASES.waiting==0
        assert administration.LEASES.writer is False
    asyncio.run(scenario())


@pytest.mark.parametrize('interruption',['release','revoke','cancel'])
def test_actual_http_commit_shares_command_lease_without_self_deadlock(owner_env,monkeypatch,interruption):
    from app.profiles import administration
    leases=administration.CatalogLeases()
    monkeypatch.setattr(administration,'LEASES',leases)
    o=owner_env;before=o['config'].policy_path.read_bytes()
    async def waiting():
        while leases.waiting==0:await asyncio.sleep(0)
    async def scenario():
        challenge,args=await prepared_http_operation(o)
        async with leases.read():  # actual admitted command lease singleton
            task=asyncio.create_task(post(o,request(o,'commit',args)))
            await asyncio.wait_for(waiting(),3)
            assert not task.done()
            assert o['config'].policy_path.read_bytes()==before
            if interruption=='revoke':o['state']['valid']=False
            elif interruption=='cancel':
                task.cancel()
                with pytest.raises(asyncio.CancelledError):await task
                assert leases.waiting==0
        if interruption!='cancel':
            result=await asyncio.wait_for(task,3)
            assert result.status_code==(200 if interruption=='release' else 403)
            assert (o['config'].policy_path.read_bytes()!=before)==(interruption=='release')
        else:
            assert o['config'].policy_path.read_bytes()==before
            status=await post(o,request(o,'operation',{'operation_id':challenge['operation_id']}))
            assert status.status_code==200
            assert status.json()['status']=='pending'
        assert leases.readers==0
        assert leases.waiting==0
        assert leases.writer is False
    asyncio.run(scenario())
