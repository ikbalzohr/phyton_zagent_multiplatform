def register(mcp, s):
    @mcp.tool()
    def arcmap_select_by_attribute(layer_name: str, where_clause: str,
                                   selection_type: str = "NEW_SELECTION", data_frame: str = ""):
        """Select features by SQL attribute query."""
        return s.call("select_by_attribute", "live_write",
                      layer_name=layer_name, where_clause=where_clause,
                      selection_type=selection_type, data_frame=data_frame)

    @mcp.tool()
    def arcmap_clear_selection(layer_name: str, data_frame: str = ""):
        """Clear feature selection on a layer."""
        return s.call("clear_selection", "live_write",
                      layer_name=layer_name, data_frame=data_frame)
