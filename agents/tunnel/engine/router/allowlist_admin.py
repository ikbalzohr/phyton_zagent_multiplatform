"""Dedicated OAuth+owner-capability routes; never part of model MCP discovery."""
import asyncio
import math
import time
from urllib.parse import urlsplit,urlunsplit
from fastapi.responses import JSONResponse
from .access import AuthorizationError,digest

SOURCE_FIELDS={'version','capability','placement','actions','key_id','request_key_id',
               'capability_revision','expires_at','revoked','mutations_ready'}
PLACEMENT={'principal_id','workspace_id','device_id','installation_id','target_profile_id'}
DENIED={'error':'ALLOWLIST_REQUEST_DENIED'}
MAX_BYTES=131072


def capability_for(cap,auth,placement,grant,method):
    action={'list':'list','operation':'status','prepare':None,'backup':None,'commit':None}.get(method)
    if action is None:
        from .access import AuthorizationError as _AE
        raise _AE('ALLOWLIST_MUTATIONS_NOT_READY',403)
    auth.require('files:read' if method in ('list','operation') else 'files:write')
    expected=dict(principal_id=auth.principal_id,workspace_id=auth.workspace_id,
        device_id=placement.device_id,installation_id=placement.installation_id,target_profile_id='agentRoot')
    if (type(cap) is not dict or set(cap)!=SOURCE_FIELDS or type(cap['version']) is not int or cap['version']!=1
        or cap['capability']!='executable_allowlist_management' or cap['placement']!=expected
        or type(cap['actions']) is not list or any(type(v) is not str for v in cap['actions'])
        or len(set(cap['actions']))!=len(cap['actions']) or action not in cap['actions']
        or not set(cap['actions'])<= {'list','add','remove','replace','status'}
        or cap['revoked'] is not False or cap['mutations_ready'] is not False
        or type(cap['expires_at']) is not int or not time.time()<cap['expires_at']
        or any(type(cap[k]) is not str or not cap[k] for k in ('key_id','request_key_id','capability_revision'))
        or grant.get('revoked',False) is not False or type(grant.get('expires_at')) not in (int,float)
        or not math.isfinite(grant['expires_at']) or not time.time()<grant['expires_at']):
        raise AuthorizationError('ALLOWLIST_REQUEST_DENIED',403)
    resource=grant.get('files_resource')
    if (type(resource) is not dict or resource.get('kind')!='files'
        or resource.get('revoked',False) is not False or resource.get('device_id')!=placement.device_id
        or resource.get('installation_id')!=placement.installation_id
        or 'agentRoot' not in resource.get('allowed_profile_ids',[resource.get('profile_id')])):
        raise AuthorizationError('ALLOWLIST_REQUEST_DENIED',403)
    return expected


