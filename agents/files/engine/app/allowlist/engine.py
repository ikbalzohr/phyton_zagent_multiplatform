"""Fail-closed Windows allowlist transactions; no route registration or enrollment.

Owner bootstrap supplies fixed policy/catalog/journal paths and a dedicated
Enrollment. This class never discovers or enrolls the installed DataRoot.
Policy preimages exist only in bounded memory or a sealed broker envelope.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import copy
import os
from pathlib import Path
import re
import stat
import tempfile
import time
import uuid
from . import authority as a
from . import protocol as p

MAX_BYTES = 262144
MAX_PENDING = 32
RISK = "Executable runs with Windows owner-account OS rights, not a filesystem sandbox."


def _physical(path):
    path=Path(path)
    for part in (path,*path.parents):
        if part.exists() or part.is_symlink():
            info=part.lstat()
            if part.is_symlink() or getattr(info,"st_file_attributes",0)&stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise PermissionError("REPARSE_ADMIN_PATH")
    return path


def validate_executable(raw):
    """Validate, never repair the literal. Stale old entries use exact matching instead."""
    if os.name!="nt": raise PermissionError("WINDOWS_REQUIRED")
    if (not isinstance(raw,str) or not re.match(r"^[A-Za-z]:\\",raw)
        or len(raw)>2048 or any(ord(c)<32 or ord(c)==127 for c in raw)
        or any(c in raw for c in ('%','*','?','/')) or ':' in raw[2:]
        or os.path.normpath(raw)!=raw or any(part.endswith((' ','.')) for part in raw.split('\\'))):
        raise ValueError("EXACT_LOCAL_EXECUTABLE_REQUIRED")
    path=_physical(Path(raw))
    if path.suffix.casefold()!=".exe" or not path.is_file():
        raise ValueError("EXISTING_EXE_REQUIRED")
    # GetLongPathName rejects 8.3 aliases without silently rewriting the request.
    import ctypes
    buf=ctypes.create_unicode_buffer(32768)
    n=ctypes.windll.kernel32.GetLongPathNameW(str(path),buf,len(buf))
    if not n or n>=len(buf) or os.path.normcase(buf.value)!=os.path.normcase(raw):
        raise ValueError("EXECUTABLE_ALIAS_DENIED")
    return raw


def _read(path):
    _physical(path)
    with Path(path).open('rb') as stream:
        raw=stream.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES: raise ValueError("ADMIN_DOCUMENT_TOO_LARGE")
    return raw


def _atomic(path,raw):
    path=_physical(Path(path))
    fd,tmp=tempfile.mkstemp(prefix=path.name+'.candidate-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
        if _read(path)!=raw: raise OSError("ATOMIC_READBACK_MISMATCH")
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


@contextmanager
def _writer(policy):
    if os.name!='nt': raise PermissionError("WINDOWS_REQUIRED")
    import msvcrt
    lock=_physical(Path(str(policy)+'.allowlist.lock'))
    try:
        handle=lock.open('x+b')
        handle.write(b'0');handle.flush()
    except FileExistsError:
        handle=lock.open('r+b')
    locked=False
    try:
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            locked=True
        except OSError:
            raise BlockingIOError("ALLOWLIST_WRITER_BUSY") from None
        yield
    finally:
        if locked:
            handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
        handle.close()


@dataclass(frozen=True)
class Prepared:
    challenge: dict
    sealed_preimage: object
    payload: dict
    outcome: object = None


class AllowlistEngine:
    def __init__(self,policy_path,profiles_path,journal_dir,*,enrollment=None,
                 path_validator=validate_executable,clock=time.time,lease_factory=None):
        self.policy_path=Path(policy_path)
        self.profiles_path=Path(profiles_path)
        self.journal_dir=Path(journal_dir)
        self.enrollment=enrollment
        self.path_validator=path_validator
        self.clock=clock
        self._pending={}
        self._lease_factory=lease_factory

    def _lease(self,write=False):
        if self._lease_factory is not None: return self._lease_factory(write)
        from app.profiles.administration import LEASES
        return LEASES.write() if write else LEASES.read()

    def _auth(self,ctx,action):
        return a.authorize(self.enrollment,ctx,action)

    def _owner(self,f):
        return p.sha(p.canonical({k:f[k] for k in p.PLACEMENT}))

    def _binding(self,f):
        return p.sha(p.canonical({k:f[k] for k in set(p.PLACEMENT)|{
            'profile_generation','session_id','actor_user_id','chat_id','thread_id'}}))

    def _snapshot(self,f):
        from app.mcp.managed_commands import _policy_profiles,COMMAND_TOOL_NAMES,_local_path
        from app.profiles.administration import profile_generation,_validate_state
        raw=_read(self.policy_path)
        doc=p.loads(raw)
        policies=_policy_profiles(doc)
        profile_id=f['target_profile_id']
        if profile_id not in policies: raise PermissionError('COMMAND_PROFILE_NOT_ENROLLED')
        policy=policies[profile_id]
        profiles=p.loads(_read(self.profiles_path))
        _validate_state(profiles)
        rows=[r for r in profiles['profiles'] if r['name']==profile_id]
        if len(rows)!=1: raise PermissionError('PROFILE_NOT_UNIQUE')
        row=rows[0]
        if (row.get('enabled') is not True or row.get('authorized_by_user') is not True
            or row.get('mode')!='read-write' or profile_generation(row,profiles)!=f['profile_generation']):
            raise PermissionError('PROFILE_CHANGED_OR_NOT_APPROVED')
        for key in ('device_id','installation_id'):
            if key in row and row[key]!=f[key]: raise PermissionError('PROFILE_PLACEMENT_MISMATCH')
        if (policy['enabled'] is not True or policy['acknowledge_host_access'] is not True
            or policy['execution_mode']!='owner-account'):
            raise PermissionError('OWNER_ACCOUNT_APPROVAL_REQUIRED')
        if _local_path(policy['root'],True)!=_local_path(row['root'],True):
            raise PermissionError('COMMAND_ROOT_MISMATCH')
        tools=policy['allowed_tools']
        if (not isinstance(tools,list) or not tools or not all(isinstance(t,str) and t in COMMAND_TOOL_NAMES for t in tools)
            or len(set(tools))!=len(tools)):
            raise ValueError('INVALID_COMMAND_TOOLS')
        for key,upper in (('max_timeout_seconds',1800),('max_output_chars',200000)):
            if type(policy[key]) is not int or not 1<=policy[key]<=upper:
                raise ValueError('INVALID_COMMAND_LIMIT')
        exes=policy['allowed_executables']
        if (not isinstance(exes,list) or not 1<=len(exes)<=64
            or not all(isinstance(e,str) and e and len(e)<=2048 for e in exes)
            or len({e.casefold() for e in exes})!=len(exes)):
            raise ValueError('INVALID_EXISTING_ALLOWLIST')
        return raw,doc,policy

    async def list(self,context):
        f=self._auth(context,'list')
        async with self._lease():
            self._auth(context,'list')
            raw,_,policy=self._snapshot(f)
            return dict(revision=p.sha(raw),allowed_executables=copy.deepcopy(policy['allowed_executables']))

    def _payload(self,payload,f):
        payload=p.loads(p.canonical(payload))
        if not isinstance(payload,dict): raise ValueError('INVALID_PAYLOAD')
        action=payload.get('action')
        fields={'action','target_profile_id'}
        if action in ('add','remove'): fields.add('executable')
        elif action=='replace': fields|={'old_executable','new_executable'}
        else: raise ValueError('INVALID_ACTION')
        if (set(payload)!=fields or any(not isinstance(v,str) or not 0<len(v)<=2048
            or any(ord(c)<32 or ord(c)==127 for c in v) for v in payload.values())):
            raise ValueError('INVALID_PAYLOAD_FIELDS')
        if payload['target_profile_id']!=f['target_profile_id']:
            raise PermissionError('TARGET_PLACEMENT_MISMATCH')
        return payload

    def _candidate(self,doc,policy,payload):
        exes=policy['allowed_executables']
        action=payload['action']
        if action in ('remove','replace'):
            old=payload['executable'] if action=='remove' else payload['old_executable']
            if old not in exes: raise ValueError('EXACT_OLD_EXECUTABLE_REQUIRED')
            index=exes.index(old)
        if action in ('add','replace'):
            new=payload['executable'] if action=='add' else payload['new_executable']
            if self.path_validator(new)!=new: raise ValueError('VALIDATOR_MUST_PRESERVE_LITERAL')
            if new.casefold() in {e.casefold() for e in exes}:
                raise ValueError('DUPLICATE_EXECUTABLE')
        updated=exes.copy()
        if action=='add': updated.append(new)
        elif action=='remove': updated.pop(index)
        else: updated[index]=new
        if not 1<=len(updated)<=64: raise ValueError('NONEMPTY_BOUNDED_ALLOWLIST_REQUIRED')
        policy['allowed_executables']=updated
        raw=p.canonical(doc)+b'\n'
        if len(raw)>MAX_BYTES: raise ValueError('CANDIDATE_TOO_LARGE')
        return raw

    def _journal_path(self,op):
        if not isinstance(op,str) or not re.fullmatch('[0-9a-f]{32}',op):
            raise ValueError('INVALID_OPERATION_ID')
        return self.journal_dir/(op+'.json')

    def _validate_record(self,record,operation_id):
        fields={'owner','binding','keyhash','fingerprint','challenge','candidate_sha256','state','outcome'}
        challenge_fields=set(p.METADATA)|{'profile_generation','session_id','action','nonce','iat','exp','placement_risk'}
        try:
            if type(record) is not dict or set(record)!=fields: raise ValueError()
            c=record['challenge']
            if type(c) is not dict or set(c)!=challenge_fields or c['operation_id']!=operation_id: raise ValueError()
            for k in ('owner','binding','keyhash','fingerprint','candidate_sha256'):
                if type(record[k]) is not str or not re.fullmatch('[0-9a-f]{64}',record[k]): raise ValueError()
            for k in ('challenge_id','operation_id'):
                if type(c[k]) is not str or not re.fullmatch('[0-9a-f]{32}',c[k]): raise ValueError()
            for k in ('expected_revision','payload_sha256'):
                if type(c[k]) is not str or not re.fullmatch('[0-9a-f]{64}',c[k]): raise ValueError()
            for k in set(p.PLACEMENT)|{'profile_generation','session_id'}:
                if not a._text(c[k]): raise ValueError()
            p.unb64(c['nonce'],32)
            if (type(c['iat']) is not int or type(c['exp']) is not int
                or not c['iat']<c['exp']<=c['iat']+300 or c['action'] not in ('add','remove','replace')
                or c['placement_risk']!=RISK): raise ValueError()
            state=record['state']
            if state not in ('pending','committing','applied','failed','expired','conflict'): raise ValueError()
            outcome=record['outcome']
            if state in ('pending','committing'):
                if outcome is not None: raise ValueError()
            else:
                expected=dict(status=state,operation_id=operation_id)
                if state=='applied': expected['revision']=record['candidate_sha256']
                if type(outcome) is not dict or outcome!=expected: raise ValueError()
            return record
        except (KeyError,TypeError,ValueError):
            raise ValueError('INVALID_OPERATION_JOURNAL') from None

    def _records(self):
        _physical(self.journal_dir)
        if not self.journal_dir.exists(): return []
        paths=list(self.journal_dir.glob('*.json'))
        if len(paths)>4096: raise PermissionError('JOURNAL_CAPACITY_REQUIRES_OWNER_ARCHIVE')
        return [self._validate_record(p.loads(_read(path)),path.stem) for path in paths]

    def _reconcile_writer(self):
        # Never obscure an unresolved prior publication with a later mutation.
        # Exact-byte recovery is safe; any third revision needs owner review.
        for record in self._records():
            if record['state']=='committing' and self._recover(record)['status']=='uncertain':
                raise PermissionError('UNRESOLVED_POLICY_PUBLICATION')

    def _save(self,record):
        _physical(self.journal_dir)
        self.journal_dir.mkdir(parents=True,exist_ok=True)
        _atomic(self._journal_path(record['challenge']['operation_id']),p.canonical(record))

    def _load(self,op,f):
        path=self._journal_path(op)
        try: record=self._validate_record(p.loads(_read(path)),op)
        except FileNotFoundError: raise KeyError('OPERATION_NOT_FOUND') from None
        if record['owner']!=self._owner(f) or record['binding']!=self._binding(f):
            raise PermissionError('OPERATION_OWNER_MISMATCH')
        return record

    def _expire_memory(self):
        now=self.clock()
        for op,pending in list(self._pending.items()):
            if pending.challenge['exp']<=now: self._pending.pop(op)

    async def prepare(self,context,payload,expected_revision=None,idempotency_key=None):
        f=self._auth(context,None)
        payload=self._payload(payload,f)
        self._auth(context,payload['action'])
        if expected_revision is not None and (not isinstance(expected_revision,str) or not re.fullmatch('[0-9a-f]{64}',expected_revision)):
            raise ValueError('INVALID_EXPECTED_REVISION')
        op=uuid.uuid4().hex
        key=idempotency_key if idempotency_key is not None else op
        if not isinstance(key,str) or not 1<=len(key)<=128: raise ValueError('INVALID_IDEMPOTENCY_KEY')
        async with self._lease():
            with _writer(self.policy_path):
                self._auth(context,payload['action'])
                # A supplied CAS revision is part of the stable request fingerprint.
                fingerprint=p.sha(p.canonical(dict(payload=payload,expected_revision=expected_revision,binding=self._binding(f))))
                keyhash=p.sha(p.canonical(dict(owner=self._owner(f),key=key)))
                for rec in self._records():
                    if rec['keyhash']==keyhash:
                        if rec['fingerprint']!=fingerprint: raise ValueError('IDEMPOTENCY_CONFLICT')
                        old=rec['challenge']['operation_id']
                        result=self._recover(rec)
                        pending=self._pending.get(old)
                        return Prepared(copy.deepcopy(rec['challenge']),copy.deepcopy(pending.sealed_preimage) if pending else None,
                                        payload,copy.deepcopy(result))
                self._reconcile_writer()
                raw,doc,policy=self._snapshot(f)
                revision=p.sha(raw)
                if expected_revision is not None and expected_revision!=revision: raise ValueError('REVISION_CONFLICT')
                candidate=self._candidate(doc,policy,payload)
                self._expire_memory()
                if len(self._pending)>=MAX_PENDING: raise PermissionError('PENDING_CAPACITY_REACHED')
                now=int(self.clock())
                exp=min(now+240,int(f['deadline']))
                if exp<=now: raise PermissionError('CONTEXT_EXPIRED')
                challenge={**dict(self.enrollment.placement), 'challenge_id':uuid.uuid4().hex,'operation_id':op,
                    'expected_revision':revision,'payload_sha256':p.sha(p.canonical(payload)),
                    'profile_generation':f['profile_generation'],'session_id':f['session_id'],'action':payload['action'],
                    'nonce':p.b64(os.urandom(32)),'iat':now,'exp':exp,'placement_risk':RISK}
                sealed=p.seal(raw,self.enrollment.backup_key,{k:challenge[k] for k in p.METADATA})
                prepared=Prepared(challenge,sealed,payload)
                record=dict(owner=self._owner(f),binding=self._binding(f),keyhash=keyhash,fingerprint=fingerprint,
                    challenge=challenge,candidate_sha256=p.sha(candidate),state='pending',outcome=None)
                self._save(record)
                # Keep only candidate and encrypted preimage, not retained plaintext backup.
                self._pending[op]=Prepared(copy.deepcopy(challenge),sealed,dict(payload),candidate)
                return copy.deepcopy(prepared)

    async def backup(self,context,operation_id):
        f=self._auth(context,None)
        async with self._lease():
            with _writer(self.policy_path):
                rec=self._load(operation_id,f)
                self._auth(context,rec['challenge']['action'])
                raw,_,_=self._snapshot(f)
                if p.sha(raw)!=rec['challenge']['expected_revision']: raise ValueError('REVISION_CONFLICT')
                self._expire_memory()
                pending=self._pending.get(operation_id)
                if rec['state']!='pending' or pending is None: raise PermissionError('OPERATION_NOT_PENDING')
                return copy.deepcopy(pending.sealed_preimage)

    def _result(self,rec,status):
        result=dict(status=status,operation_id=rec['challenge']['operation_id'])
        if status=='applied': result['revision']=rec['candidate_sha256']
        rec.update(state=status,outcome=result)
        self._save(rec)
        if status!='pending': self._pending.pop(rec['challenge']['operation_id'],None)
        return copy.deepcopy(result)

    def _recover(self,rec):
        if rec['state']=='committing':
            digest=p.sha(_read(self.policy_path))
            if digest==rec['candidate_sha256']: return self._result(rec,'applied')
            if digest==rec['challenge']['expected_revision']: return self._result(rec,'failed')
            return dict(status='uncertain',operation_id=rec['challenge']['operation_id'])
        if rec['outcome'] is not None: return copy.deepcopy(rec['outcome'])
        if rec['challenge']['exp']<=self.clock(): return self._result(rec,'expired')
        return dict(status='pending',operation_id=rec['challenge']['operation_id'])

    async def operation(self,context,operation_id):
        f=self._auth(context,'status')
        async with self._lease():
            with _writer(self.policy_path):
                self._auth(context,'status')
                try: rec=self._load(operation_id,f)
                except KeyError: return dict(status='not_found',operation_id=operation_id)
                return self._recover(rec)

    async def commit(self,context,operation_id,approval,backup_receipt):
        f=self._auth(context,None)
        async with self._lease(True):
            with _writer(self.policy_path):
                rec=self._load(operation_id,f)
                c=rec['challenge']
                self._auth(context,c['action'])
                if rec['state']!='pending': return self._recover(rec)
                if self.clock()>=c['exp']: return self._result(rec,'expired')
                pending=self._pending.get(operation_id)
                if pending is None: return self._result(rec,'expired')
                metadata={k:c[k] for k in p.METADATA}
                identity={k:c[k] for k in p.PLACEMENT}
                rule=p.sha(p.canonical(dict(identity,action=c['action'],payload=pending.payload)))
                expected={**metadata,'idempotency_key':operation_id,'profile_generation':c['profile_generation'],
                    'session_id':c['session_id'],'action':c['action'],'nonce':c['nonce'],'rule_digest':rule,
                    **{k:f[k] for k in ('actor_user_id','chat_id','thread_id')}}
                p.verify(approval,p.APPROVAL,self.enrollment.key_id,self.enrollment.approval_key,expected,int(self.clock()))
                p.verify(backup_receipt,p.BACKUP,self.enrollment.key_id,self.enrollment.approval_key,
                         metadata,int(self.clock()))
                self._auth(context,c['action'])
                self._reconcile_writer()
                raw,doc,policy=self._snapshot(f)
                if p.sha(raw)!=c['expected_revision']: return self._result(rec,'conflict')
                # New executable may disappear/change into a reparse path during broker backup.
                candidate=self._candidate(doc,policy,pending.payload)
                if p.sha(candidate)!=rec['candidate_sha256']: raise ValueError('CANDIDATE_CHANGED')
                self._auth(context,c['action'])
                if self.clock()>=c['exp']: return self._result(rec,'expired')
                # Recheck signatures after all validation immediately before publication.
                p.verify(approval,p.APPROVAL,self.enrollment.key_id,self.enrollment.approval_key,expected,int(self.clock()))
                p.verify(backup_receipt,p.BACKUP,self.enrollment.key_id,self.enrollment.approval_key,
                         metadata,int(self.clock()))
                if p.sha(_read(self.policy_path))!=c['expected_revision']: return self._result(rec,'conflict')
                rec['state']='committing'
                self._save(rec)  # durable intent contains no preimage or policy body
                _atomic(self.policy_path,candidate)
                return self._result(rec,'applied')