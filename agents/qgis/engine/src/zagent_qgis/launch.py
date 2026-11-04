"""Run upstream FastMCP as a loopback HTTP MCP service owned by Zagent Core.

FastMCP 1.26 passes constructor defaults directly into its Settings object,
so setting FASTMCP_PORT in the environment does NOT change the default 8000.
This thin adapter binds explicitly, without editing upstream GPL source.
"""
import ipaddress
import os

from qgis_mcp.server import mcp


def configure():
    host = os.environ.get("ZAGENT_QGIS_BIND_HOST", "127.0.0.1")
    try:
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError("QGIS_MCP_REQUIRES_LOOPBACK_BIND")
    except ValueError as error:
        raise ValueError("QGIS_MCP_REQUIRES_LOOPBACK_BIND") from error
    raw_port = os.environ.get("ZAGENT_QGIS_BIND_PORT", "19150")
    try:
        port = int(raw_port)
    except ValueError as error:
        raise ValueError("QGIS_MCP_PORT_INVALID") from error
    if not 1 <= port <= 65535:
        raise ValueError("QGIS_MCP_PORT_INVALID")
    mcp.settings.host = host
    mcp.settings.port = port
    return host, port


def main():
    configure()
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()