class RouterAllowlist:
    def __init__(self,server):
        self.server=server
        self.active={}

    async def _files(self,path,payload):
        s=self.server
        candidates=[v for v in s.registry.enabled_states() if v.service['id'] in {'zagent_files','zagent_files_v3'}]
        if len(candidates)!=1:raise AuthorizationError('ALLOWLIST_NOT_CONFIGURED',503)
        state=candidates[0];url=urlsplit(state.service['url'])
        if (url.scheme!='http' or url.hostname not in {'127.0.0.1','127.0.0.3','::1'}
            or url.username or url.password or url.query or url.fragment or url.path!='/mcp'):
            raise AuthorizationError('ALLOWLIST_NOT_CONFIGURED',503)
        target=urlunsplit((url.scheme,url.netloc,path,'',''))
        client=s.registry._client(state)
        from .identity import internal_token
        import json
        async with client.stream('POST',target,json=payload,
            headers={'X-Zagent-Internal-Token':internal_token(),'Content-Type':'application/json'},
            timeout=25,follow_redirects=False) as response:
            if response.status_code!=200:raise AuthorizationError('ALLOWLIST_REQUEST_DENIED',403)
            raw=bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw)>MAX_BYTES:raise AuthorizationError('ALLOWLIST_REQUEST_DENIED',403)
            return json.loads(raw)

    async def _authorize(self,auth,method):
        s=self.server
        current=s.authorizer();grant=current.current_grant(auth)
        cap=await self._files('/allowlist/capability',{})
        expected=capability_for(cap,auth,s.placement,grant,method)
        return cap,expected

    async def catalog(self,auth):
        s=self.server;current=s.authorizer();grant=current.current_grant(auth)
        cap=await self._files('/allowlist/capability',{})
        from .profile_admin import PROFILE_ADMIN_SCOPES, require_profile_management
        require_profile_management(auth,s.placement,current,'allowlist_admin_list')
        expected=capability_for(cap,auth,s.placement,grant,'list')
        catalog=await s._files_catalog(auth,current)
        if 'agentRoot' not in catalog['allowed_profile_ids']:raise AuthorizationError('ALLOWLIST_REQUEST_DENIED',403)
        return dict(version=1,placement=expected,profile_generation=catalog['generations']['agentRoot'],
                    capability_revision=cap['capability_revision'],mutations_ready=False)

    async def dispatch(self,request,auth,bearer):
        if (type(request) is not dict or set(request)!={'version','kind','key_id','body','signature','arguments'}
            or type(request['body']) is not dict):raise AuthorizationError('ALLOWLIST_REQUEST_DENIED',403)
        body=request['body'];method=body.get('method');fields=body.get('context');nonce=body.get('nonce')
        view=await self.catalog(auth)
        if method not in ('list','operation'):raise AuthorizationError('ALLOWLIST_MUTATIONS_NOT_READY',403)
        if (type(fields) is not dict or any(fields.get(k)!=v for k,v in view['placement'].items())
            or fields.get('profile_generation')!=view['profile_generation']
            or fields.get('capability_revision')!=view['capability_revision']
            or type(fields.get('deadline')) not in (int,float) or not math.isfinite(fields['deadline'])
            or not time.time()<fields['deadline']<=auth.expires_at
            or type(nonce) is not str or not 1<=len(nonce)<=128):
            raise AuthorizationError('ALLOWLIST_REQUEST_DENIED',403)
        if len(self.active)>=128 or nonce in self.active:raise AuthorizationError('ALLOWLIST_REQUEST_DENIED',403)
        self.active[nonce]=(digest(request),bearer,auth,method,view)
        try:return await self._files('/allowlist/dispatch',request)
        finally:self.active.pop(nonce,None)

    async def current(self,body):
        if type(body) is not dict or set(body)!={'request_sha256','nonce'}:return {'current':False}
        row=self.active.get(body['nonce'])
        if row is None or row[0]!=body['request_sha256']:return {'current':False}
        _,bearer,initial,method,view=row
        s=self.server
        if s._auth_client is None:return {'current':False}
        auth=await s.authorizer().authenticate(bearer,s._auth_client)
        if (auth.principal_id!=initial.principal_id or auth.workspace_id!=initial.workspace_id
            or auth.policy_revision!=initial.policy_revision):return {'current':False}
        cap,placement=await self._authorize(auth,method)
        # No catalog/read lease here: callback may run inside Files writer lease.
        return {'current':placement==view['placement'] and cap['capability_revision']==view['capability_revision']}


def install_routes(server):
    route=RouterAllowlist(server)
    app=server.app
    @app.post('/broker/allowlist/catalog')
    async def catalog(request:server.Request):
        try:
            if await server.bounded_json(request)!={}:raise ValueError()
            return JSONResponse(await route.catalog(request.state.auth),headers={'Cache-Control':'no-store'})
        except Exception:return JSONResponse(DENIED,status_code=403)
    @app.post('/broker/allowlist')
    async def dispatch(request:server.Request):
        try:
            return JSONResponse(await route.dispatch(await server.bounded_json(request),request.state.auth,
                request.headers.get('authorization','')),headers={'Cache-Control':'no-store'})
        except Exception:return JSONResponse(DENIED,status_code=403)
    @app.post('/router/allowlist/current')
    async def current(request:server.Request):
        try:
            if not getattr(request.state,'internal',False):raise PermissionError()
            return JSONResponse(await route.current(await server.bounded_json(request)),headers={'Cache-Control':'no-store'})
        except Exception:return JSONResponse({'current':False},status_code=403)
    return route
