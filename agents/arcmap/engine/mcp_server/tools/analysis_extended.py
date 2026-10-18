def register(mcp, s):
    @mcp.tool()
    def arcmap_gp_preflight(operation: str, layers: list[str] = [],
                            output_path: str = "", data_frame: str = ""):
        """Validate a geoprocessing request without running it. Read only."""
        return s.call("gp_preflight", operation=operation, layers=layers,
                      output_path=output_path, data_frame=data_frame)

    @mcp.tool()
    def arcmap_select_by_location(target_layer: str, select_layer: str,
                                  overlap_type: str = "INTERSECT",
                                  search_distance: str = "",
                                  selection_type: str = "NEW_SELECTION",
                                  data_frame: str = ""):
        """Select features by spatial relationship. Reversible live selection; MXD remains unsaved."""
        return s.call("select_by_location", "live_write",
                      target_layer=target_layer, select_layer=select_layer,
                      overlap_type=overlap_type, search_distance=search_distance,
                      selection_type=selection_type, data_frame=data_frame)

    @mcp.tool()
    def arcmap_project_features(layer_name: str, output_path: str,
                                target_spatial_reference: str,
                                data_frame: str = ""):
        """Project features to a new output dataset. Blocked while geoprocessing is disabled."""
        return s.call("project_features", "geoprocessing",
                      layer_name=layer_name, output_path=output_path,
                      target_spatial_reference=target_spatial_reference,
                      data_frame=data_frame)

    @mcp.tool()
    def arcmap_merge_layers(layers: list[str], output_path: str,
                            data_frame: str = ""):
        """Merge layers to a new dataset. Blocked while geoprocessing is disabled."""
        return s.call("merge_layers", "geoprocessing", layers=layers,
                      output_path=output_path, data_frame=data_frame)

    @mcp.tool()
    def arcmap_union_layers(layers: list[str], output_path: str,
                            data_frame: str = "", join_attributes: str = "ALL",
                            cluster_tolerance: str = "", gaps: str = "GAPS"):
        """Union polygon layers to a new dataset. Blocked while geoprocessing is disabled."""
        return s.call("union_layers", "geoprocessing", layers=layers,
                      output_path=output_path, data_frame=data_frame,
                      join_attributes=join_attributes,
                      cluster_tolerance=cluster_tolerance, gaps=gaps)

    @mcp.tool()
    def arcmap_erase_features(input_layer: str, erase_layer: str,
                              output_path: str, data_frame: str = ""):
        """Erase features to a new dataset. Blocked while geoprocessing is disabled."""
        return s.call("erase_features", "geoprocessing",
                      input_layer=input_layer, erase_layer=erase_layer,
                      output_path=output_path, data_frame=data_frame)

    @mcp.tool()
    def arcmap_create_file_gdb(out_folder: str, gdb_name: str,
                               version: str = "CURRENT"):
        """Create a File Geodatabase. Blocked while geoprocessing is disabled."""
        return s.call("create_file_gdb", "geoprocessing",
                      out_folder=out_folder, gdb_name=gdb_name, version=version)
