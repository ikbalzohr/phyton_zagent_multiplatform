"""Native ArcMap Data Frame grids/graticules. Never saves CURRENT MXD."""


def register(mcp, s):
    @mcp.tool()
    def arcmap_list_native_grids(data_frame: str = ""):
        """Enumerate the existing IMapGrid objects attached to a map frame."""
        return s.call("list_native_grids", data_frame=data_frame)

    @mcp.tool()
    def arcmap_get_native_grid_properties(grid_name: str = "",
                                           grid_index: int = None, data_frame: str = ""):
        """Inspect an existing map grid and its X/Y intervals without editing."""
        return s.call("get_native_grid_properties", grid_name=grid_name,
                      grid_index=grid_index, data_frame=data_frame)

    @mcp.tool()
    def arcmap_set_native_grid_properties(grid_name: str = "",
                                           grid_index: int = None,
                                           properties: dict = None,
                                           data_frame: str = ""):
        """Edit existing grid in place: name, visibility, X/Y intervals, line, labels.

        To set 30 arcseconds, pass x_interval=y_interval=1/120 degrees.
        Returns bridge-session snapshot token for restoration.
        """
        return s.call("set_native_grid_properties", "live_write",
                      grid_name=grid_name, grid_index=grid_index,
                      properties=properties or {}, data_frame=data_frame)

    @mcp.tool()
    def arcmap_restore_native_grid_state(token: str):
        """Restore a grid snapshot only within the same live CURRENT-MXD session."""
        return s.call("restore_native_grid_state", "live_write", token=token)


    @mcp.tool()
    def arcmap_create_native_grid(grid_name: str, interval: float = 0.008333333333333333,
                                  visible: bool = True, data_frame: str = ""):
        """Create a uniquely named graticule when explicitly requested; no save."""
        return s.call("create_native_grid", "live_write",
                      grid_name=grid_name, interval=interval,
                      visible=visible, data_frame=data_frame)

    @mcp.tool()
    def arcmap_remove_native_grid(grid_name: str = "", grid_index: int = None,
                                  confirm_remove: bool = False, data_frame: str = ""):
        """Guarded removal of an existing grid; return session snapshot for restore."""
        return s.call("remove_native_grid", "live_write",
                      grid_name=grid_name, grid_index=grid_index,
                      confirm_remove=confirm_remove, data_frame=data_frame)
