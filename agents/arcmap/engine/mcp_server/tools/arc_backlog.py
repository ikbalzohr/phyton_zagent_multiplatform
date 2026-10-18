"""ARC-05..ARC-10 optional ArcMap Dev source tools.

Live document edits require ArcMap ownership and explicit safety gates.
"""
def register(mcp, s):
    @mcp.tool()
    def arcmap_set_native_label_preset(
            layer_name: str, preset: str = "FONT_2", size: float = None,
            font_name: str = "", label_class_index: int = 0,
            remove_duplicates: bool = None, thinning_distance: float = None,
            data_frame: str = ""):
        """Set label text symbol; Maplex-only duplicate thinning fails closed."""
        return s.call("native_label_preset", "live_write",
                      layer_name=layer_name, preset=preset, size=size,
                      font_name=font_name, label_class_index=label_class_index,
                      remove_duplicates=remove_duplicates,
                      thinning_distance=thinning_distance, data_frame=data_frame)

    @mcp.tool()
    def arcmap_connect_gis_mapserver(service_url: str, layer_name: str = "",
                                     data_frame: str = ""):
        """Attach a HTTPS ArcGIS MapServer .lyr descriptor without exporting SHP."""
        return s.call("connect_gis_mapserver", "live_write",
                      service_url=service_url, layer_name=layer_name,
                      data_frame=data_frame)

    @mcp.tool()
    def arcmap_list_native_scale_bars():
        """List existing native IScaleBar layout elements without editing."""
        return s.call("list_native_scale_bars")

    @mcp.tool()
    def arcmap_set_native_scale_bar(element_name: str, units: str,
                                    preserve_distance: bool = True):
        """Switch an existing scale bar METERS/KILOMETERS; never saves MXD."""
        return s.call("set_native_scale_bar", "live_write",
                      element_name=element_name, units=units,
                      preserve_distance=preserve_distance)

    @mcp.tool()
    def arcmap_edit_guard_acquire(seconds: int = 900):
        """Declare a manual human-edit interval; return a release token.

        Cooperative only. Does not intercept unannounced physical mouse actions.
        """
        return s.call("edit_guard_acquire", "live_write", seconds=seconds)

    @mcp.tool()
    def arcmap_edit_guard_status():
        """Read the active cooperative ArcMap manual edit guard."""
        return s.call("edit_guard_status")

    @mcp.tool()
    def arcmap_edit_guard_release(token: str):
        """End only the current session's manual edit interval."""
        return s.call("edit_guard_release", "live_write", token=token)

    @mcp.tool()
    def arcmap_calculate_geometry_xy(
            layer_name: str, x_field: str = "X_DD", y_field: str = "Y_DD",
            output_wkid: int = 4326, create_fields: bool = False,
            max_rows: int = 100000, confirm_dataset_write: bool = False,
            data_frame: str = ""):
        """Write X/Y into Double fields; irreversible row updates require confirmation."""
        return s.call("calculate_geometry_xy", "destructive",
                      layer_name=layer_name, x_field=x_field, y_field=y_field,
                      output_wkid=output_wkid, create_fields=create_fields,
                      max_rows=max_rows, confirm_dataset_write=confirm_dataset_write,
                      data_frame=data_frame)

    @mcp.tool()
    def arcmap_import_coordinates_to_shp(
            input_path: str, output_shp: str, x_field: str = "X",
            y_field: str = "Y", label_field: str = "LABEL",
            input_wkid: int = 4326, delimiter: str = ",",
            sheet_name: str = "", max_rows: int = 10000,
            add_to_map: bool = False, confirm_create_shp: bool = False,
            data_frame: str = ""):
        """Import CSV/Excel/DBF/EXIF GPS as NEW point SHP, never overwrites."""
        return s.call("import_coordinates_to_shp", "destructive",
                      input_path=input_path, output_shp=output_shp,
                      x_field=x_field, y_field=y_field,
                      label_field=label_field, input_wkid=input_wkid,
                      delimiter=delimiter, sheet_name=sheet_name,
                      max_rows=max_rows, add_to_map=add_to_map,
                      confirm_create_shp=confirm_create_shp,
                      data_frame=data_frame)
