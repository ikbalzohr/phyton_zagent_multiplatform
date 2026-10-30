"""Inert private ASGI factory. Import does not bind, register or enroll anything.

Attestation authenticates the transport broker, NOT human approval. The real
engine independently verifies the original approval and durable backup receipt.
Never wrap this app in the generic Files catalog read lease (commit needs write).
"""
import asyncio
import os
import re
import time
from pathlib import Path
from . import authority as a, protocol as p
from .engine import AllowlistEngine
from .owner_loader import LoadedOwner, validate_private_path
from .service import AllowlistService, FIELDS
from app.core.execution_context import TrustedMetadata

KIND='zagent.allowlist.dispatch.v1'
AUDIENCE='zagent.allowlist.private-dispatch'
DENIED=b'{"error":"ALLOWLIST_REQUEST_DENIED"}'
MAX_BYTES=131072
MAX_NONCES=4096


class PrivateAllowlistApp:
    def __init__(self, owner):
        if type(owner) is not LoadedOwner: raise PermissionError('ALLOWLIST_REQUEST_DENIED')
        self.owner=owner
        c=owner.config
        self.service=AllowlistService(AllowlistEngine(c.policy_path,c.profiles_path,c.journal_dir,
                                                    enrollment=owner.enrollment))

    def _claim(self,nonce):
        # Persistent cross-process replay protection; no automatic deletion. A
        # restart never reaccepts a valid old signed request. Owner archival is
        # required at capacity; never clear this directory to recover a request.
        c=self.owner.config
        directory=validate_private_path(c.replay_dir,owner_sid=c.owner_sid,service_sid=c.service_sid)
        if sum(1 for _ in directory.iterdir())>=MAX_NONCES: raise PermissionError('ALLOWLIST_REQUEST_DENIED')
        path=directory/(p.sha(nonce.encode('ascii'))+'.nonce')
        with path.open('xb') as stream:
            stream.write(b'1');stream.flush();os.fsync(stream.fileno())
        validate_private_path(path,owner_sid=c.owner_sid,service_sid=c.service_sid)

    async def dispatch(self, request):
        # Only closed signed requests, never TrustedMetadata/VerifiedContext,
        # raw _meta, ordinary internal tokens or model booleans.
        if type(request) is not dict or set(request)!={'version','kind','key_id','body','signature','arguments'}:
            raise PermissionError('ALLOWLIST_REQUEST_DENIED')
        if (type(request['version']) is not int or request['version']!=1 or request['kind']!=KIND
            or request['key_id']!=self.owner.config.request_key_id):
            raise PermissionError('ALLOWLIST_REQUEST_DENIED')
        body=request['body']
        if type(body) is not dict or set(body)!={'method','arguments_sha256','context','nonce','iat','exp','audience'}:
            raise PermissionError('ALLOWLIST_REQUEST_DENIED')
        signed={k:request[k] for k in ('version','kind','key_id','body')}
        self.owner.request_key.verify(p.unb64(request['signature'],64),p.canonical(signed))
        now=time.time()
        if (body['audience']!=AUDIENCE or any(type(body[k]) is not int for k in ('iat','exp'))
            or not body['iat']<=now<body['exp']<=body['iat']+60):
            raise PermissionError('ALLOWLIST_REQUEST_DENIED')
        p.unb64(body['nonce'],32)
        method=body['method'];arguments=request['arguments'];fields=body['context']
        if (type(method) is not str or method not in FIELDS or type(arguments) is not dict
            or set(arguments)!=FIELDS[method] or body['arguments_sha256']!=p.sha(p.canonical(arguments))
            or type(fields) is not dict or set(fields)!=a.FIELDS
            or type(fields['deadline']) not in (int,float) or fields['deadline']>body['exp']
            or not self.owner.current_fields(fields)):
            raise PermissionError('ALLOWLIST_REQUEST_DENIED')
        # Construct typed metadata ONLY after cryptographic AND independent
        # current OAuth/runtime validation; constructor is not authentication.
        metadata=TrustedMetadata({a.META:fields})
        a._context_from_enrolled_adapter(self.owner.enrollment,metadata)
        self._claim(body['nonce'])
        return await self.service.dispatch(method,arguments,metadata)

    async def __call__(self, scope, receive, send):
        # No logging of exceptions or request bytes. Even backend private-path
        # errors use the same static channel. HTTP only; host owns routing/TLS.
        if scope.get('type')!='http': raise RuntimeError('HTTP_ONLY')
        try:
            if scope.get('method')!='POST' or scope.get('path')!='/': raise PermissionError()
            raw=bytearray()
            async with asyncio.timeout(10):
                while True:
                    event=await receive()
                    if event.get('type')!='http.request': raise PermissionError()
                    raw.extend(event.get('body',b''))
                    if len(raw)>MAX_BYTES: raise PermissionError()
                    if not event.get('more_body',False): break
            result=await self.dispatch(p.loads(bytes(raw)))
            response=p.canonical(result);status=200
        except Exception:
            response=DENIED;status=403
        await send({'type':'http.response.start','status':status,'headers':[
            (b'content-type',b'application/json'),(b'cache-control',b'no-store')]})
        await send({'type':'http.response.body','body':response})


def make_private_app(owner):
    """Return an UNREGISTERED app, no generic Files decorator or read lease."""
    return PrivateAllowlistApp(owner)
