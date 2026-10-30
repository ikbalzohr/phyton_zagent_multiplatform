"""Core-owned Files cohost. Routes are not MCP tools and never take a generic read lease."""
import contextvars
import hmac
import os
import time
from pathlib import Path
import httpx
from starlette.responses import JSONResponse
from . import protocol as p
from .adapter import make_private_app, MAX_BYTES
from .bootstrap import configuration, RUNTIME_URL, ROUTER_URL
from .owner_loader import load_owner, validate_private_path, process_sid

ACTIVE=contextvars.ContextVar('allowlist_original_request',default=None)
RUNTIME_FIELDS={'session_id','profile_generation','actor_user_id','chat_id','thread_id'}


def verify_runtime_view(view,request,nonce,key,key_id,now=None):
    now=time.time() if now is None else now
    if (type(view) is not dict or set(view)!={'version','kind','key_id','body','signature'}
        or type(view['version']) is not int or view['version']!=1
        or view['kind']!='zagent.allowlist.runtime-context.v1' or view['key_id']!=key_id):
        raise PermissionError('ALLOWLIST_RUNTIME_DENIED')
    signed={k:view[k] for k in ('version','kind','key_id','body')}
    key.verify(p.unb64(view['signature'],64),p.canonical(signed))
    b=view['body']
    if (type(b) is not dict or set(b)!={'audience','request_sha256','verifier_nonce','iat','exp','context'}
        or b['audience']!='zagent.allowlist.windows-runtime'
        or b['request_sha256']!=p.sha(p.canonical(request)) or b['verifier_nonce']!=nonce
        or any(type(b[k]) is not int for k in ('iat','exp'))
        or not b['iat']<=now<b['exp']<=b['iat']+15
        or type(b['context']) is not dict or b['context']!=request['body']['context']):
        raise PermissionError('ALLOWLIST_RUNTIME_DENIED')
    # Also require exact scalar types; Python True==1 is not an authority match.
    if any(type(v) is not type(request['body']['context'][k]) for k,v in b['context'].items()):
        raise PermissionError('ALLOWLIST_RUNTIME_DENIED')
    return {k:b['context'][k] for k in RUNTIME_FIELDS}


class FilesAllowlistHost:
    def __init__(self,manifest_path,*,post=None):
        self.path=Path(manifest_path)
        sid=process_sid()
        validate_private_path(self.path,owner_sid=sid,service_sid=sid)
        self.raw=self.path.read_bytes()
        if len(self.raw)>32768:raise PermissionError('ALLOWLIST_HOST_DISABLED')
        self.manifest=p.loads(self.raw)
        self.config=configuration(self.manifest)
        # Production endpoints are constants, never HTTP/body-provided URLs.
        self.post=post or self._post
        self.owner=load_owner(self.config,oauth_current=self.oauth_current,resolve_runtime=self.resolve_runtime)
        self.app=make_private_app(self.owner)

    @staticmethod
    def _post(url,body,internal=False):
        headers={'Content-Type':'application/json'}
        if internal:
            token=os.environ.get('ZAGENT_INTERNAL_TOKEN','')
            if not token:raise PermissionError('ALLOWLIST_HOST_DISABLED')
            headers['X-Zagent-Internal-Token']=token
        with httpx.Client(trust_env=False,follow_redirects=False,timeout=5) as client:
            with client.stream('POST',url,content=p.canonical(body),headers=headers) as response:
                if response.status_code!=200:raise PermissionError('ALLOWLIST_HOST_DISABLED')
                raw=bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw)>MAX_BYTES:raise PermissionError('ALLOWLIST_HOST_DISABLED')
                return p.loads(bytes(raw))

    def _current_manifest(self):
        validate_private_path(self.path,owner_sid=self.config.owner_sid,service_sid=self.config.service_sid)
        if self.path.read_bytes()!=self.raw:raise PermissionError('ALLOWLIST_HOST_DISABLED')

    def capability(self):
        self._current_manifest()
        self.owner._validate_config()
        source=self.owner._source()
        self.owner._validate_source(source)
        if source!=self.owner._initial:raise PermissionError('ALLOWLIST_HOST_DISABLED')
        for role in ('approval','backup','request'):self.owner._key(role)
        return dict(source,mutations_ready=False)

    def oauth_current(self,fields):
        try:
            self._current_manifest()
            request=ACTIVE.get()
            if request is None or request['body']['context']!=fields:return False
            reply=self.post(ROUTER_URL+'/router/allowlist/current',
                {'request_sha256':p.sha(p.canonical(request)),'nonce':request['body']['nonce']},True)
            return type(reply) is dict and reply=={'current':True}
        except Exception:return False

    def resolve_runtime(self,fields):
        self._current_manifest()
        request=ACTIVE.get()
        if request is None or request['body']['context']!=fields:raise PermissionError('ALLOWLIST_RUNTIME_DENIED')
        nonce=p.b64(os.urandom(32))
        view=self.post(RUNTIME_URL,{'request':request,'verifier_nonce':nonce},False)
        return verify_runtime_view(view,request,nonce,self.owner.request_key,self.config.request_key_id)

    async def dispatch(self,request):
        # Deliberately immutable OFF: later operational readiness is not point 1/2.
        if request.get('body',{}).get('method') not in ('list','operation'):
            raise PermissionError('ALLOWLIST_MUTATIONS_NOT_READY')
        token=ACTIVE.set(request)
        try:return await self.app.dispatch(request)
        finally:ACTIVE.reset(token)


