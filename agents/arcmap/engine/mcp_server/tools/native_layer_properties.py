"""ArcMap 10.6.1 native Layer Properties tools (Development source)."""


def register(mcp, s):
    @mcp.tool()
    def arcmap_get_native_layer_properties(layer_name: str, data_frame: str = ""):
        """Read supported Layer Properties tabs and explicit capability limitations."""
        return s.call("get_native_layer_properties",
                      layer_name=layer_name, data_frame=data_frame)

    @mcp.tool()
    def arcmap_get_native_renderer_state(layer_name: str, data_frame: str = ""):
        """Read the renderer, unique value field, categories and other-values flag."""
        return s.call("get_native_renderer_state",
                      layer_name=layer_name, data_frame=data_frame)

    @mcp.tool()
    def arcmap_set_native_layer_properties(layer_name: str, properties: dict,
                                           data_frame: str = ""):
        """Edit name, visibility, query, transparency, scales, labels; no MXD save."""
        return s.call("set_native_layer_properties", "live_write",
                      layer_name=layer_name, properties=properties, data_frame=data_frame)

    @mcp.tool()
    def arcmap_set_native_unique_values_renderer(layer_name: str, field_name: str,
                                                  show_other_values: bool = False,
                                                  refresh_values: bool = True,
                                                  category_styles: dict = None,
                                                  category_labels: dict = None,
                                                  data_frame: str = ""):
        """Create/replace native Unique Values renderer via ArcObjects, not .lyr template.

        Snapshot token returned for style rollback; refuses ambiguous layers.
        """
        return s.call("set_native_unique_values_renderer", "live_write",
                      layer_name=layer_name, field_name=field_name,
                      show_other_values=show_other_values,
                      refresh_values=refresh_values,
                      category_styles=category_styles or {},
                      category_labels=category_labels or {},
                      data_frame=data_frame)

    @mcp.tool()
    def arcmap_refresh_native_unique_values(layer_name: str, field_name: str = "",
                                             data_frame: str = ""):
        """Refresh the categories of an existing native single-field unique renderer."""
        return s.call("refresh_native_unique_values", "live_write",
                      layer_name=layer_name, field_name=field_name, data_frame=data_frame)

    @mcp.tool()
    def arcmap_update_native_category(layer_name: str, value: str, label: str = None,
                                      symbol: dict = None, remove: bool = False,
                                      show_other_values: bool = None,
                                      data_frame: str = ""):
        """Edit one unique-value class, category label/symbol or other-values flag."""
        return s.call("update_native_category", "live_write",
                      layer_name=layer_name, value=value, label=label,
                      symbol=symbol, remove=remove,
                      show_other_values=show_other_values, data_frame=data_frame)
