"""Explicit owner-bootstrap seam; no discovery, enrollment, writes or activation.

This versioned source is NOT an existing Core capability convention. A reviewed
host must supply it, real OAuth revalidation and independent runtime resolution.
pywin32 is required on Windows; missing native security APIs fail closed.
"""
from dataclasses import dataclass
from pathlib import Path
import os
import re
import stat
import time
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
from . import authority as a, protocol as p

# Standard protected Windows owners; never infer trust from arbitrary group ACEs.
SYSTEM = 'S-1-5-18'
ADMINS = 'S-1-5-32-544'
INSTALLER = 'S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464'
WRITE_MASK = 0x10000000 | 0x40000000 | 0x000D0156  # generic/modify/delete/ACL/owner
SOURCE_FIELDS = {'version','capability','placement','actions','key_id','request_key_id',
                 'capability_revision','expires_at','revoked'}


@dataclass(frozen=True)
class OwnerConfiguration:
    """Only trusted owner startup constructs this; NEVER deserialize HTTP input.

    All paths absolute, pre-existing, private, under the supplied DataRoot.
    Digests pin raw 32-byte public key files, not line-projected read output.
    """
    data_root: Path
    source_path: Path
    policy_path: Path
    profiles_path: Path
    journal_dir: Path
    replay_dir: Path
    approval_key_path: Path
    backup_key_path: Path
    request_key_path: Path
    owner_sid: str
    service_sid: str
    placement: dict
    actions: frozenset
    key_id: str
    request_key_id: str
    capability_revision: str
    approval_key_sha256: str
    backup_key_sha256: str
    request_key_sha256: str


def process_sid():
    if os.name != 'nt': raise PermissionError('OWNER_LOADER_DENIED')
    import win32api, win32con, win32security as s
    token=s.OpenProcessToken(win32api.GetCurrentProcess(),win32con.TOKEN_QUERY)
    try:
        return s.ConvertSidToStringSid(s.GetTokenInformation(token,s.TokenUser)[0])
    finally:
        token.Close()


def _absolute(value):
    raw=os.fspath(value)
    if (not re.fullmatch(r'[A-Za-z]:\\[^\x00-\x1f]*',raw) or ':' in raw[2:]
        or any(c in raw for c in ('/','%','*','?')) or os.path.normpath(raw)!=raw
        or any(v.endswith((' ','.')) for v in raw.split('\\'))):
        raise PermissionError('OWNER_LOADER_DENIED')
    return Path(raw)


def validate_private_path(path, *, owner_sid, service_sid, private=True):
    """Read native owner/DACL at EVERY existing ancestor, reject reparse points.

    Private objects only grant owner/service/SYSTEM/admin. Ancestors may grant
    public read/traverse but never public write. Unknown allow ACE types deny.
    Deny ACEs do not cancel a dangerous allow ACE (conservative fail closed).
    """
    if os.name!='nt': raise PermissionError('OWNER_LOADER_DENIED')
    import win32security as s
    path=_absolute(path)
    trusted={owner_sid,service_sid,SYSTEM,ADMINS}
    standard=trusted|{INSTALLER}
    for node in (path,*path.parents):
        info=node.lstat()
        if info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise PermissionError('OWNER_LOADER_DENIED')
        sd=s.GetNamedSecurityInfo(str(node),s.SE_FILE_OBJECT,
            s.OWNER_SECURITY_INFORMATION|s.DACL_SECURITY_INFORMATION)
        is_private=private and node==path
        if s.ConvertSidToStringSid(sd.GetSecurityDescriptorOwner()) not in (trusted if is_private else standard):
            raise PermissionError('OWNER_LOADER_DENIED')
        acl=sd.GetSecurityDescriptorDacl()
        if acl is None: raise PermissionError('OWNER_LOADER_DENIED')
        for index in range(acl.GetAceCount()):
            ace=acl.GetAce(index)
            kind,flags=ace[0]
            if flags & 8: continue  # INHERIT_ONLY does not apply to this object.
            if kind==s.ACCESS_DENIED_ACE_TYPE: continue
            if kind!=s.ACCESS_ALLOWED_ACE_TYPE: raise PermissionError('OWNER_LOADER_DENIED')
            sid=s.ConvertSidToStringSid(ace[2])
            # Standard drive roots grant Authenticated Users create-subdirectory
            # (0x4). This permits siblings, NOT replacement of an existing child.
            # Accept only that bit at the drive anchor; delete-child, file writes,
            # generic write, ownership and ACL changes remain denied everywhere.
            mask=WRITE_MASK & ~0x4 if not is_private and node==Path(node.anchor) else WRITE_MASK
            if sid not in trusted and (is_private or ace[1]&mask):
                raise PermissionError('OWNER_LOADER_DENIED')
    return path


