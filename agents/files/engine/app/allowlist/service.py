"""Internal broker facade; importing this module registers/enrolls nothing.

Only a separately authenticated adapter may supply TrustedMetadata. Never put
this facade behind generic Files execute or forward model-supplied metadata.
"""
from . import authority as a

FIELDS = {
    'list': set(),
    'prepare': {'payload','session_id'},
    'backup': {'operation_id'},
    'commit': {'operation_id','approval','backup_receipt'},
    'operation': {'operation_id'},
}

class AllowlistService:
    def __init__(self, engine):
        self.engine=engine

    async def dispatch(self, method, arguments, trusted_metadata):
        if method not in FIELDS or type(arguments) is not dict or set(arguments)!=FIELDS[method]:
            raise ValueError('INVALID_ALLOWLIST_RPC_ARGUMENTS')
        context=a._context_from_enrolled_adapter(self.engine.enrollment,trusted_metadata)
        if method=='prepare':
            session=arguments['session_id']
            if type(session) is not str or session!=context.fields['session_id']:
                raise PermissionError('REAL_SESSION_MISMATCH')
            prepared=await self.engine.prepare(context,arguments['payload'])
            return prepared.challenge
        if method=='list': return await self.engine.list(context)
        if method=='backup': return await self.engine.backup(context,arguments['operation_id'])
        if method=='operation': return await self.engine.operation(context,arguments['operation_id'])
        return await self.engine.commit(context,arguments['operation_id'],arguments['approval'],arguments['backup_receipt'])
