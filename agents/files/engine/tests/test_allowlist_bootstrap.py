import copy
import importlib.util
import os
import time
import pytest
from app.allowlist import protocol as p


def test_bootstrap_public_bundle_planner_exists():
    assert importlib.util.find_spec('app.allowlist.bootstrap') is not None


def bundle():
    place=dict(principal_id='principal',workspace_id='workspace',device_id='device',installation_id='install',target_profile_id='agentRoot')
    keys={}
    for role,algorithm in [('approval','Ed25519'),('request','Ed25519'),('transport','X25519')]:
        raw=os.urandom(32);sha=p.sha(raw)
        keys[role]=dict(algorithm=algorithm,public_key=p.b64(raw),sha256=sha,key_id=role+'-'+sha)
    return dict(version=1,kind='zagent.allowlist.public-bootstrap.v1',placement=place,keys=keys)


def test_public_bundle_exact_pins_and_inert_plan():
    from app.allowlist.bootstrap import validate_bundle,plan,configuration
    b=bundle();raw=p.canonical(b)
    doc,keys=validate_bundle(raw,p.sha(raw),b['placement'])
    assert doc==b and len(set(keys.values()))==3
    out=plan(raw,acknowledged_sha256=p.sha(raw),placement=b['placement'],data_root=r'C:\OwnerData',
        policy_path=r'C:\OwnerData\files\config\remote_execution_policy.json',
        profiles_path=r'C:\OwnerData\files\config\profiles.json',owner_sid='S-1-5-21-1-2-3-1001',expires_at=int(time.time())+3600)
    assert set(out['files'])=={'owner.json','capability.json','approval.pub','request.pub','transport.pub'}
    assert out['directories']==['journal','replay']
    import base64
    decode=lambda s:base64.urlsafe_b64decode(s+'='*(-len(s)%4))
    manifest=p.loads(decode(out['files']['owner.json']))
    config=configuration(manifest)
    assert config.placement==b['placement']
    assert manifest['mutations_ready'] is False
    assert config.approval_key_sha256==b['keys']['approval']['sha256']
    assert config.backup_key_sha256==b['keys']['transport']['sha256']
    assert config.request_key_sha256==b['keys']['request']['sha256']
    assert not any('private' in name or 'backup' in name for name in out['files'])


@pytest.mark.parametrize('fault',['ack','placement','profile','private','role','algorithm','length','digest','keyid','duplicate-key','version','extra'])
def test_malformed_or_unacknowledged_bundle_denies(fault):
    from app.allowlist.bootstrap import validate_bundle
    b=bundle();place=copy.deepcopy(b['placement'])
    if fault=='placement':b['placement']['device_id']='foreign'
    elif fault=='profile':b['placement']['target_profile_id']='other';place=copy.deepcopy(b['placement'])
    elif fault=='private':b['keys']['request']['private_key']='NEVER_ACCEPT'
    elif fault=='role':b['keys']['backup']=b['keys'].pop('transport')
    elif fault=='algorithm':b['keys']['request']['algorithm']='X25519'
    elif fault=='length':b['keys']['request']['public_key']=p.b64(bytes(31))
    elif fault=='digest':b['keys']['request']['sha256']='0'*64
    elif fault=='keyid':b['keys']['request']['key_id']='unexpected'
    elif fault=='duplicate-key':
        other=b['keys']['approval'];b['keys']['request']=dict(other,key_id='request-'+other['sha256'])
    elif fault=='version':b['version']=True
    elif fault=='extra':b['token']='NEVER_ACCEPT'
    raw=p.canonical(b);ack='0'*64 if fault=='ack' else p.sha(raw)
    with pytest.raises((ValueError,PermissionError)):validate_bundle(raw,ack,place)


@pytest.mark.parametrize('fault',['expiry','private-path','endpoint','mutation-ready'])
def test_plan_and_loader_reject_expansion(fault):
    from app.allowlist.bootstrap import plan,configuration
    b=bundle();raw=p.canonical(b)
    args=dict(acknowledged_sha256=p.sha(raw),placement=b['placement'],data_root=r'C:\OwnerData',
        policy_path=r'C:\OwnerData\files\config\remote_execution_policy.json',
        profiles_path=r'C:\OwnerData\files\config\profiles.json',owner_sid='S-1-5-21-1-2-3-1001',expires_at=int(time.time())+3600)
    if fault=='expiry':args['expires_at']=True
    elif fault=='private-path':args['policy_path']=r'C:\Public\policy.json'
    elif fault=='endpoint':args['runtime_url']='https://evil.invalid/runtime'
    if fault!='mutation-ready':
        with pytest.raises((ValueError,PermissionError)):plan(raw,**args)
    else:
        out=plan(raw,**args)
        import base64
        v=out['files']['owner.json'];manifest=p.loads(base64.urlsafe_b64decode(v+'='*(-len(v)%4)))
        manifest['mutations_ready']=True
        with pytest.raises(PermissionError):configuration(manifest)
