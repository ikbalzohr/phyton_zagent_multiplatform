"""Closed canonical protocol; no keys are generated or enrolled here."""
import base64
import hashlib
import json
import re

APPROVAL = "zagent.allowlist.approval.v1"
BACKUP = "zagent.allowlist.backup-receipt.v1"
PLACEMENT = ("principal_id","workspace_id","device_id","installation_id","target_profile_id")
METADATA = ("challenge_id","operation_id","expected_revision","payload_sha256") + PLACEMENT


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out: raise ValueError("DUPLICATE_KEY")
        out[key] = value
    return out


def loads(raw):
    if len(raw) > 524288: raise ValueError("DOCUMENT_TOO_LARGE")
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("NONFINITE_JSON")))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()

APPROVAL_FIELDS = set(METADATA) | {"approval_id","grant_id","idempotency_key","profile_generation","session_id","action","nonce","iat","exp","audience","choice","rule_digest","actor_user_id","chat_id","thread_id"}
BACKUP_FIELDS = set(METADATA) | {"backup_id","backup_digest","iat","exp","retention_until"}


def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def unb64(text, length=None):
    if not isinstance(text,str) or not re.fullmatch(r"[A-Za-z0-9_-]+",text):
        raise ValueError("INVALID_BASE64URL")
    raw = base64.b64decode(text + "="*((-len(text))%4),altchars=b"-_",validate=True)
    if b64(raw) != text or (length is not None and len(raw) != length):
        raise ValueError("INVALID_BASE64URL_LENGTH")
    return raw


def verify(receipt, kind, key_id, public_key, expected, now):
    from cryptography.exceptions import InvalidSignature
    if isinstance(receipt,(str,bytes)): receipt = loads(receipt)
    if not isinstance(receipt,dict) or set(receipt) != {"version","kind","key_id","body","signature"}:
        raise ValueError("INVALID_RECEIPT_ENVELOPE")
    if type(receipt["version"]) is not int or receipt["version"] != 1 or receipt["kind"] != kind or receipt["key_id"] != key_id:
        raise PermissionError("RECEIPT_AUTHORITY_MISMATCH")
    if kind not in (APPROVAL,BACKUP): raise ValueError("INVALID_RECEIPT_KIND")
    signed = {k:v for k,v in receipt.items() if k != "signature"}
    try: public_key.verify(unb64(receipt["signature"],64),canonical(signed))
    except InvalidSignature as exc: raise PermissionError("INVALID_SIGNATURE") from exc
    body = receipt["body"]
    if not isinstance(body,dict) or set(body) != (APPROVAL_FIELDS if kind == APPROVAL else BACKUP_FIELDS):
        raise ValueError("INVALID_RECEIPT_BODY")
    if any(type(body.get(k)) is not type(v) or body.get(k) != v for k,v in expected.items()):
        raise PermissionError("RECEIPT_BINDING_MISMATCH")
    if any(type(body[k]) is not int for k in ("iat","exp")) or not body["iat"] <= now < body["exp"] <= body["iat"] + 300:
        raise PermissionError("RECEIPT_EXPIRED_OR_FUTURE")
    for k in ("challenge_id","operation_id") + (("approval_id","grant_id") if kind == APPROVAL else ("backup_id",)):
        if not isinstance(body[k],str) or not re.fullmatch(r"[0-9a-f]{32}",body[k]): raise ValueError("INVALID_UUID")
    for k in ("expected_revision","payload_sha256") + (("rule_digest",) if kind == APPROVAL else ("backup_digest",)):
        if not isinstance(body[k],str) or not re.fullmatch(r"[0-9a-f]{64}",body[k]): raise ValueError("INVALID_SHA256")
    if kind == APPROVAL:
        if body["audience"] != "zagent.allowlist.admin" or body["choice"] not in ("once","session","always") or body["action"] not in ("add","replace","remove"):
            raise PermissionError("INVALID_APPROVAL")
        if not isinstance(body["idempotency_key"],str) or not 1 <= len(body["idempotency_key"]) <= 128: raise ValueError("INVALID_IDEMPOTENCY_KEY")
        unb64(body["nonce"],32)
    elif type(body["retention_until"]) is not int or body["retention_until"] < body["iat"] + 30*86400:
        raise PermissionError("INSUFFICIENT_BACKUP_RETENTION")
    return body


def seal(raw, public_key, metadata):
    import os
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if set(metadata) != set(METADATA): raise ValueError("INVALID_BACKUP_METADATA")
    ephemeral = X25519PrivateKey.generate()
    aad = canonical(metadata)
    key = HKDF(algorithm=hashes.SHA256(),length=32,salt=hashlib.sha256(aad).digest(),info=b"zagent.allowlist.backup.v1").derive(ephemeral.exchange(public_key))
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce,raw,aad)
    return dict(version=1,algorithm="X25519-HKDF-SHA256-AES256GCM",ephemeral_public_key=b64(ephemeral.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)),nonce=b64(nonce),ciphertext=b64(ciphertext),metadata=metadata)
