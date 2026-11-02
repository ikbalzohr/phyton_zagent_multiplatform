#!/usr/bin/env python3
"""Read-only, no-token MCP OAuth discovery preflight. Never changes DNS or grants."""
from __future__ import annotations

import argparse
import json
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def valid_https(value: str) -> bool:
    if not isinstance(value, str):
        return False
    try:
        p = urlsplit(value)
        return bool(p.scheme == "https" and p.hostname and not p.username
                    and not p.password and not p.query and not p.fragment)
    except (ValueError, TypeError):
        return False


def validate_discovery(mcp_uri: str, issuer: str, protected: dict, as_info: dict) -> None:
    if not valid_https(mcp_uri) or not mcp_uri.endswith("/mcp"):
        raise ValueError("Invalid exact public MCP HTTPS URL")
    if not valid_https(issuer):
        raise ValueError("Invalid HTTPS issuer")
    if protected.get("resource") != mcp_uri or protected.get("authorization_servers") != [issuer]:
        raise ValueError("RFC9728 resource/authorization server mismatch")
    if as_info.get("issuer") != issuer:
        raise ValueError("Issuer discovery mismatch")
    for key in ("authorization_endpoint", "token_endpoint"):
        if not valid_https(as_info.get(key, "")):
            raise ValueError("Invalid authorization-server endpoint: " + key)
    if "S256" not in as_info.get("code_challenge_methods_supported", []):
        raise ValueError("PKCE S256 not advertised")
    # Our pre-registered ChatGPT callback is the stable RFC9207 callback.
    # Never claim it works unless issuer identification is advertised.
    if as_info.get("authorization_response_iss_parameter_supported") is not True:
        raise ValueError("Stable ChatGPT callback requires RFC9207 issuer support")
    if not isinstance(as_info.get("token_endpoint_auth_methods_supported"), list):
        raise ValueError("Missing token authentication methods")
    if "none" not in as_info["token_endpoint_auth_methods_supported"]:
        raise ValueError("Public PKCE token exchange 'none' not advertised")


def fetch_json(opener, uri: str) -> dict:
    with opener.open(Request(uri, headers={"Accept": "application/json"}),
                     timeout=12) as response:
        if response.status != 200:
            raise ValueError("Metadata request failed")
        raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("Oversized OAuth metadata")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Malformed OAuth metadata")
        return data


def check(mcp_uri: str, issuer: str) -> None:
    if not valid_https(mcp_uri) or not valid_https(issuer):
        raise ValueError("HTTPS-only configuration required")
    p = urlsplit(mcp_uri)
    metadata_uri = p.scheme + "://" + p.netloc + "/.well-known/oauth-protected-resource" + p.path
    opener = build_opener(NoRedirect())
    metadata = fetch_json(opener, metadata_uri)
    root_metadata = fetch_json(opener, p.scheme + "://" + p.netloc +
                               "/.well-known/oauth-protected-resource")
    if metadata != root_metadata:
        raise ValueError("Root and path-scoped protected metadata disagree")
    issuer_metadata = fetch_json(opener, issuer + "/.well-known/openid-configuration")
    validate_discovery(mcp_uri, issuer, metadata, issuer_metadata)
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-11-25",
                                  "capabilities": {}, "clientInfo":
                                  {"name": "zmp-readiness", "version": "1.0"}}}).encode()
    request = Request(mcp_uri, data=body, headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-11-25"}, method="POST")
    try:
        with opener.open(request, timeout=12):
            raise ValueError("UNAUTHENTICATED_MCP_INITIALIZE_ALLOWED")
    except HTTPError as failure:
        if failure.code != 401:
            raise ValueError("Unauthenticated initialize must return HTTP 401") from None
        challenge = failure.headers.get("WWW-Authenticate", "")
        if not challenge.startswith("Bearer ") or (
                'resource_metadata="' + metadata_uri + '"') not in challenge:
            raise ValueError("Missing/mismatched RFC9728 WWW-Authenticate challenge")
    print("PASS public metadata, issuer, PKCE S256, public token method and unauthenticated 401")
    print("NOT VERIFIED: real user login, refresh rotation, resource/audience claims, grant, or MCP tool execution")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mcp_uri", help="Exact public HTTPS resource URI ending in /mcp")
    parser.add_argument("issuer", help="Exact Keycloak realm issuer HTTPS URI")
    args = parser.parse_args()
    try:
        check(args.mcp_uri, args.issuer)
    except Exception as error:
        parser.exit(2, "NOT_READY: " + type(error).__name__ + ": " + str(error) + "\n")
