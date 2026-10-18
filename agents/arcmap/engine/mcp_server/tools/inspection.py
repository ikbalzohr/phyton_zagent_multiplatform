def register(mcp, s):
    @mcp.tool()
    def arcmap_inspect_current_map():
        """Inspect data frames, layers and basic CURRENT MXD state."""
        return s.call("inspect_current_map")

    @mcp.tool()
    def arcmap_list_layout_text():
        """List text elements in the active ArcMap layout."""
        return s.call("list_layout_text")

    @mcp.tool()
    def arcmap_list_layout_elements():
        """List all layout elements and positions."""
        return s.call("list_layout_elements")
