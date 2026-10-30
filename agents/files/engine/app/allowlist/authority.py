"""Dedicated owner-loaded authority. Ordinary execution metadata is never authority.

Only the authenticated management adapter calls the underscored constructors;
no owner enrollment, key generation or environment opt-in occurs on import.
"""
from dataclasses import dataclass
from types import MappingProxyType
import math
import time
from app.core.execution_context import TrustedMetadata
from . import protocol as p

CAPABILITY = "executable_allowlist_management"
META = "zagent.executable_allowlist_management_context"
_INTERNAL = object()
FIELDS = set(p.PLACEMENT) | {"capability_revision", "profile_generation", "session_id",
    "actor_user_id", "chat_id", "thread_id", "deadline"}

@dataclass(frozen=True)
class _Enrollment:
    placement: object
    actions: frozenset
    key_id: str
    approval_key: object
    backup_key: object
    capability_revision: str
    current: object
    marker: object

@dataclass(frozen=True)
class _Context:
    fields: object
    enrollment: object


def _enrollment_from_owner_loader(marker, *, placement, actions, key_id, approval_key,
                                  backup_key, capability_revision, current,
                                  capability=CAPABILITY):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey
    if marker is not _INTERNAL or capability != CAPABILITY:
        raise PermissionError("DEDICATED_OWNER_ENROLLMENT_REQUIRED")
    if (set(placement) != set(p.PLACEMENT) or not all(_text(v) for v in placement.values())
        or not isinstance(actions,frozenset) or not actions or not actions <= {"list","add","replace","remove","status"}
        or not _text(key_id) or not _text(capability_revision) or not callable(current)
        or not isinstance(approval_key,Ed25519PublicKey) or not isinstance(backup_key,X25519PublicKey)):
        raise PermissionError("INVALID_ALLOWLIST_ENROLLMENT")
    return _Enrollment(MappingProxyType(dict(placement)),actions,key_id,approval_key,
                       backup_key,capability_revision,current,object())


def _text(v):
    return isinstance(v,str) and 0 < len(v) <= 256 and not any(ord(c)<32 or ord(c)==127 for c in v)


def _context_from_enrolled_adapter(enrollment, metadata):
    if type(enrollment) is not _Enrollment or type(metadata) is not TrustedMetadata:
        raise PermissionError("AUTHENTICATED_MANAGEMENT_CHANNEL_REQUIRED")
    f=metadata.get(META)
    if not isinstance(f,dict) or set(f)!=FIELDS:
        raise PermissionError("INVALID_MANAGEMENT_CONTEXT")
    f=p.loads(p.canonical(f))
    if any(f[k]!=v or type(f[k]) is not type(v) for k,v in enrollment.placement.items()):
        raise PermissionError("MANAGEMENT_PLACEMENT_MISMATCH")
    if f["capability_revision"]!=enrollment.capability_revision:
        raise PermissionError("CAPABILITY_REVISION_MISMATCH")
    if not _text(f["session_id"]) or not _text(f["profile_generation"]):
        raise PermissionError("REAL_SESSION_AND_GENERATION_REQUIRED")
    for key in ("actor_user_id","chat_id","thread_id"):
        if not (_text(f[key]) or type(f[key]) is int):
            raise PermissionError("INVALID_CHAT_BINDING")
    ctx=_Context(MappingProxyType(f),enrollment)
    authorize(enrollment,ctx,None)
    return ctx


def authorize(enrollment, context, action):
    if (type(enrollment) is not _Enrollment or type(context) is not _Context
        or context.enrollment is not enrollment):
        raise PermissionError("DEDICATED_ALLOWLIST_AUTHORITY_REQUIRED")
    f=context.fields
    expiry=f["deadline"]
    if (type(expiry) not in (int,float) or not math.isfinite(expiry)
        or not time.time()<expiry<=time.time()+3600):
        raise PermissionError("MANAGEMENT_CONTEXT_EXPIRED")
    if action is not None and action not in enrollment.actions:
        raise PermissionError("ALLOWLIST_ACTION_NOT_ENROLLED")
    # Callback must re-read the *dedicated* capability and current owner enrollment,
    # including revocation/placement. Truthy objects are not authentication.
    if enrollment.current(context) is not True:
        raise PermissionError("ALLOWLIST_CAPABILITY_REVOKED")
    return f
