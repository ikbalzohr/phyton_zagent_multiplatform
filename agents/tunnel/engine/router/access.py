"""OAuth protected resource, not an authorization server.

RFC 7662 introspection uses httpx TLS validation and HTTP Basic client auth.
No bearer, client label, transport session or model metadata can provision grants.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from .diagnostic_events import record, traced


class AuthorizationError(ValueError):
    def __init__(self, code: str, status: int = 403, scope: str = ""):
        super().__init__(code)
        self.code, self.status, self.scope = code, status, scope


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def principal_id(issuer: str, subject: str) -> str:
    return "principal_v1_" + digest([issuer, subject])


def owner_key(principal: str, workspace: str) -> str:
    # Kept in existing journal session columns; never a protocol/chat identifier.
    return "owner_v1_" + digest([principal, workspace])


def secure_url(value: Any) -> bool:
    try:
        url = urlsplit(str(value))
        return bool(url.scheme == "https" and url.hostname and not url.username
                    and not url.password and not url.fragment and not url.query)
    except ValueError:
        return False


@dataclass(frozen=True)
class AuthContext:
    principal_id: str
    workspace_id: str
    scopes: frozenset[str]
    tools: frozenset[str]
    policy_revision: str
    expires_at: float

    @property
    def owner(self) -> str:
        return owner_key(self.principal_id, self.workspace_id)

    def require(self, scope: str, tool: str = "") -> None:
        if self.expires_at <= time.time():
            raise AuthorizationError("invalid_token", 401)
        if scope not in self.scopes or (tool and tool not in self.tools):
            raise AuthorizationError("insufficient_scope", 403, scope)

    def public(self) -> dict[str, Any]:
        return {"principal_id": self.principal_id, "workspace_id": self.workspace_id,
                "scopes": sorted(self.scopes), "policy_revision": self.policy_revision,
                "expires_at": self.expires_at}


class ResourceAuthorizer:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    @property
    def configured(self) -> bool:
        c = self.config
        return bool(all(secure_url(c.get(k)) for k in
                        ("resource_uri", "issuer", "introspection_endpoint"))
                    and c.get("workspace_id") and c.get("policy_revision")
                    and c.get("introspection_client_id") and c.get("introspection_secret_env")
                    and c.get("authorization_servers")
                    and all(secure_url(u) for u in c["authorization_servers"]))

    def metadata(self) -> dict[str, Any]:
        if not self.configured:
            raise AuthorizationError("NOT_CONFIGURED", 503)
        return {"resource": self.config["resource_uri"],
                "authorization_servers": self.config["authorization_servers"],
                "bearer_methods_supported": ["header"],
                "scopes_supported": sorted(set(self.config.get("scopes_supported", [])))}

    @traced('auth.current_grant', 'AUTH_NOT_AUTHORIZED')
    def current_grant(self, auth: AuthContext) -> dict[str, Any]:
        c = self.config
        grant = (c.get("grants") or {}).get(auth.principal_id)
        if (not isinstance(grant, dict) or grant.get("revoked") is True
                or c.get("workspace_id") != auth.workspace_id
                or str(c.get("policy_revision")) != auth.policy_revision):
            raise AuthorizationError("grant_revoked", 403)
        if grant.get("expires_at") is not None and float(grant["expires_at"]) <= time.time():
            raise AuthorizationError("grant_revoked", 403)
        return grant

    @traced('auth.token', 'AUTH_INVALID_TOKEN')
    async def authenticate(self, authorization: str, client: httpx.AsyncClient) -> AuthContext:
        if not self.configured:
            record('auth.configuration', 'ROUTER_CONFIGURATION_ERROR')
            raise AuthorizationError("NOT_CONFIGURED", 503)
        scheme, separator, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not separator or not token or len(token) > 8192 or any(ch.isspace() for ch in token):
            record('auth.token_header', 'AUTH_REQUIRED' if not authorization else 'AUTH_INVALID_TOKEN')
            raise AuthorizationError("invalid_token", 401)
        c = self.config
        secret = os.environ.get(c["introspection_secret_env"], "")
        if not secret:
            record('auth.introspection_configuration', 'ROUTER_CONFIGURATION_ERROR')
            raise AuthorizationError("NOT_CONFIGURED", 503)
        try:
            # Streaming bounds the actual bytes, including chunked responses.
            async with client.stream("POST", c["introspection_endpoint"],
                    data={"token": token, "token_type_hint": "access_token"},
                    auth=httpx.BasicAuth(c["introspection_client_id"], secret),
                    headers={"Accept": "application/json"}, timeout=5.0,
                    follow_redirects=False) as response:
                if response.status_code != 200:
                    record('auth.introspection_status', 'AUTH_INTROSPECTION_FAILED')
                    raise AuthorizationError("authorization_unavailable", 503)
                payload = bytearray()
                async for chunk in response.aiter_bytes():
                    payload.extend(chunk)
                    if len(payload) > 65536:
                        record('auth.introspection_size', 'AUTH_INTROSPECTION_FAILED')
                        raise AuthorizationError("authorization_unavailable", 503)
                claims = json.loads(payload)
        except AuthorizationError:
            raise
        except (httpx.HTTPError, ValueError, TypeError):
            record('auth.introspection', 'AUTH_INTROSPECTION_FAILED')
            raise AuthorizationError("authorization_unavailable", 503) from None
        try:
            stamp = time.time()
            exp = claims.get("exp")
            nbf = claims.get("nbf", 0)
            if (claims.get("active") is not True or claims.get("iss") != c["issuer"]
                    or not isinstance(claims.get("sub"), str) or not claims["sub"]
                    or not isinstance(exp, (int, float)) or isinstance(exp, bool)
                    or not math.isfinite(exp) or exp <= stamp
                    or not isinstance(nbf, (int, float)) or isinstance(nbf, bool)
                    or not math.isfinite(nbf) or nbf > stamp):
                record('auth.token_claims', 'AUTH_INVALID_TOKEN')
                raise AuthorizationError("invalid_token", 401)
            audience = claims.get("aud")
            if not (isinstance(audience, str) or (isinstance(audience, list)
                    and audience and all(isinstance(item, str) and item for item in audience))):
                raise AuthorizationError("invalid_token", 401)
            if c["resource_uri"] not in (audience if isinstance(audience, list) else [audience]):
                raise AuthorizationError("invalid_token", 401)
            if not isinstance(claims.get("scope", ""), str):
                raise AuthorizationError("invalid_token", 401)
            principal = principal_id(c["issuer"], claims["sub"])
            auth = AuthContext(principal, str(c["workspace_id"]), frozenset(), frozenset(),
                               str(c["policy_revision"]), float(exp))
            grant = self.current_grant(auth)
            return AuthContext(principal, auth.workspace_id,
                frozenset(claims.get("scope", "").split()) & frozenset(grant.get("scopes", [])),
                frozenset(grant.get("tools", [])), auth.policy_revision, auth.expires_at)
        except AuthorizationError:
            raise
        except (AttributeError, TypeError, ValueError, KeyError):
            raise AuthorizationError("invalid_token", 401) from None
