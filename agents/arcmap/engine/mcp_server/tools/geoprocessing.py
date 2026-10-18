def register(mcp, s):
    @mcp.tool()
    def arcmap_buffer(layer_name: str, output_path: str, distance: str,
                      data_frame: str = "", dissolve_option: str = "NONE"):
        """Run ArcGIS Buffer. Blocked by default until geoprocessing is enabled."""
        return s.call("buffer", "geoprocessing", layer_name=layer_name,
                      output_path=output_path, distance=distance,
                      data_frame=data_frame, dissolve_option=dissolve_option)

    @mcp.tool()
    def arcmap_clip(input_layer: str, clip_layer: str, output_path: str, data_frame: str = ""):
        """Run ArcGIS Clip. Blocked by default until geoprocessing is enabled."""
        return s.call("clip", "geoprocessing", input_layer=input_layer,
                      clip_layer=clip_layer, output_path=output_path, data_frame=data_frame)

    @mcp.tool()
    def arcmap_dissolve(layer_name: str, output_path: str, dissolve_fields: list[str] = [],
                        data_frame: str = ""):
        """Run ArcGIS Dissolve. Blocked by default until geoprocessing is enabled."""
        return s.call("dissolve", "geoprocessing", layer_name=layer_name,
                      output_path=output_path, dissolve_fields=dissolve_fields, data_frame=data_frame)

    @mcp.tool()
    def arcmap_intersect(layers: list[str], output_path: str, data_frame: str = ""):
        """Run ArcGIS Intersect. Blocked by default until geoprocessing is enabled."""
        return s.call("intersect", "geoprocessing", layers=layers,
                      output_path=output_path, data_frame=data_frame)

    @mcp.tool()
    def arcmap_spatial_join(target_layer: str, join_layer: str, output_path: str,
                            match_option: str = "INTERSECT", data_frame: str = ""):
        """Run Spatial Join. Blocked by default until geoprocessing is enabled."""
        return s.call("spatial_join", "geoprocessing",
                      target_layer=target_layer, join_layer=join_layer,
                      output_path=output_path, match_option=match_option, data_frame=data_frame)

    @mcp.tool()
    def arcmap_near(input_layer: str, near_layer: str, search_radius: str = "",
                    data_frame: str = ""):
        """Run Near analysis. Blocked by default until geoprocessing is enabled."""
        return s.call("near", "geoprocessing", input_layer=input_layer,
                      near_layer=near_layer, search_radius=search_radius, data_frame=data_frame)
