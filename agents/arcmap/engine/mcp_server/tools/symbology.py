def register(mcp, s):
    @mcp.tool()
    def arcmap_apply_symbology_from_layer(layer_name: str, source_layer_file: str, data_frame: str = ""):
        """Apply symbology from a .lyr file to a target layer live."""
        return s.call("apply_symbology_from_layer", "live_write",
                      layer_name=layer_name, source_layer_file=source_layer_file,
                      data_frame=data_frame)
