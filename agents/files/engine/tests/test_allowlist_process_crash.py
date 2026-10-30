"""Abrupt Windows process-termination fixtures; synthetic temp policies only.

These are not power-loss tests. A checkpoint pauses a real approved Python
child; its parent uses TerminateProcess, so finally blocks do not run.
"""
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from app.allowlist import authority as a
from app.allowlist import protocol as p
from app.allowlist.engine import AllowlistEngine
from app.core.execution_context import TrustedMetadata
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey


CHILD = r"""
import json,os,sys,threading
from pathlib import Path
sys.path.insert(0,os.getcwd())
sys.path.insert(0,str(Path.cwd()/'tests'))
from test_allowlist_engine import env, sync, prepare_add, receipts
from app.allowlist import engine as module
from app.allowlist import protocol as p
from cryptography.hazmat.primitives import serialization
root=Path(sys.argv[1]); phase=sys.argv[2]
e=env.__wrapped__(root)
prepared=prepare_add(e)
op=prepared.challenge['operation_id']
info=dict(fields=e['fields'],operation_id=op,policy_path=str(e['policy_path']),
          profiles_path=str(e['profiles_path']),journal_dir=str(root/'journal'),
          old_sha256=prepared.challenge['expected_revision'],
          signing_public=p.b64(e['ed'].public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)),
          transport_public=p.b64(e['x'].public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)))
(root/'fixture-info.json').write_bytes(p.canonical(info))
journal=root/'journal'/(op+'.json')
real_replace=module.os.replace

def stop():
    (root/'checkpoint.ready').write_text(phase,encoding='utf-8')
    threading.Event().wait(60)
    raise RuntimeError('parent failed to terminate checkpoint child')

def replace(source,destination):
    destination=Path(destination)
    if destination==e['policy_path'] and phase=='before-policy-replace':stop()
    if destination==journal and phase=='before-intent-replace':
        if p.loads(Path(source).read_bytes())['state']=='committing':stop()
    real_replace(source,destination)
    if destination==e['policy_path'] and phase=='after-policy-replace':stop()
    if destination==journal and phase=='after-final-journal-replace':
        if p.loads(destination.read_bytes())['state']=='applied':stop()

module.os.replace=replace
sync(e['engine'].commit(e['context'],op,*receipts(e,prepared)))
raise AssertionError('checkpoint was not reached')
"""


def killed_fixture(tmp_path,phase):
    root=tmp_path/'child-fixture'
    root.mkdir()
    child=subprocess.Popen([sys.executable,'-c',CHILD,str(root),phase],
                           stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True)
    try:
        deadline=time.monotonic()+15
        ready=root/'checkpoint.ready'
        while not ready.exists() and child.poll() is None and time.monotonic()<deadline:
            time.sleep(0.01)
        assert ready.exists(), 'child did not reach bounded synthetic checkpoint'
        assert ready.read_text(encoding='utf-8')==phase
        assert child.poll() is None
        child.kill()  # Windows TerminateProcess: no Python finally or cleanup.
        _,stderr=child.communicate(timeout=5)
        assert child.returncode!=0
        assert not stderr
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)
    info=json.loads((root/'fixture-info.json').read_text(encoding='utf-8'))
    fields=info['fields']
    enrollment=a._enrollment_from_owner_loader(a._INTERNAL,
        placement={k:fields[k] for k in p.PLACEMENT},
        actions=frozenset({'list','add','replace','remove','status'}),key_id='test-key',
        approval_key=Ed25519PublicKey.from_public_bytes(p.unb64(info['signing_public'],32)),
        backup_key=X25519PublicKey.from_public_bytes(p.unb64(info['transport_public'],32)),
        capability_revision='cap-1',current=lambda _:True)
    context=a._context_from_enrolled_adapter(enrollment,TrustedMetadata({a.META:fields}))
    engine=AllowlistEngine(info['policy_path'],info['profiles_path'],info['journal_dir'],enrollment=enrollment)
    return info,engine,context


@pytest.mark.parametrize('phase,expected',[
    ('before-intent-replace','pending'),
    ('before-policy-replace','failed'),
    ('after-policy-replace','applied'),
    ('after-final-journal-replace','applied'),
])
def test_real_process_kill_recovers_exact_operation(tmp_path,phase,expected):
    import asyncio
    info,engine,context=killed_fixture(tmp_path,phase)
    operation=info['operation_id']
    record=p.loads((Path(info['journal_dir'])/(operation+'.json')).read_bytes())
    current=p.sha(Path(info['policy_path']).read_bytes())
    candidate=record['candidate_sha256']
    assert current==(candidate if expected=='applied' else info['old_sha256'])
    assert not engine._pending
    result=asyncio.run(engine.operation(context,operation))
    assert result['status']==expected
    assert asyncio.run(engine.operation(context,operation))==result
    if expected=='pending':
        # A dead process's in-memory candidate cannot be silently reconstructed.
        expired=asyncio.run(engine.commit(context,operation,None,None))
        assert expired['status']=='expired'
        assert p.sha(Path(info['policy_path']).read_bytes())==info['old_sha256']
    retained=list(Path(info['policy_path']).parent.glob('*.candidate-*'))
    assert bool(retained)==(phase=='before-policy-replace')
    for path in retained:
        assert path.stat().st_size<=262144
        assert p.sha(path.read_bytes())==candidate


def test_killed_writer_unknown_revision_stays_uncertain_and_blocks_new_prepare(tmp_path):
    import asyncio
    info,engine,context=killed_fixture(tmp_path,'before-policy-replace')
    path=Path(info['policy_path'])
    policy=p.loads(path.read_bytes())
    policy['max_timeout_seconds']+=1
    path.write_bytes(p.canonical(policy))  # synthetic noncooperating writer only
    changed=path.read_bytes()
    result=asyncio.run(engine.operation(context,info['operation_id']))
    assert result['status']=='uncertain'
    payload=dict(action='remove',target_profile_id='fixture',executable=policy['allowed_executables'][0])
    with pytest.raises(PermissionError,match='UNRESOLVED_POLICY_PUBLICATION'):
        asyncio.run(engine.prepare(context,payload))
    assert path.read_bytes()==changed
