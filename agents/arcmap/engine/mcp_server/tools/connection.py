def register(mcp, s):
    @mcp.tool()
    def arcmap_agent_safety_status():
        """Return Zagent ArcMap safety policy. Read only."""
        return {"ok": True, "safety": s.safety.status()}

    @mcp.tool()
    def arcmap_ping():
        """Check ArcMap 10.6.1, live bridge connectivity, and current MCP/Stage 2 tool counts."""
        result = s.call("ping")
        if isinstance(result, dict):
            result["mcp_tool_count"] = getattr(s, "mcp_tool_count", None)
            result["stage2_mcp_tool_count"] = getattr(s, "stage2_mcp_tool_count", None)
            result["stage2_mcp_loaded"] = bool(getattr(s, "stage2_mcp_loaded", False))
            result["stage3_mcp_tool_count"] = getattr(s, "stage3_mcp_tool_count", None)
            result["stage3_mcp_loaded"] = bool(getattr(s, "stage3_mcp_loaded", False))
            result["zagent_version"] = "1.0.0"
        return result

    @mcp.tool()
    def arcmap_get_status():
        """Return CURRENT MXD status. Read only."""
        result = s.call("status")
        if isinstance(result, dict):
            result["mcp_tool_count"] = getattr(s, "mcp_tool_count", None)
            result["stage2_mcp_tool_count"] = getattr(s, "stage2_mcp_tool_count", None)
            result["stage2_mcp_loaded"] = bool(getattr(s, "stage2_mcp_loaded", False))
            result["stage3_mcp_tool_count"] = getattr(s, "stage3_mcp_tool_count", None)
            result["stage3_mcp_loaded"] = bool(getattr(s, "stage3_mcp_loaded", False))
            result["zagent_version"] = "1.0.0"
        return result
