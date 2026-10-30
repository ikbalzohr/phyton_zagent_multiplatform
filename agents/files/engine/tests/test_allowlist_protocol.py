"""Synthetic cryptographic fixtures only; no enrollment or live policy access."""
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from app.allowlist import protocol as p


def test_canonical_and_duplicate_keys():
    assert p.canonical({"z":1,"a":"é"}) == '{"a":"é","z":1}'.encode()
    with pytest.raises(ValueError): p.loads('{"a":1,"a":2}')
    with pytest.raises(ValueError): p.loads('{"a":NaN}')
    with pytest.raises(ValueError): p.canonical({"a":float("nan")})

def sign(key, kind, body, kid="enrolled"):
    wrapper = dict(version=1, kind=kind, key_id=kid, body=body)
    return dict(wrapper, signature=p.b64(key.sign(p.canonical(wrapper))))


def approval_body():
    body = {k:"fixture" for k in p.PLACEMENT}
    body.update(challenge_id="a"*32, operation_id="b"*32, approval_id="c"*32,
                grant_id="d"*32, idempotency_key="one", profile_generation="generation",
                session_id="real-broker-session", action="add", payload_sha256="0"*64,
                expected_revision="1"*64, nonce=p.b64(bytes(32)), iat=1000, exp=1200,
                audience="zagent.allowlist.admin", choice="once", rule_digest="2"*64,
                actor_user_id="owner", chat_id="chat", thread_id="topic")
    return body


def test_signed_closed_receipt_and_all_bindings():
    key = Ed25519PrivateKey.generate()
    body = approval_body()
    expected = {k:v for k,v in body.items() if k not in ("iat","exp","approval_id","grant_id","choice")}
    receipt = sign(key,p.APPROVAL,body)
    assert p.verify(receipt,p.APPROVAL,"enrolled",key.public_key(),expected,1100) == body
    for field in expected:
        bad = dict(body, **{field:"tampered"})
        with pytest.raises((ValueError,PermissionError)):
            p.verify(sign(key,p.APPROVAL,bad),p.APPROVAL,"enrolled",key.public_key(),expected,1100)
    for bad in (dict(receipt, kind=p.BACKUP),dict(receipt,key_id="foreign"),dict(receipt,extra=1),dict(receipt,signature=p.b64(bytes(64)))):
        with pytest.raises((ValueError,PermissionError)):
            p.verify(bad,p.APPROVAL,"enrolled",key.public_key(),expected,1100)
    for iat,exp,now in [(1101,1200,1100),(1000,1301,1100),(1000,1100,1100),(True,1200,1100)]:
        with pytest.raises((ValueError,PermissionError)):
            p.verify(sign(key,p.APPROVAL,dict(body,iat=iat,exp=exp)),p.APPROVAL,"enrolled",key.public_key(),expected,now)


def test_sealed_preimage_round_trip_and_metadata_authentication():
    key = X25519PrivateKey.generate()
    metadata = {k:"fixture" for k in p.METADATA}
    raw = b"private synthetic policy"
    sealed = p.seal(raw,key.public_key(),metadata)
    assert raw not in p.canonical(sealed)
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
    shared = key.exchange(X25519PublicKey.from_public_bytes(p.unb64(sealed["ephemeral_public_key"],32)))
    aeskey = HKDF(algorithm=hashes.SHA256(),length=32,salt=bytes.fromhex(p.sha(p.canonical(metadata))),info=b"zagent.allowlist.backup.v1").derive(shared)
    aes = AESGCM(aeskey)
    assert aes.decrypt(p.unb64(sealed["nonce"],12),p.unb64(sealed["ciphertext"]),p.canonical(metadata)) == raw
    from cryptography.exceptions import InvalidTag
    with pytest.raises(InvalidTag):
        aes.decrypt(p.unb64(sealed["nonce"],12),p.unb64(sealed["ciphertext"]),p.canonical(dict(metadata,operation_id="changed")))
