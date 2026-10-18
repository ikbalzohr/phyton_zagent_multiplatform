def register(mcp, s):
    @mcp.tool()
    def arcmap_get_feature_count(layer_name: str, where_clause: str = "",
                                 data_frame: str = ""):
        """Count features with an optional SQL where clause. Read only."""
        return s.call("get_feature_count", layer_name=layer_name,
                      where_clause=where_clause, data_frame=data_frame)

    @mcp.tool()
    def arcmap_get_unique_values(layer_name: str, field_name: str,
                                 where_clause: str = "", limit: int = 100,
                                 data_frame: str = ""):
        """Return unique attribute values with a bounded result size. Read only."""
        return s.call("get_unique_values", layer_name=layer_name,
                      field_name=field_name, where_clause=where_clause,
                      limit=limit, data_frame=data_frame)

    @mcp.tool()
    def arcmap_get_field_statistics(layer_name: str, field_name: str,
                                    where_clause: str = "",
                                    max_rows: int = 100000,
                                    data_frame: str = ""):
        """Compute count/min/max/sum/mean for a numeric field. Read only."""
        return s.call("get_field_statistics", layer_name=layer_name,
                      field_name=field_name, where_clause=where_clause,
                      max_rows=max_rows, data_frame=data_frame)

    @mcp.tool()
    def arcmap_query_features(layer_name: str, fields: list[str] = [],
                              where_clause: str = "", limit: int = 50,
                              include_geometry: bool = False,
                              data_frame: str = ""):
        """Read a bounded set of feature attributes and optional centroid/extent geometry."""
        return s.call("query_features", layer_name=layer_name, fields=fields,
                      where_clause=where_clause, limit=limit,
                      include_geometry=include_geometry, data_frame=data_frame)

    @mcp.tool()
    def arcmap_get_geometry_summary(layer_name: str, where_clause: str = "",
                                    max_features: int = 100000,
                                    data_frame: str = ""):
        """Summarize feature geometry, total area/length and extent. Read only."""
        return s.call("get_geometry_summary", layer_name=layer_name,
                      where_clause=where_clause, max_features=max_features,
                      data_frame=data_frame)

    @mcp.tool()
    def arcmap_compare_layer_extents(layer_a: str, layer_b: str,
                                     data_frame: str = ""):
        """Compare two layer bounding boxes and overlap ratios. Read only."""
        return s.call("compare_layer_extents", layer_a=layer_a,
                      layer_b=layer_b, data_frame=data_frame)

    @mcp.tool()
    def arcmap_get_agent_context():
        """Return a compact current-map context bundle for planning GIS workflows."""
        return s.call("get_agent_context")

    @mcp.tool()
    def arcmap_get_capability_matrix():
        """Return Grand Plan L0-L9 capability status and current safety locks."""
        return s.call("get_capability_matrix")
