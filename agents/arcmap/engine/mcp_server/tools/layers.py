def register(mcp, s):
    @mcp.tool()
    def arcmap_list_layers():
        """List layers, visibility, data source and data frame."""
        return s.call("list_layers")

    @mcp.tool()
    def arcmap_set_layer_visibility(layer_name: str, visible: bool = False, data_frame: str = ""):
        """Change layer visibility live. MXD remains unsaved."""
        return s.call("set_layer_visibility", "live_write",
                      layer_name=layer_name, visible=visible, data_frame=data_frame)

    @mcp.tool()
    def arcmap_zoom_to_layer(layer_name: str, data_frame: str = "", scale_factor: float = 1.0):
        """Zoom active map to a layer extent. MXD remains unsaved."""
        return s.call("zoom_to_layer", "live_write",
                      layer_name=layer_name, data_frame=data_frame, scale_factor=scale_factor)

    @mcp.tool()
    def arcmap_set_definition_query(layer_name: str, definition_query: str, data_frame: str = ""):
        """Set a layer definition query live. MXD remains unsaved."""
        return s.call("set_definition_query", "live_write",
                      layer_name=layer_name, definition_query=definition_query, data_frame=data_frame)

    @mcp.tool()
    def arcmap_add_layer(path: str, data_frame: str = "", position: str = "AUTO_ARRANGE"):
        """Add a layer to CURRENT MXD without saving it."""
        return s.call("add_layer", "live_write", path=path, data_frame=data_frame, position=position)

    @mcp.tool()
    def arcmap_remove_layer(layer_name: str, data_frame: str = ""):
        """Remove a layer from CURRENT MXD. Blocked by default as destructive."""
        return s.call("remove_layer", "destructive", layer_name=layer_name, data_frame=data_frame)

    @mcp.tool()
    def arcmap_replace_data_source(layer_name: str, workspace_path: str, workspace_type: str,
                                   dataset_name: str = "", data_frame: str = "", validate: bool = True):
        """Replace a layer data source live without saving the MXD."""
        return s.call("replace_data_source", "live_write",
                      layer_name=layer_name, workspace_path=workspace_path,
                      workspace_type=workspace_type, dataset_name=dataset_name,
                      data_frame=data_frame, validate=validate)
