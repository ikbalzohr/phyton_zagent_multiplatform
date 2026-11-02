"""Produce a NON-ACTIVATING, least-privilege Keycloak CIMD policy review plan.

Keycloak 26.8 CIMD requires a client policy and executor. Exact Admin UI
configuration is reviewed by the operator before any realm mutation. This
module never registers a client, publishes DCR, or accesses credentials.
"""
from __future__ import annotations

from urllib.parse import urlsplit


def build_review(resource_uri: str) -> dict:
    if not isinstance(resource_uri, str) or resource_uri != resource_uri.strip():
        raise ValueError("Exact HTTPS MCP resource URI required")
    try:
        parsed = urlsplit(resource_uri)
        valid = (parsed.scheme == "https" and parsed.hostname
                 and parsed.path == "/mcp" and not parsed.username
                 and not parsed.password and not parsed.query and not parsed.fragment
                 and all(not ch.isspace() for ch in resource_uri))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Exact HTTPS MCP resource URI required")
    return {
        "status": "OWNER_REVIEW_REQUIRED_NOT_APPLIED",
        "feature_flags": ["cimd", "resource-indicators"],
        "resource_indicator_allow_list": [resource_uri],
        "client_policies": [
            {
                "name": "zmp-claude-cimd",
                "condition": "client-id-uri",
                "uri_scheme": ["https"],
                "client_id_trusted_domains": ["claude.ai"],
                "executor": "client-id-metadata-document",
                "metadata_trusted_domains": ["claude.ai", "localhost", "127.0.0.1"],
                "allow_http_scheme": False,
                "restrict_same_domain": False,
                "only_allow_confidential_client": False,
                "accept_public_client_with_confidential_only_grant_types": True,
                "resource_indicator_allow_list": [resource_uri],
                "notes": "One policy for Claude Code and Desktop; never apply conflicting profiles."
            },
            {
                "name": "zmp-hermes-cimd",
                "condition": "client-id-uri",
                "uri_scheme": ["https"],
                "client_id_trusted_domains": ["nousresearch.github.io"],
                "executor": "client-id-metadata-document",
                "metadata_trusted_domains": ["nousresearch.github.io", "localhost", "127.0.0.1"],
                "allow_http_scheme": False,
                "restrict_same_domain": False,
                "only_allow_confidential_client": False,
                "accept_public_client_with_confidential_only_grant_types": False,
                "resource_indicator_allow_list": [resource_uri],
                "notes": "Verify Hermes' current metadata URLs/redirects before activating this profile."
            }
        ],
        "chatgpt": {
            "mode": "pre_registered_public_pkce",
            "client_id": "chatgpt-zagent-mp",
            "why": "Keycloak 26.8 CIMD rejects ChatGPT plural token_endpoint_auth_methods_supported.",
            "redirect_uri": "https://chatgpt.com/connector_platform_oauth_redirect",
            "must_verify_issuer_callback": True
        },
        "registration_endpoint": {
            "public": False,
            "reason": "Do not permit unrestricted anonymous Dynamic Client Registration."
        },
        "required_live_checks": [
            "Keycloak OIDC discovery issuer/PKCE S256 and RFC9207 iss",
            "CIMD client metadata fetched and redirected securely",
            "resource sent at both authorization and token endpoints",
            "token introspection active/iss/aud/exp/scope and refresh rotation",
            "MCP 401 challenge; revoked grants; absent or wrong audience denied"
        ]
    }
