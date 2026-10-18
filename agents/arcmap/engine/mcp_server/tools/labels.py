def register(mcp, s):
    @mcp.tool()
    def arcmap_toggle_labels(layer_name: str, show: bool = True, data_frame: str = ""):
        """Enable or disable labels for a layer live."""
        return s.call("toggle_labels", "live_write",
                      layer_name=layer_name, show=show, data_frame=data_frame)

    @mcp.tool()
    def arcmap_set_label_expression(layer_name: str, expression: str,
                                    expression_parser: str = "PYTHON", data_frame: str = ""):
        """Set the first label class expression for a layer live."""
        return s.call("set_label_expression", "live_write",
                      layer_name=layer_name, expression=expression,
                      expression_parser=expression_parser, data_frame=data_frame)
