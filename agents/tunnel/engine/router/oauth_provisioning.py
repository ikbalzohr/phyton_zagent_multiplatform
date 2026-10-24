"""Non-secret, offline Keycloak/Hermes integration plan; never installs or activates.

Run from agents/tunnel/engine on the owner machine:
  python -m router.oauth_provisioning --spec approved-input.json
JSON is written to stdout only. Merge resource_server into the owner's private
Core-managed tunnel configuration AFTER review; this is not a complete tunnel
config or a Keycloak realm import. No networking, credential access or file writes.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from urllib.parse import urlsplit

from .access import principal_id, secure_url

_FIELDS = frozenset({"issuer", "resource_uri", "subject", "workspace_id", "policy_revision",
                     "profile_id", "device_id", "installation_id", "grant_expires_at",
                     "hermes_client_id", "introspection_client_id", "redirect_port"})
_TEXT_FIELDS = _FIELDS - {"grant_expires_at", "redirect_port", "issuer", "resource_uri"}


def build_readonly_plan(spec: dict) -> dict:
    """Require exact owner-approved identifiers; output revoked read-only policy.

    subject MUST be the actual AS access-token subject (not username, client name,
    email, or Hermes profile). Introspection and MCP client identities are separate.
    """
    if not isinstance(spec, dict) or set(spec) != _FIELDS:
        raise ValueError("EXACT_NONSECRET_FIELDS_REQUIRED")
    for key in _TEXT_FIELDS:
        value = spec[key]
        if (not isinstance(value, str) or not value or value != value.strip()
                or len(value) > 256 or any(ord(ch) < 32 for ch in value)):
            raise ValueError("INVALID_IDENTIFIER:" + key)
    for key in ("issuer", "resource_uri"):
        value = spec[key]
        if (not isinstance(value, str) or not secure_url(value)
                or value != value.strip() or any(ch.isspace() for ch in value)
                or "?" in value or "#" in value or value.endswith("/")):
            raise ValueError("EXACT_HTTPS_URL_REQUIRED:" + key)
        parsed = urlsplit(value)
        try:
            parsed.port
        except ValueError:
            raise ValueError("INVALID_URL_PORT:" + key) from None
        if any(segment in (".", "..") for segment in parsed.path.split("/")):
            raise ValueError("URL_DOT_SEGMENTS_NOT_ALLOWED:" + key)
    issuer, resource = spec["issuer"], spec["resource_uri"]
    if not re.fullmatch(r"/realms/[A-Za-z0-9_-]+", urlsplit(issuer).path):
        raise ValueError("KEYCLOAK_REALM_ISSUER_REQUIRED")
    if urlsplit(resource).path != "/mcp":
        raise ValueError("CURRENT_ROUTER_REQUIRES_EXACT_MCP_PATH")
    if spec["hermes_client_id"] == spec["introspection_client_id"]:
        raise ValueError("SEPARATE_CLIENT_IDENTITIES_REQUIRED")
    expiry = spec["grant_expires_at"]
    if type(expiry) not in (int, float) or not math.isfinite(expiry) or expiry <= 0:
        raise ValueError("FINITE_GRANT_EXPIRY_REQUIRED")
    port = spec["redirect_port"]
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("UNPRIVILEGED_CALLBACK_PORT_REQUIRED")
    principal = principal_id(issuer, spec["subject"])
    redirect = f"http://127.0.0.1:{port}/callback"
    grant = {
        "revoked": True, "expires_at": expiry,
        "scopes": ["files:read"], "tools": ["files_stat", "files_read"],
        "files_resource": {
            "resource_id": "workspace:" + spec["workspace_id"] + ":approved-repository",
            "kind": "files", "profile_id": spec["profile_id"],
            "device_id": spec["device_id"], "installation_id": spec["installation_id"],
            "revoked": True}}
    return {
        "status": "REVIEW_REQUIRED_NOT_ACTIVE",
        "resource_server": {
            "resource_uri": resource, "issuer": issuer, "authorization_servers": [issuer],
            "introspection_endpoint": issuer + "/protocol/openid-connect/token/introspect",
            "introspection_client_id": spec["introspection_client_id"],
            "introspection_secret_env": "ZAGENT_OAUTH_INTROSPECTION_SECRET",
            "workspace_id": spec["workspace_id"], "policy_revision": spec["policy_revision"],
            "scopes_supported": ["files:read"], "grants": {principal: grant}},
        "hermes_mcp_entry": {
            "url": resource, "auth": "oauth", "enabled": False, "ssl_verify": True,
            "protocol": "legacy", "connect_timeout": 300,
            "oauth": {"client_id": spec["hermes_client_id"],
                      "token_endpoint_auth_method": "none", "scope": "files:read",
                      "flow": "browser", "redirect_port": port, "timeout": 300},
            "tools": {"include": ["files_stat", "files_read"],
                      "resources": False, "prompts": False},
            "sampling": {"enabled": False}},
        "keycloak": {
            "hermes_client": {
                "clientId": spec["hermes_client_id"], "protocol": "openid-connect",
                "publicClient": True, "standardFlowEnabled": True,
                "implicitFlowEnabled": False, "directAccessGrantsEnabled": False,
                "serviceAccountsEnabled": False, "fullScopeAllowed": False,
                "redirectUris": [redirect], "webOrigins": [],
                "attributes": {"pkce.code.challenge.method": "S256"},
                "optionalClientScopes": ["files:read"]},
            "introspection_client": {
                "clientId": spec["introspection_client_id"], "protocol": "openid-connect",
                "publicClient": False, "clientAuthenticatorType": "client-secret",
                "standardFlowEnabled": False, "implicitFlowEnabled": False,
                "directAccessGrantsEnabled": False, "serviceAccountsEnabled": False,
                "fullScopeAllowed": False, "redirectUris": [], "webOrigins": []},
            "read_scope": {"name": "files:read", "protocol": "openid-connect",
                           "attributes": {"include.in.token.scope": "true"}},
            "audience_mapper": {
                "name": "zagent-exact-resource-audience", "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper", "consentRequired": False,
                "config": {"included.custom.audience": resource,
                           "access.token.claim": "true", "id.token.claim": "false",
                           "introspection.token.claim": "true"}}}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path, required=True,
                        help="Non-secret owner-approved JSON input; output is stdout only")
    args = parser.parse_args()
    try:
        plan = build_readonly_plan(json.loads(args.spec.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError, TypeError):
        parser.exit(2, "Invalid non-secret provisioning specification; no changes made.\n")
    print(json.dumps(plan, indent=2, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
