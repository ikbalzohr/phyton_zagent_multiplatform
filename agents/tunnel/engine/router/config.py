from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = Path(os.environ.get("ZAGENT_TUNNEL_CONFIG_DIR", str(ROOT / "config"))).resolve()
CORE_FILE = CONFIG_DIR / "core_services.json"
ADDITIONAL_FILE = CONFIG_DIR / "additional_services.json"
TUNNEL_FILE = CONFIG_DIR / "tunnel.json"

_NS_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_tunnel_config() -> dict[str, Any]:
    cfg = load_json(TUNNEL_FILE)
    forbidden = {"plugin", "plugin_access", "identity_enforcement", "mcp_host_sessions", "mcp_host_clients", "mcp_host_fixed_session"}
    if forbidden.intersection(cfg):
        raise ValueError("LEGACY_CONFIG_REQUIRES_OFFLINE_MIGRATION")
    return cfg


def load_services() -> list[dict[str, Any]]:
    core = load_json(CORE_FILE).get("services", [])
    extra = load_json(ADDITIONAL_FILE).get("services", [])
    services: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_ns: set[str] = set()

    for raw in [*core, *extra]:
        svc = dict(raw)
        validate_service(svc)
        if svc["id"] in seen_ids:
            raise ValueError(f"Duplicate service id: {svc['id']}")
        if svc["namespace"] in seen_ns:
            raise ValueError(f"Duplicate namespace: {svc['namespace']}")
        seen_ids.add(svc["id"])
        seen_ns.add(svc["namespace"])
        services.append(svc)
    return services


def validate_service(service: dict[str, Any]) -> None:
    required = ("id", "name", "namespace", "url")
    for key in required:
        if not str(service.get(key, "")).strip():
            raise ValueError(f"Service field '{key}' is required")

    namespace = str(service["namespace"]).strip().lower()
    if not _NS_RE.fullmatch(namespace):
        raise ValueError(
            f"Invalid namespace '{namespace}'. Use lowercase letters, digits, underscore; start with a letter."
        )
    service["namespace"] = namespace
    if namespace in {"zagent", "system"}:
        raise ValueError("Reserved management namespace")

    cfg = load_tunnel_config()
    security = cfg.get("security", {})
    parsed = urlparse(str(service["url"]).strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Invalid MCP URL scheme for {service['name']}")
    if not parsed.hostname:
        raise ValueError(f"Invalid MCP URL host for {service['name']}")

    allowed = {x.lower() for x in security.get("allowed_hosts", ["127.0.0.1", "localhost"])}
    # Core's exact alias is opt-in even when the legacy local-only switch is off.
    if security.get("allow_local_upstreams_only", True) or parsed.hostname == "127.0.0.3":
        if parsed.hostname.lower() not in allowed:
            raise ValueError(
                f"Host '{parsed.hostname}' is not allowed. Zagent Tunnel1 accepts approved local MCP agents only."
            )

    if parsed.scheme == "http" and not security.get("allow_http", True):
        raise ValueError("HTTP upstreams are disabled by security policy")
    if parsed.hostname not in {"127.0.0.1", "127.0.0.3", "::1", "localhost"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Internal channel requires an exact loopback URL without credentials/query")

    service["enabled"] = bool(service.get("enabled", True))
    service["permanent"] = bool(service.get("permanent", False))
    service["timeout_seconds"] = max(3, min(int(service.get("timeout_seconds", 25)), 120))


def public_tool_name(namespace: str, upstream_name: str) -> str:
    prefix = namespace + "_"
    if upstream_name.startswith(prefix):
        return upstream_name
    return prefix + upstream_name
