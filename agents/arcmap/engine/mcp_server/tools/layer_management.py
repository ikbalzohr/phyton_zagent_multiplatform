def register(mcp, s):
    @mcp.tool()
    def arcmap_get_layer_extent(layer_name: str, data_frame: str = ""):
        """Read a layer extent and center without changing the map."""
        return s.call("get_layer_extent", layer_name=layer_name, data_frame=data_frame)

    @mcp.tool()
    def arcmap_get_layer_capabilities(layer_name: str, data_frame: str = ""):
        """Inspect ArcMap layer capabilities supported by the live layer."""
        return s.call("get_layer_capabilities", layer_name=layer_name, data_frame=data_frame)

    @mcp.tool()
    def arcmap_get_broken_data_sources():
        """List broken data sources in CURRENT MXD. Read only."""
        return s.call("get_broken_data_sources")

    @mcp.tool()
    def arcmap_validate_data_source(layer_name: str = "", data_frame: str = "", path: str = ""):
        """Validate a layer data source or explicit dataset path. Read only."""
        return s.call("validate_data_source",
                      layer_name=layer_name, data_frame=data_frame, path=path)

    @mcp.tool()
    def arcmap_rename_layer(layer_name: str, new_name: str, data_frame: str = ""):
        """Rename one live layer in CURRENT MXD without saving."""
        return s.call("rename_layer", "live_write",
                      layer_name=layer_name, new_name=new_name, data_frame=data_frame)

    @mcp.tool()
    def arcmap_move_layer(layer_name: str, reference_layer: str,
                          position: str = "BEFORE", data_frame: str = ""):
        """Move one layer BEFORE or AFTER another layer in the same data frame. MXD remains unsaved."""
        return s.call("move_layer", "live_write",
                      layer_name=layer_name, reference_layer=reference_layer,
                      position=position, data_frame=data_frame)

    @mcp.tool()
    def arcmap_set_layer_transparency(layer_name: str, transparency: int,
                                      data_frame: str = ""):
        """Set live layer transparency from 0 to 100 without saving."""
        return s.call("set_layer_transparency", "live_write",
                      layer_name=layer_name, transparency=transparency,
                      data_frame=data_frame)

    @mcp.tool()
    def arcmap_set_layer_scale_range(layer_name: str, min_scale: float = 0.0,
                                     max_scale: float = 0.0, data_frame: str = ""):
        """Set live layer min/max scale. Use 0 for no limit. MXD remains unsaved."""
        return s.call("set_layer_scale_range", "live_write",
                      layer_name=layer_name, min_scale=min_scale,
                      max_scale=max_scale, data_frame=data_frame)

    @mcp.tool()
    def arcmap_add_temporary_layer(path: str, data_frame: str = "",
                                   position: str = "AUTO_ARRANGE"):
        """Add a session-scoped temporary layer that can only be removed with its returned token."""
        return s.call("add_temporary_layer", "live_write",
                      path=path, data_frame=data_frame, position=position)

    @mcp.tool()
    def arcmap_list_temporary_layers():
        """List temporary layers created by the L3 session manager. Read only."""
        return s.call("list_temporary_layers")

    @mcp.tool()
    def arcmap_remove_temporary_layer(token: str):
        """Remove only a temporary layer created by arcmap_add_temporary_layer. Generic removal stays blocked."""
        return s.call("remove_temporary_layer", "live_write", token=token)
