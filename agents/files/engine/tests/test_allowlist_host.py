import asyncio
import copy
import importlib.util
import time
from dataclasses import asdict
from pathlib import Path
import pytest
import httpx
from mcp.server.fastmcp import FastMCP
from test_allowlist_adapter import owner_env, tmp_path, protect, request, env
from app.allowlist import protocol as p


def test_core_managed_host_and_runtime_bridge_exist():
    assert importlib.util.find_spec('app.allowlist.host') is not None


@pytest.fixture
def host_env(owner_env,monkeypatch):
    from app.allowlist.host import FilesAllowlistHost
    from app.allowlist.bootstrap import MANIFEST_KIND,ROUTER_URL,RUNTIME_URL
    o=owner_env
    config=asdict(o['config'])
    for k,v in config.items():
        if isinstance(v,Path):config[k]=str(v)
        elif isinstance(v,frozenset):config[k]=sorted(v)
    doc=dict(version=1,kind=MANIFEST_KIND,configuration=config,router_url=ROUTER_URL,
             runtime_url=RUNTIME_URL,mutations_ready=False,bundle_sha256='0'*64)
    manifest=o['config'].data_root/'owner.json';manifest.write_bytes(p.canonical(doc));protect(manifest)
    calls=[];state={'oauth':True,'context':None,'fault':None}
    def post(url,body,internal):
        calls.append((url,copy.deepcopy(body),internal))
        if url.endswith('/router/allowlist/current'):return {'current':state['oauth']}
        assert url==RUNTIME_URL and internal is False
        now=int(time.time())
        context=copy.deepcopy(state['context'])
        if state['fault']=='session':context['session_id']='reset-session'
        value=dict(audience='zagent.allowlist.windows-runtime',request_sha256=p.sha(p.canonical(body['request'])),
                   verifier_nonce=body['verifier_nonce'],iat=now,exp=now+15,context=context)
        fault=state['fault']
        if fault=='nonce':value['verifier_nonce']=p.b64(bytes(32))
        elif fault=='digest':value['request_sha256']='0'*64
        elif fault=='future':value['iat']=now+10;value['exp']=now+15
        elif fault=='expired':value['iat']=now-20;value['exp']=now-1
        elif fault=='audience':value['audience']='other'
        view=dict(version=1,kind='zagent.allowlist.runtime-context.v1',key_id='transport-key',body=value)
        view['signature']=p.b64(o['request_key'].sign(p.canonical(view)))
        if fault=='signature':view['signature']=p.b64(bytes(64))
        return view
    host=FilesAllowlistHost(manifest,post=post)
    mcp=FastMCP('fixture',stateless_http=True)
    from app.allowlist.host import register_routes
    register_routes(mcp,host)
    monkeypatch.setenv('ZAGENT_INTERNAL_TOKEN','fixture-internal')
    return dict(o=o,host=host,calls=calls,state=state,app=mcp.streamable_http_app(),manifest=manifest,doc=doc)


async def post(h,path,body,token='fixture-internal',client=('127.0.0.1',123)):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=h['app'],client=client),base_url='http://localhost') as c:
        return await c.post(path,content=p.canonical(body),headers={'X-Zagent-Internal-Token':token})


def test_actual_fastmcp_cohost_routes_and_runtime_lookup(host_env):
    h=host_env;r=request(h['o']);h['state']['context']=copy.deepcopy(r['body']['context'])
    result=asyncio.run(post(h,'/allowlist/dispatch',r))
    assert result.status_code==200,result.text
    assert result.json()['allowed_executables']==h['o']['e']['paths'][:2]
    assert any(v[0].endswith('/runtime/allowlist-context') for v in h['calls'])
    nonces=[v[1]['verifier_nonce'] for v in h['calls'] if not v[2]]
    assert len(nonces)==len(set(nonces)) and nonces
    assert all(v[1]['request']==r for v in h['calls'] if not v[2])
    cap=asyncio.run(post(h,'/allowlist/capability',{}))
    assert cap.status_code==200
    assert cap.json()['mutations_ready'] is False
    assert [t for t in h['app'].routes if getattr(t,'path','').startswith('/allowlist/')]


@pytest.mark.parametrize('fault',['session','nonce','digest','future','expired','audience','signature'])
def test_untrusted_or_noncurrent_runtime_views_deny(host_env,fault):
    h=host_env;r=request(h['o']);h['state']['context']=copy.deepcopy(r['body']['context']);h['state']['fault']=fault
    response=asyncio.run(post(h,'/allowlist/dispatch',r))
    assert response.status_code==403 and response.json()=={'error':'ALLOWLIST_REQUEST_DENIED'}


@pytest.mark.parametrize('fault',['oauth','token','remote','manifest','mutations'])
def test_private_routes_and_readiness_fail_closed(host_env,fault):
    h=host_env;r=request(h['o']);h['state']['context']=copy.deepcopy(r['body']['context'])
    kwargs={}
    if fault=='oauth':h['state']['oauth']=False
    elif fault=='token':kwargs['token']='wrong'
    elif fault=='remote':kwargs['client']=('192.0.2.1',123)
    elif fault=='manifest':h['manifest'].write_bytes(p.canonical(dict(h['doc'],mutations_ready=True)))
    elif fault=='mutations':r=request(h['o'],'prepare',{'payload':{},'session_id':'anything'})
    response=asyncio.run(post(h,'/allowlist/dispatch',r,**kwargs))
    assert response.status_code==403
    assert list(h['o']['config'].replay_dir.iterdir())==[]


def test_missing_enrollment_does_not_disable_native_server(monkeypatch):
    from app.allowlist.host import install_core_routes
    monkeypatch.delenv('ZAGENT_CORE_DATA_ROOT',raising=False)
    m=FastMCP('unenrolled',stateless_http=True)
    assert install_core_routes(m) is None
    h={'app':m.streamable_http_app()}
    assert asyncio.run(post(h,'/allowlist/dispatch',{})).status_code==403
