def register(mcp, s):
    @mcp.tool()
    def arcmap_capture_layer_style(layer_name: str, data_frame: str = ""):
        """Capture layer symbology into a session-owned .lyr snapshot under Work. Does not save MXD."""
        return s.call("capture_layer_style", "live_write",
                      layer_name=layer_name, data_frame=data_frame)

    @mcp.tool()
    def arcmap_list_style_snapshots():
        """List session-owned style snapshots. Read only."""
        return s.call("list_style_snapshots")

    @mcp.tool()
    def arcmap_restore_layer_style(token: str, layer_name: str = "", data_frame: str = ""):
        """Restore symbology from a prior style snapshot. MXD remains unsaved."""
        return s.call("restore_layer_style", "live_write", token=token,
                      layer_name=layer_name, data_frame=data_frame)

    @mcp.tool()
    def arcmap_delete_style_snapshot(token: str):
        """Delete only a session-owned style snapshot file."""
        return s.call("delete_style_snapshot", "live_write", token=token)

    @mcp.tool()
    def arcmap_get_renderer_capabilities(layer_name: str, data_frame: str = ""):
        """Inspect renderer type and writable symbology properties. Read only."""
        return s.call("get_renderer_capabilities",
                      layer_name=layer_name, data_frame=data_frame)

    @mcp.tool()
    def arcmap_set_label_class(layer_name: str, class_index: int = 0,
                               expression: str = None, sql_query: str = None,
                               show_class_labels: bool = None,
                               expression_parser: str = None,
                               show_labels: bool = None,
                               data_frame: str = ""):
        """Edit one label class live, including expression and SQL filter."""
        return s.call("set_label_class", "live_write",
                      layer_name=layer_name, class_index=class_index,
                      expression=expression, sql_query=sql_query,
                      show_class_labels=show_class_labels,
                      expression_parser=expression_parser,
                      show_labels=show_labels, data_frame=data_frame)

    @mcp.tool()
    def arcmap_set_unique_value_field(layer_name: str, field_name: str,
                                      refresh_values: bool = True,
                                      data_frame: str = ""):
        """Change the value field of an existing UNIQUE_VALUES renderer."""
        return s.call("set_unique_value_field", "live_write",
                      layer_name=layer_name, field_name=field_name,
                      refresh_values=refresh_values, data_frame=data_frame)

    @mcp.tool()
    def arcmap_set_class_breaks(layer_name: str, field_name: str,
                                break_values: list[float], data_frame: str = ""):
        """Set manual breaks on an existing graduated renderer."""
        return s.call("set_class_breaks", "live_write",
                      layer_name=layer_name, field_name=field_name,
                      break_values=break_values, data_frame=data_frame)
