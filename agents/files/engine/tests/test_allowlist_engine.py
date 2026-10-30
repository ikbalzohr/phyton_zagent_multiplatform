"""Windows temp-only tests. Never locate or open the installed DataRoot."""
import asyncio
import copy
import json
import time
import uuid
from pathlib import Path
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from app.core.execution_context import TrustedMetadata, VerifiedContext
from app.allowlist import protocol as p
from app.allowlist import authority as a
from app.allowlist.engine import AllowlistEngine


def sync(coro): return asyncio.run(coro)


def sign(key, kind, body):
    wrapper = dict(version=1,kind=kind,key_id="test-key",body=body)
    return dict(wrapper,signature=p.b64(key.sign(p.canonical(wrapper))))


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    paths = []
    for name in ("first.exe","second.exe","third.exe"):
        path = root / name
        path.write_bytes(b"synthetic test executable, never executed")
        paths.append(str(path))
    row = dict(name="fixture",root=str(root),enabled=True,authorized_by_user=True,mode="read-write")
    profiles = dict(schema_version=1,active_profile="fixture",profiles=[row])
    from app.profiles.administration import profile_generation
    generation = profile_generation(row,profiles)
    policy = dict(version=1,enabled=True,execution_mode="owner-account",acknowledge_host_access=True,
                  profile_id="fixture",root=str(root),allowed_tools=["files_exec_command"],
                  allowed_executables=paths[:2],max_timeout_seconds=30,max_output_chars=1000)
    config = tmp_path / "config"
    config.mkdir()
    policy_path = config / "policy.json"
    policy_path.write_bytes(p.canonical(policy)+b"\n")
    profiles_path = config / "profiles.json"
    profiles_path.write_bytes(p.canonical(profiles))
    ed = Ed25519PrivateKey.generate()
    x = X25519PrivateKey.generate()
    placement = {k:"fixture" for k in p.PLACEMENT}
    fresh = {"valid":True}
    enrollment = a._enrollment_from_owner_loader(a._INTERNAL, placement=placement,
        actions=frozenset({"list","add","replace","remove","status"}),key_id="test-key",
        approval_key=ed.public_key(),backup_key=x.public_key(),capability_revision="cap-1",
        current=lambda _:fresh["valid"])
    fields = dict(placement,capability_revision="cap-1",profile_generation=generation,
        session_id="broker-session-random",actor_user_id="owner",chat_id="chat",thread_id="topic",
        deadline=time.time()+240)
    metadata = TrustedMetadata({a.META:fields})
    context = a._context_from_enrolled_adapter(enrollment,metadata)
    engine = AllowlistEngine(policy_path,profiles_path,tmp_path/"journal",enrollment=enrollment)
    return dict(engine=engine,context=context,metadata=metadata,fields=fields,enrollment=enrollment,
                fresh=fresh,policy=policy,policy_path=policy_path,profiles_path=profiles_path,
                paths=paths,ed=ed,x=x,tmp=tmp_path)


def test_default_disabled_and_no_argument_authority(env):
    e=env
    disabled=AllowlistEngine(e["policy_path"],e["profiles_path"],e["tmp"]/"disabled")
    with pytest.raises(PermissionError): sync(disabled.list(e["context"]))
    for bad in (True,e["fields"],VerifiedContext(e["fields"]),e["metadata"]):
        with pytest.raises(PermissionError): sync(e["engine"].list(bad))
    with pytest.raises(PermissionError): a._context_from_enrolled_adapter(e["enrollment"],dict(e["metadata"]))
    e["fresh"]["valid"]=False
    with pytest.raises(PermissionError): sync(e["engine"].list(e["context"]))


def test_list_and_prepare_do_not_mutate_policy(env):
    e=env
    before=e["policy_path"].read_bytes()
    listed=sync(e["engine"].list(e["context"]))
    assert listed["allowed_executables"] == e["paths"][:2]
    payload=dict(action="add",target_profile_id="fixture",executable=e["paths"][2])
    prepared=sync(e["engine"].prepare(e["context"],payload,p.sha(before),"key-one"))
    assert prepared.challenge["payload_sha256"] == p.sha(p.canonical(payload))
    assert prepared.sealed_preimage["metadata"]["expected_revision"] == p.sha(before)
    assert e["policy_path"].read_bytes() == before
    assert before not in p.canonical(prepared.sealed_preimage)
    for path in (e["tmp"]/"journal").glob("*"):
        assert before not in path.read_bytes()


def receipts(e, prepared):
    c=prepared.challenge
    now=int(time.time())
    meta={k:c[k] for k in p.METADATA}
    payload=prepared.payload
    identity={k:c[k] for k in p.PLACEMENT}
    rule=p.sha(p.canonical(dict(identity,action=payload["action"],payload=payload)))
    approval=dict(meta,approval_id=uuid.uuid4().hex,grant_id=uuid.uuid4().hex,
        idempotency_key=c["operation_id"],profile_generation=c["profile_generation"],
        session_id=c["session_id"],action=c["action"],nonce=c["nonce"],iat=now,exp=now+100,
        audience="zagent.allowlist.admin",choice="once",rule_digest=rule,
        actor_user_id="owner",chat_id="chat",thread_id="topic")
    backup=dict(meta,backup_id=uuid.uuid4().hex,backup_digest=c["expected_revision"],
        iat=now,exp=now+100,retention_until=now+30*86400)
    return sign(e["ed"],p.APPROVAL,approval),sign(e["ed"],p.BACKUP,backup)


def prepare_add(e,key="add"):
    return sync(e["engine"].prepare(e["context"],dict(action="add",target_profile_id="fixture",
        executable=e["paths"][2]),p.sha(e["policy_path"].read_bytes()),key))


def test_commit_requires_signed_backup_then_exactly_once_readback(env):
    e=env
    prepared=prepare_add(e)
    approval,backup=receipts(e,prepared)
    before=e["policy_path"].read_bytes()
    with pytest.raises((ValueError,PermissionError)):
        sync(e["engine"].commit(e["context"],prepared.challenge["operation_id"],approval,{}))
    assert e["policy_path"].read_bytes()==before
    result=sync(e["engine"].commit(e["context"],prepared.challenge["operation_id"],approval,backup))
    assert result["status"]=="applied"
    assert p.loads(e["policy_path"].read_bytes())["allowed_executables"]==e["paths"]
    assert sync(e["engine"].operation(e["context"],prepared.challenge["operation_id"]))==result
    assert sync(e["engine"].commit(e["context"],prepared.challenge["operation_id"],approval,backup))==result
    from app.mcp.managed_commands import _policy_profiles
    assert _policy_profiles(p.loads(e["policy_path"].read_bytes()))["fixture"]["allowed_tools"]==["files_exec_command"]
