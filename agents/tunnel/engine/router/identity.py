"""Installation placement comes from the Core-owned process environment only."""
from __future__ import annotations

import hmac
import os
from dataclasses import dataclass
from .access import AuthorizationError


@dataclass(frozen=True)
class Placement:
    device_id: str
    installation_id: str

    def validate(self, target: str = "") -> None:
        if not self.device_id or not self.installation_id:
            raise AuthorizationError("INSTALLATION_NOT_CONFIGURED", 503)
        if target and target != self.device_id:
            raise AuthorizationError("IDENTITY_MISMATCH", 403)


def internal_token() -> str:
    value = os.environ.get("ZAGENT_INTERNAL_TOKEN", "")
    if len(value) < 32 or any(ch.isspace() for ch in value):
        raise AuthorizationError("INTERNAL_CHANNEL_NOT_CONFIGURED", 503)
    return value


def verify_internal_token(value: str) -> None:
    if not hmac.compare_digest(value, internal_token()):
        raise AuthorizationError("INTERNAL_ACCESS_DENIED", 403)