class LoadedOwner:
    """Holds enrolled pins and mandatory host callbacks; never accepts RPC paths."""
    def __init__(self, config, *, oauth_current, resolve_runtime):
        if type(config) is not OwnerConfiguration or not callable(oauth_current) or not callable(resolve_runtime):
            raise PermissionError('OWNER_LOADER_DENIED')
        self.config=config
        self._oauth_current=oauth_current
        self._resolve_runtime=resolve_runtime
        self._validate_config()
        self._initial=self._source()
        self._validate_source(self._initial)
        self.approval_key=Ed25519PublicKey.from_public_bytes(self._key('approval'))
        self.backup_key=X25519PublicKey.from_public_bytes(self._key('backup'))
        self.request_key=Ed25519PublicKey.from_public_bytes(self._key('request'))
        self.enrollment=a._enrollment_from_owner_loader(a._INTERNAL,
            placement=config.placement,actions=config.actions,key_id=config.key_id,
            approval_key=self.approval_key,backup_key=self.backup_key,
            capability_revision=config.capability_revision,current=self.current)

    def _validate_config(self):
        c=self.config
        if process_sid()!=c.service_sid: raise PermissionError('OWNER_LOADER_DENIED')
        # Validate SID syntax using Windows, not string prefix heuristics.
        import win32security as s
        for sid in (c.owner_sid,c.service_sid):
            if s.ConvertSidToStringSid(s.ConvertStringSidToSid(sid))!=sid:
                raise PermissionError('OWNER_LOADER_DENIED')
        if (set(c.placement)!=set(p.PLACEMENT) or not all(a._text(v) for v in c.placement.values())
            or type(c.actions) is not frozenset or not c.actions or not c.actions<= {'list','add','remove','replace','status'}
            or not all(a._text(v) for v in (c.key_id,c.request_key_id,c.capability_revision))):
            raise PermissionError('OWNER_LOADER_DENIED')
        root=_absolute(c.data_root)
        paths=[c.source_path,c.policy_path,c.profiles_path,c.journal_dir,c.replay_dir,
               c.approval_key_path,c.backup_key_path,c.request_key_path]
        if len({os.path.normcase(str(_absolute(v))) for v in paths})!=len(paths):
            raise PermissionError('OWNER_LOADER_DENIED')
        for item in (root,*paths):
            path=_absolute(item)
            if path!=root and root not in path.parents: raise PermissionError('OWNER_LOADER_DENIED')
            # Every DataRoot descendant (including candidate/journal parent) private.
            node=path
            while True:
                validate_private_path(node,owner_sid=c.owner_sid,service_sid=c.service_sid)
                if node==root: break
                node=node.parent
        if not all(Path(v).is_dir() for v in (root,c.journal_dir,c.replay_dir)):
            raise PermissionError('OWNER_LOADER_DENIED')
        for v in paths:
            if v not in (c.journal_dir,c.replay_dir) and not Path(v).is_file():
                raise PermissionError('OWNER_LOADER_DENIED')
        # The ACTUAL catalog must not expose private DataRoot through any Files root.
        doc=p.loads(self._read(c.profiles_path))
        for row in doc['profiles']:
            public=_absolute(row['root'])
            # A lexical sibling can be a junction into the private DataRoot.
            # Reject every reparse component before physical overlap comparison.
            for node in (public,*public.parents):
                if node.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                    raise PermissionError('OWNER_LOADER_DENIED')
            if not public.is_dir(): raise PermissionError('OWNER_LOADER_DENIED')
            physical_public=public.resolve(strict=True)
            physical_root=root.resolve(strict=True)
            if (physical_root==physical_public or physical_root in physical_public.parents
                or physical_public in physical_root.parents):
                raise PermissionError('OWNER_LOADER_DENIED')

    @staticmethod
    def _read(path):
        with Path(path).open('rb') as stream: raw=stream.read(262145)
        if len(raw)>262144: raise PermissionError('OWNER_LOADER_DENIED')
        return raw

    def _key(self,kind):
        c=self.config
        raw=self._read(getattr(c,kind+'_key_path'))
        pin=getattr(c,kind+'_key_sha256')
        if len(raw)!=32 or not isinstance(pin,str) or not re.fullmatch('[0-9a-f]{64}',pin) or p.sha(raw)!=pin:
            raise PermissionError('OWNER_LOADER_DENIED')
        return raw

    def _source(self): return p.loads(self._read(self.config.source_path))

    def _validate_source(self,source):
        c=self.config
        if (type(source) is not dict or set(source)!=SOURCE_FIELDS or type(source['version']) is not int
            or source['version']!=1 or source['capability']!=a.CAPABILITY or source['revoked'] is not False
            or type(source['expires_at']) is not int or not time.time()<source['expires_at']
            or source['placement']!=c.placement or type(source['actions']) is not list
            or len(source['actions'])!=len(c.actions) or set(source['actions'])!=c.actions
            or source['key_id']!=c.key_id or source['request_key_id']!=c.request_key_id
            or source['capability_revision']!=c.capability_revision):
            raise PermissionError('OWNER_LOADER_DENIED')

    def current_fields(self,fields):
        try:
            self._validate_config()
            source=self._source()
            self._validate_source(source)
            if source!=self._initial: return False
            for kind in ('approval','backup','request'): self._key(kind)
            if any(type(fields[k]) is not type(v) or fields[k]!=v for k,v in self.config.placement.items()): return False
            if fields['capability_revision']!=self.config.capability_revision: return False
            # Independent trusted host lookup: NEVER a callback supplied by request.
            if self._oauth_current(dict(fields)) is not True: return False
            actual=self._resolve_runtime(dict(fields))
            keys={'session_id','profile_generation','actor_user_id','chat_id','thread_id'}
            if type(actual) is not dict or set(actual)!=keys: return False
            return all(type(fields[k]) is type(actual[k]) and fields[k]==actual[k] for k in keys)
        except Exception:
            return False

    def current(self,context): return self.current_fields(context.fields)


def load_owner(config, *, oauth_current=None, resolve_runtime=None):
    """Explicit startup only. No default authority and no private state rewrite."""
    try: return LoadedOwner(config,oauth_current=oauth_current,resolve_runtime=resolve_runtime)
    except Exception: raise PermissionError('OWNER_LOADER_DENIED') from None
