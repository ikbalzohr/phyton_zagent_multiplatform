def register(mcp, s):
    @mcp.tool()
    def arcmap_refresh():
        """Refresh ArcMap Active View and TOC."""
        return s.call("refresh", "live_write")

    @mcp.tool()
    def arcmap_save_current_map():
        """Explicitly save CURRENT MXD. Blocked by default in Safe Mode."""
        return s.call("save_current_map", "save")