def _internal(request):
    if not request.client or request.client.host not in ('127.0.0.1','127.0.0.3','::1'):
        raise PermissionError('ALLOWLIST_REQUEST_DENIED')
    expected=os.environ.get('ZAGENT_INTERNAL_TOKEN','')
    actual=request.headers.get('x-zagent-internal-token','')
    if not expected or not hmac.compare_digest(expected,actual):raise PermissionError('ALLOWLIST_REQUEST_DENIED')


async def _body(request):
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>MAX_BYTES:raise PermissionError('ALLOWLIST_REQUEST_DENIED')
    return p.loads(bytes(raw))


def register_routes(mcp,host):
    """Same Core-owned listener, explicit loopback+internal token on EVERY route."""
    @mcp.custom_route('/allowlist/capability',methods=['POST'],include_in_schema=False)
    async def capability(request):
        try:
            _internal(request)
            if host is None or await _body(request)!={}:raise PermissionError()
            result=host.capability()
            return JSONResponse(result,headers={'Cache-Control':'no-store'})
        except Exception:return JSONResponse({'error':'ALLOWLIST_REQUEST_DENIED'},status_code=403)

    @mcp.custom_route('/allowlist/dispatch',methods=['POST'],include_in_schema=False)
    async def dispatch(request):
        try:
            _internal(request)
            if host is None:raise PermissionError()
            result=await host.dispatch(await _body(request))
            return JSONResponse(result,headers={'Cache-Control':'no-store'})
        except Exception:return JSONResponse({'error':'ALLOWLIST_REQUEST_DENIED'},status_code=403)


def install_core_routes(mcp):
    """Called by real Files startup. Missing bootstrap disables only these routes."""
    root=os.environ.get('ZAGENT_CORE_DATA_ROOT','')
    host=None
    if root:
        manifest=Path(root)/'allowlist'/'owner.json'
        if manifest.exists():
            candidate=FilesAllowlistHost(manifest)
            from app.paths import CONFIG_DIR
            if (candidate.config.data_root!=Path(root)
                or candidate.config.policy_path!=CONFIG_DIR/'remote_execution_policy.json'
                or candidate.config.profiles_path!=CONFIG_DIR/'profiles.json'):
                raise PermissionError('ALLOWLIST_HOST_DISABLED')
            host=candidate
    register_routes(mcp,host)
    return host
