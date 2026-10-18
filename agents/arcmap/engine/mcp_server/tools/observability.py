def register(mcp, s):
    @mcp.tool()
    def arcmap_get_dataframe_state(data_frame: str = ""):
        """Read scale, extent, center, rotation and spatial reference for a CURRENT MXD data frame."""
        return s.call("get_dataframe_state", data_frame=data_frame)

    @mcp.tool()
    def arcmap_get_layer_state(layer_name: str, data_frame: str = ""):
        """Read live layer visibility, data source, definition query, label state and scale constraints."""
        return s.call("get_layer_state", layer_name=layer_name, data_frame=data_frame)

    @mcp.tool()
    def arcmap_get_label_state(layer_name: str, data_frame: str = ""):
        """Read label visibility and label class expressions without changing the MXD."""
        return s.call("get_label_state", layer_name=layer_name, data_frame=data_frame)

    @mcp.tool()
    def arcmap_get_selection_state(layer_name: str, data_frame: str = ""):
        """Read selected feature OIDs and selection count."""
        return s.call("get_selection_state", layer_name=layer_name, data_frame=data_frame)

    @mcp.tool()
    def arcmap_list_fields(layer_name: str, data_frame: str = ""):
        """List layer fields and basic field metadata. Read only."""
        return s.call("list_fields", layer_name=layer_name, data_frame=data_frame)

    @mcp.tool()
    def arcmap_get_layer_order(data_frame: str = ""):
        """Read the flattened ArcMap layer order for a data frame."""
        return s.call("get_layer_order", data_frame=data_frame)

    @mcp.tool()
    def arcmap_get_active_dataframe():
        """Return the currently active ArcMap data frame. Read only."""
        return s.call("get_active_dataframe")

    @mcp.tool()
    def arcmap_get_symbology_state(layer_name: str, data_frame: str = ""):
        """Read serializable ArcMap 10.x symbology metadata without changing the layer."""
        return s.call("get_symbology_state", layer_name=layer_name, data_frame=data_frame)

    @mcp.tool()
    def arcmap_snapshot_state():
        """Capture reversible live state in the current ArcMap bridge session without saving the MXD."""
        return s.call("snapshot_state")

    @mcp.tool()
    def arcmap_restore_snapshot(snapshot_id: str):
        """Restore a prior live-session snapshot. Never saves the MXD; Safe Mode live-write guard applies."""
        return s.call("restore_snapshot", "live_write", snapshot_id=snapshot_id)
