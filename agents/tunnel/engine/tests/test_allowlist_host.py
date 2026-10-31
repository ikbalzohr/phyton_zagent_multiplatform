"""Windows real Router HTTP/OAuth perimeter with disposable upstream/introspection."""
import asyncio
import copy
import importlib
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import pytest
import httpx
from fastapi import FastAPI,Request


def test_dedicated_router_module_exists():
    assert importlib.util.find_spec('router.allowlist_admin') is not None


@pytest.fixture
def isolated_router_modules():
    # Importing the production server creates disposable journals/config state.
    # Restore both import caches; sys.modules alone leaves package attributes stale.
    import router
    names=('config','server','registry')
    missing=object()
    modules={name:sys.modules.get('router.'+name,missing) for name in names}
    attributes={name:getattr(router,name,missing) for name in names}
    try:
        for name in names:
            sys.modules.pop('router.'+name,None)
            if hasattr(router,name):delattr(router,name)
        yield
    finally:
        for name in names:
            if modules[name] is missing:sys.modules.pop('router.'+name,None)
            else:sys.modules['router.'+name]=modules[name]
            if attributes[name] is missing:
                if hasattr(router,name):delattr(router,name)
            else:setattr(router,name,attributes[name])


def test_actual_router_auth_catalog_forwarding_and_live_revocation(tmp_path,monkeypatch,isolated_router_modules):
    import json
    config=tmp_path/'config';config.mkdir()
    runtime=tmp_path/'runtime';runtime.mkdir()
    monkeypatch.setenv('ZAGENT_TUNNEL_CONFIG_DIR',str(config))
    monkeypatch.setenv('ZAGENT_TUNNEL_RUNTIME_DIR',str(runtime))
    monkeypatch.setenv('ZAGENT_DEVICE_ID','device')
    monkeypatch.setenv('ZAGENT_INSTALLATION_ID','install')
    monkeypatch.setenv('ZAGENT_INTERNAL_TOKEN','fixture-internal-token-32-bytes-minimum')
    monkeypatch.setenv('FIXTURE_INTROSPECT','fixture-credential')
    from router.access import principal_id
    principal=principal_id('https://issuer.invalid','owner')
    now=int(time.time())
    grant=dict(scopes=['files:read','files:write','allowlist-admin'],tools=['files_profile_admin_list','files_profile_admin_get','allowlist_admin_list'],expires_at=now+3600,revoked=False,
        files_resource=dict(kind='files',resource_id='r',profile_id='agentRoot',allowed_profile_ids=['agentRoot'],
                            device_id='device',installation_id='install',revoked=False),
        profile_management=dict(version=1,enabled=True,workspace_id='workspace',device_id='device',
            installation_id='install',actions=['list','get']))
    rs=dict(resource_uri='https://public.invalid/mcp',issuer='https://issuer.invalid',
        introspection_endpoint='https://issuer.invalid/introspect',workspace_id='workspace',policy_revision='grant-1',
        introspection_client_id='fixture',introspection_secret_env='FIXTURE_INTROSPECT',
        authorization_servers=['https://issuer.invalid'],grants={principal:grant})
    cfg=dict(resource_server=rs,tool_policy={},allowed_origins=[])
    def publish(): (config/'tunnel.json').write_text(json.dumps(cfg),encoding='utf-8')
    publish()
    service=dict(id='zagent_files',name='Files',namespace='files',url='http://127.0.0.1:18010/mcp',enabled=True)
    (config/'core_services.json').write_text(json.dumps({'services':[service]}),encoding='utf-8')
    (config/'additional_services.json').write_text('{"services":[]}',encoding='utf-8')
    server=importlib.import_module('router.server')
    from router.allowlist_admin import RouterAllowlist
    route=server.allowlist_routes
    cap=dict(version=1,capability='executable_allowlist_management',placement=dict(principal_id=principal,
        workspace_id='workspace',device_id='device',installation_id='install',target_profile_id='agentRoot'),
        actions=['list','status','add','remove','replace'],key_id='approval',request_key_id='request',
        capability_revision='cap-1',expires_at=now+3000,revoked=False,mutations_ready=False)
    state={'revoke':False,'dedicated':True};forwarded=[];checks=[]
    upstream=FastAPI()
    @upstream.post('/allowlist/capability')
    async def capability(request:Request):
        assert request.headers['x-zagent-internal-token']=='fixture-internal-token-32-bytes-minimum'
        return dict(cap,revoked=not state['dedicated'])
    @upstream.post('/allowlist/dispatch')
    async def dispatch(request:Request):
        body=await request.json();forwarded.append(body)
        if state['revoke']:
            cfg['resource_server']['grants'][principal]['revoked']=True;publish()
        check=await route.current({'request_sha256':server.authorizer().config and __import__('router.access',fromlist=['digest']).digest(body),'nonce':body['body']['nonce']})
        checks.append(check)
        if not check['current']:
            from fastapi.responses import JSONResponse
            return JSONResponse({'error':'denied'},status_code=403)
        return {'revision':'0'*64,'allowed_executables':['C:\\fixture.exe']}
    async def catalog(auth,current):
        current.current_grant(auth)
        return {'allowed_profile_ids':['agentRoot'],'generations':{'agentRoot':'generation-1'}}
    monkeypatch.setattr(server,'_files_catalog',catalog)
    def introspect(request):
        assert request.url==httpx.URL('https://issuer.invalid/introspect')
        assert request.headers['authorization'].startswith('Basic ')
        return httpx.Response(200,json=dict(active=True,iss='https://issuer.invalid',sub='owner',
            aud='https://public.invalid/mcp',scope='files:read files:write allowlist-admin',exp=now+3600))
    async def scenario():
        server._auth_client=httpx.AsyncClient(transport=httpx.MockTransport(introspect),trust_env=False)
        server.registry.clients['zagent_files']=httpx.AsyncClient(transport=httpx.ASGITransport(app=upstream),base_url='http://127.0.0.1:18010')
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app),base_url='https://public.invalid') as client:
                assert (await client.post('/broker/allowlist/catalog',json={})).status_code==401
                headers={'Authorization':'Bearer fixture-bearer'}
                result=await client.post('/broker/allowlist/catalog',json={},headers=headers)
                assert result.status_code==200,result.text
                view=result.json();assert view['profile_generation']=='generation-1' and view['mutations_ready'] is False
                fields={**view['placement'], 'profile_generation':view['profile_generation'],
                    'capability_revision':view['capability_revision'],'session_id':'real-fixture-session',
                    'actor_user_id':1,'chat_id':2,'thread_id':3,'deadline':now+50}
                original=dict(version=1,kind='zagent.allowlist.dispatch.v1',key_id='request',signature='opaque-backend-verifies',
                    arguments={},body=dict(method='list',context=fields,nonce='random-fixture-nonce'))
                result=await client.post('/broker/allowlist',json=original,headers=headers)
                assert result.status_code==200,result.text
                assert forwarded==[original] and checks==[{'current':True}]
                assert route.active=={}
                forged=copy.deepcopy(original);forged['body']['context']['profile_generation']='stale'
                assert (await client.post('/broker/allowlist',json=forged,headers=headers)).status_code==403
                forbidden=copy.deepcopy(original);forbidden['body']['method']='commit'
                assert (await client.post('/broker/allowlist',json=forbidden,headers=headers)).status_code==403
                assert len(forwarded)==1
                for field,value in [('scopes',['files:read','files:write']),
                                    ('tools',['files_profile_admin_list','files_profile_admin_get']),
                                    ('profile_management',dict(grant['profile_management'],enabled=False))]:
                    before=copy.deepcopy(grant[field]);grant[field]=value;publish()
                    assert (await client.post('/broker/allowlist/catalog',json={},headers=headers)).status_code==403
                    grant[field]=before;publish()
                state['dedicated']=False
                assert (await client.post('/broker/allowlist/catalog',json={},headers=headers)).status_code==403
                state['dedicated']=True;state['revoke']=True
                result=await client.post('/broker/allowlist',json=original,headers=headers)
                assert result.status_code==403 and route.active=={}
                assert not any('allowlist' in t['name'] for t in server._management_tools())
        finally:
            await server.registry.close();await server._auth_client.aclose();server._auth_client=None
            server.orchestrator.journal.conn.close();server.workflow_journal.conn.close()
    asyncio.run(scenario())
