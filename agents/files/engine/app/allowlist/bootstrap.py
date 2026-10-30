"""Pure public-only bootstrap planner. No key generation, configuration reads or writes."""
import time
import uuid
from pathlib import Path
from . import protocol as p, authority as a
from .owner_loader import OwnerConfiguration

BUNDLE_KIND='zagent.allowlist.public-bootstrap.v1'
MANIFEST_KIND='zagent.allowlist.owner-host.v1'
RUNTIME_URL='https://zagent.ikbalzohr.web.id/runtime/allowlist-context'
ROUTER_URL='http://127.0.0.1:18810'


def validate_bundle(raw, acknowledged_sha256, placement):
    if type(raw) is not bytes or len(raw)>16384 or p.sha(raw)!=acknowledged_sha256:
        raise ValueError('BOOTSTRAP_BUNDLE_ACKNOWLEDGEMENT_REQUIRED')
    doc=p.loads(raw)
    if (type(doc) is not dict or set(doc)!={'version','kind','placement','keys'}
        or type(doc['version']) is not int or doc['version']!=1 or doc['kind']!=BUNDLE_KIND
        or type(placement) is not dict or set(placement)!=set(p.PLACEMENT)
        or not all(type(v) is str and v and v==v.strip() for v in placement.values())
        or doc['placement']!=placement or placement['target_profile_id']!='agentRoot'
        or type(doc['keys']) is not dict or set(doc['keys'])!={'approval','request','transport'}):
        raise ValueError('BOOTSTRAP_BUNDLE_INVALID')
    keys={}
    for role,algorithm in [('approval','Ed25519'),('request','Ed25519'),('transport','X25519')]:
        item=doc['keys'][role]
        if type(item) is not dict or set(item)!={'algorithm','public_key','sha256','key_id'}:
            raise ValueError('BOOTSTRAP_BUNDLE_INVALID')
        key=p.unb64(item['public_key'],32)
        if item['algorithm']!=algorithm or item['sha256']!=p.sha(key) or item['key_id']!=role+'-'+p.sha(key):
            raise ValueError('BOOTSTRAP_BUNDLE_INVALID')
        keys[role]=key
    if len(set(keys.values()))!=3:raise ValueError('BOOTSTRAP_DISTINCT_KEYS_REQUIRED')
    return doc,keys


def plan(raw, *, acknowledged_sha256, placement, data_root, policy_path, profiles_path,
         owner_sid, expires_at, router_url=ROUTER_URL, runtime_url=RUNTIME_URL):
    """Inputs are trusted owner-local facts; never invoke as remote authority."""
    doc,keys=validate_bundle(raw,acknowledged_sha256,placement)
    now=time.time()
    if type(expires_at) is not int or not now<expires_at<=now+366*86400:
        raise ValueError('BOOTSTRAP_FINITE_EXPIRY_REQUIRED')
    if router_url!=ROUTER_URL or runtime_url!=RUNTIME_URL:raise ValueError('BOOTSTRAP_ENDPOINT_DENIED')
    from .owner_loader import _absolute
    data_root=_absolute(data_root)
    for path in (policy_path,profiles_path):
        if data_root not in _absolute(path).parents:raise ValueError('BOOTSTRAP_PRIVATE_PATH_REQUIRED')
    if type(owner_sid) is not str or not owner_sid.startswith('S-1-5-21-'):raise ValueError('BOOTSTRAP_OWNER_REQUIRED')
    folder=data_root/'allowlist'
    source=dict(version=1,capability=a.CAPABILITY,placement=dict(placement),
        actions=['add','list','remove','replace','status'],key_id=doc['keys']['approval']['key_id'],
        request_key_id=doc['keys']['request']['key_id'],capability_revision='allowlist-'+uuid.uuid4().hex,
        expires_at=expires_at,revoked=False)
    config=dict(data_root=str(data_root),source_path=str(folder/'capability.json'),policy_path=str(policy_path),
        profiles_path=str(profiles_path),journal_dir=str(folder/'journal'),replay_dir=str(folder/'replay'),
        approval_key_path=str(folder/'approval.pub'),backup_key_path=str(folder/'transport.pub'),
        request_key_path=str(folder/'request.pub'),owner_sid=owner_sid,service_sid=owner_sid,
        placement=dict(placement),actions=source['actions'],key_id=source['key_id'],request_key_id=source['request_key_id'],
        capability_revision=source['capability_revision'],approval_key_sha256=p.sha(keys['approval']),
        backup_key_sha256=p.sha(keys['transport']),request_key_sha256=p.sha(keys['request']))
    manifest=dict(version=1,kind=MANIFEST_KIND,configuration=config,router_url=router_url,runtime_url=runtime_url,
                  mutations_ready=False,bundle_sha256=p.sha(raw))
    files={'capability.json':p.canonical(source),'owner.json':p.canonical(manifest),
           'approval.pub':keys['approval'],'transport.pub':keys['transport'],'request.pub':keys['request']}
    return {'files':{name:p.b64(value) for name,value in files.items()},'directories':['journal','replay'],
            'bundle_sha256':p.sha(raw),'capability_revision':source['capability_revision']}


def configuration(manifest):
    if (type(manifest) is not dict or set(manifest)!={'version','kind','configuration','router_url','runtime_url',
            'mutations_ready','bundle_sha256'} or type(manifest['version']) is not int or manifest['version']!=1
        or manifest['kind']!=MANIFEST_KIND or manifest['mutations_ready'] is not False
        or manifest['router_url']!=ROUTER_URL or manifest['runtime_url']!=RUNTIME_URL):
        raise PermissionError('ALLOWLIST_HOST_DISABLED')
    c=dict(manifest['configuration'])
    if set(c)!=set(OwnerConfiguration.__dataclass_fields__):raise PermissionError('ALLOWLIST_HOST_DISABLED')
    for k in ('data_root','source_path','policy_path','profiles_path','journal_dir','replay_dir',
              'approval_key_path','backup_key_path','request_key_path'):c[k]=Path(c[k])
    c['actions']=frozenset(c['actions'])
    return OwnerConfiguration(**c)


if __name__=='__main__':
    # Pure plan CLI for the reviewed interactive PowerShell owner helper only.
    # No private grants read, no installed writes, no private key generation.
    import sys,json
    inputs=p.loads(sys.stdin.buffer.read(65537))
    encoded=inputs.pop('bundle')
    import base64
    raw=base64.b64decode(encoded,validate=True)
    print(json.dumps(plan(raw,**inputs),sort_keys=True,separators=(',',':')))
