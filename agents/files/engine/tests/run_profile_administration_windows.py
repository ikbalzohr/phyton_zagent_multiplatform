"""Disposable Windows behavioral fixture. NOT_RUN on source-only hosts.
Run from repository root: py -3 agents/files/engine/tests/run_profile_administration_windows.py
No product import occurs before Windows guard + all data paths redirected.
"""
import os
import sys
if os.name != 'nt':
    raise SystemExit('WINDOWS_ONLY: no product modules imported')
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace

with tempfile.TemporaryDirectory(prefix='zagent-profile-admin-') as temporary:
    base = Path(temporary)
    private = base / 'private'
    private.mkdir()
    os.environ.update(ZAGENT_INTERNAL_TOKEN='fixture-token-' + 'x'*40,
                      ZAGENT_DEVICE_ID='fixture-device', ZAGENT_INSTALLATION_ID='fixture-installation',
                      ZAGENT_CORE_DATA_ROOT=str(private))
    for variable, directory in {'DATA_ROOT':'data','CONFIG_DIR':'config','RUNTIME_DIR':'runtime','LOG_DIR':'logs','BACKUP_ROOT':'backups','UPDATE_STATE_ROOT':'updates'}.items():
        target = private / directory
        target.mkdir()
        os.environ['ZAGENT_FILES_' + variable] = str(target)
    os.environ['ZAGENT_FILES_ENGINE_ROOT'] = str(Path(__file__).resolve().parents[1])
    sys.path.insert(0, os.environ['ZAGENT_FILES_ENGINE_ROOT'])
    from app.profiles import manager
    from app.profiles import administration as a
    from app.core.execution_context import request_meta, TrustedMetadata, VerifiedContext, validate_profile, owner_key

    original = base / 'original'
    original.mkdir()
    (original/'marker.txt').write_text('unchanged',encoding='utf-8')
    initial = {'schema_version':'2.0','active_profile':'appBridge','profiles':[
        {'name':'appBridge','root':str(original),'mode':'read-write','enabled':True,'authorized_by_user':True}]}
    manager.PROFILES_FILE.write_text(json.dumps(initial),encoding='utf-8')
    common = {'version':1,'source':'oauth','actor_id':'fixture-principal','principal_id':'fixture-principal',
              'workspace_id':'fixture-workspace','device_id':'fixture-device','installation_id':'fixture-installation'}
    def channel(context,key):
        # Actual HTTP header + alias metadata consumer, not a direct trust cast.
        request = SimpleNamespace(headers={'x-zagent-internal-token':os.environ['ZAGENT_INTERNAL_TOKEN']})
        ctx = SimpleNamespace(request_context=SimpleNamespace(request=request,meta={key:context}))
        return request_meta(ctx)
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'tunnel' / 'engine'))
    from router.profile_admin import new_admin_context, catalog_context
    class Placement:
        device_id = 'fixture-device'
        installation_id = 'fixture-installation'
        def validate(self):
            assert self.device_id and self.installation_id
    placement = Placement()
    grant = {'expires_at':time.time()+1800,'revoked':False,'scopes':['files:read','files:write'],
             'tools':list(a.PROFILE_ADMIN_TOOLS),
             'profile_management':{'version':1,'enabled':True,'workspace_id':'fixture-workspace',
                 'device_id':placement.device_id,'installation_id':placement.installation_id,'actions':list(a.ACTIONS)},
             'files_resource':{'kind':'files','resource_id':'fixture-resource','profile_id':'appBridge','allowed_profile_ids':['appBridge'],
                 'device_id':placement.device_id,'installation_id':placement.installation_id}}
    def require(scope,tool):
        assert scope in grant['scopes'] and tool in grant['tools']
    auth = SimpleNamespace(principal_id='fixture-principal',workspace_id='fixture-workspace',expires_at=grant['expires_at'],policy_revision='fixture-policy',require=require)
    authorizer = SimpleNamespace(current_grant=lambda _:grant)
    def metadata(action,args):
        context = new_admin_context(auth,placement,authorizer,'files_profile_admin_'+action,args)['profile_admin_context']
        # Real Router producer -> canonical wire -> Files request_meta consumer.
        context = json.loads(a.canonical(context).decode('utf-8'))
        return channel(context,a.ADMIN_META)
    async def call(action,args):
        return await a.admin_call('files_profile_admin_'+action,args,metadata(action,args))
    async def denied(action,args,expected,meta=None):
        try:
            await a.admin_call('files_profile_admin_'+action,args,meta if meta is not None else metadata(action,args))
        except (ValueError,PermissionError,KeyError,RuntimeError,OSError) as error:
            assert expected in str(error),(expected,str(error))
        else:
            raise AssertionError('unexpected authorization/snapshot success: '+expected)
    async def run():
        catalog_meta = channel({**common,'deadline':time.time()+300}, a.CATALOG_META)
        catalog = await a.catalog_snapshot({},catalog_meta)
        assert not catalog['managed'] and catalog['owner'] is None
        assert 'owner_management' not in manager.load_profiles()
        root = base/'new-project'
        root.mkdir()
        args = {'target_profile_id':'_new','root':str(root),'mode':'read-write','description':'uji café 日本',
                'expected_revision':catalog['revision'],'idempotency_key':'create-1'}
        await denied('create',{**args,'metadata':{}},'INVALID_ADMIN_ARGUMENT_FIELDS')
        await denied('create',args,'AUTHENTICATED_INTERNAL_CHANNEL_REQUIRED',{})
        bad = metadata('create',args)
        bad[a.ADMIN_META]['principal_id'] = 'spoof'
        bad[a.ADMIN_META]['unknown'] = True
        await denied('create',args,'INVALID_PROFILE_CONTEXT_SCHEMA',bad)
        # Actual token mismatch must fail before the typed metadata is trusted.
        try:
            request_meta(SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers={'x-zagent-internal-token':'wrong'}),meta={})))
        except PermissionError as error:
            assert 'INVALID_INTERNAL_TOKEN' in str(error)
        else:
            raise AssertionError('wrong private channel token accepted')
        for field, wrong, expected in (('deadline',time.time()-1,'PROFILE_CONTEXT_EXPIRED'),('device_id','other-device','PROFILE_CONTEXT_PLACEMENT_MISMATCH'),('payload_digest','0'*64,'PROFILE_ADMIN_PAYLOAD_MISMATCH')):
            invalid = metadata('create',args)
            invalid[a.ADMIN_META][field] = wrong
            await denied('create',args,expected,invalid)
        result = await call('create',args)
        assert result['access_sync'] == 'committed'
        assert result == await call('create',args)
        await denied('create',{**args,'description':'different'},'IDEMPOTENCY_CONFLICT')
        await denied('set_default',{'target_profile_id':'_new','expected_revision':catalog['revision'],'idempotency_key':'stale'},'REVISION_CONFLICT')
        state = manager.load_profiles()
        assert state['owner_management']['owners']['fixture-principal']['allowed_profile_ids'] == ['appBridge','_new']
        assert not manager.PENDING_FILE.exists()
        try:
            manager.save_profiles(state)
        except PermissionError as error:
            assert 'SINGLE_WRITER' in str(error)
        else:
            raise AssertionError('legacy managed writer accepted')
        generation = state['owner_management']['generations']['_new']
        native = VerifiedContext({'profile_id':'_new','effective_access':'read','effective_resources':[{'profile_generation':generation}]})
        validate_profile(native,manager.get_profile('_new'))
        update = {'target_profile_id':'_new','changes':{'mode':'read-only'},'expected_revision':result['revision'],'idempotency_key':'update-1'}
        result = await call('update',update)
        try:
            validate_profile(native,manager.get_profile('_new'))
        except PermissionError as error:
            assert 'PROFILE_GENERATION_MISMATCH' in str(error)
        else:
            raise AssertionError('old generation accepted')
        result = await call('set_default',{'target_profile_id':'_new','expected_revision':result['revision'],'idempotency_key':'default-1'})
        state = manager.load_profiles()
        assert state['active_profile'] == state['owner_management']['owners']['fixture-principal']['default_profile_id'] == '_new'
        delete = {'target_profile_id':'_new','expected_revision':result['revision'],'idempotency_key':'delete-1'}
        await denied('delete',delete,'EXPLICIT_REPLACEMENT_DEFAULT_REQUIRED')
        result = await call('delete',{**delete,'replacement_default_id':'appBridge'})
        assert root.exists() and (original/'marker.txt').read_text() == 'unchanged'
        args = {**args,'expected_revision':result['revision'],'idempotency_key':'recreate-1'}
        result = await call('create',args)
        assert a.current_catalog()['generations']['_new'] != generation
        # Reject private directory itself AND a parent wrapping credentials.
        for number, forbidden in enumerate((private,base,private/'config')):
            await denied('create',{'target_profile_id':'forbidden'+str(number),'root':str(forbidden),'expected_revision':result['revision'],'idempotency_key':'private-'+str(number)},'PRIVATE_ROOT_OVERLAP')
        # A writer waits for the real read lease; cancellation/control remains reachable.
        async with a.read_lease():
            pending = asyncio.create_task(call('update',{'target_profile_id':'_new','changes':{'description':'lease test'},'expected_revision':result['revision'],'idempotency_key':'lease-1'}))
            await asyncio.sleep(0.05)
            assert not pending.done()
            async with a.read_lease(control=True):
                assert not pending.done()
        result = await asyncio.wait_for(pending,3)
        # Repeated task cancellation cannot release a worker's catalog lease
        # while its real thread is still running (no Windows Job claim here).
        import threading
        started, finish = threading.Event(), threading.Event()
        def blocked_worker():
            started.set()
            assert finish.wait(5), 'fixture worker release timed out'
            return 'finished'
        worker = asyncio.create_task(a.catalog_worker(asyncio.to_thread(blocked_worker)))
        writer_entered = asyncio.Event()
        async def waiting_writer():
            async with a.LEASES.write():
                writer_entered.set()
        try:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(.01)
            assert started.is_set()
            writer = asyncio.create_task(waiting_writer())
            for _ in range(3):
                worker.cancel()
                await asyncio.sleep(.01)
                assert not writer_entered.is_set() and not worker.done()
            async with a.read_lease(control=True):
                assert not writer_entered.is_set()
        finally:
            finish.set()
        try:
            await worker
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError('worker cancellation was swallowed')
        await asyncio.wait_for(writer, 3)
        assert writer_entered.is_set()
        # Atomic replace failure cannot return success or alter old document.
        previous = manager.PROFILES_FILE.read_bytes()
        replace = a.os.replace
        def fail_replace(*args,**kwargs):
            raise OSError('injected-replace-failure')
        a.os.replace = fail_replace
        try:
            await denied('update',{'target_profile_id':'_new','changes':{'description':'fault'},'expected_revision':result['revision'],'idempotency_key':'fault-1'},'injected-replace-failure')
        finally:
            a.os.replace = replace
        assert manager.PROFILES_FILE.read_bytes() == previous
        assert (original/'marker.txt').read_text() == 'unchanged'
        print('PASS Windows behavior: direct CRUD/default/CAS/idempotency/generation/no-ABA/private-roots/leases/atomic-fault/legacy-writer/token-serialization')
    try:
        asyncio.run(run())
    finally:
        if a._WRITER_HANDLE is not None:
            a._WRITER_HANDLE.close()
            a._WRITER_HANDLE = None
