def register(mcp, s):
    @mcp.tool()
    def arcmap_get_layout_manifest():
        """Read page size and all layout element states with stable in-session indices."""
        return s.call("get_layout_manifest")

    @mcp.tool()
    def arcmap_get_layout_element_state(index: int = -1, name: str = "",
                                        element_type: str = ""):
        """Read one layout element by index or unique name/type selector."""
        return s.call("get_layout_element_state", index=index, name=name,
                      element_type=element_type)

    @mcp.tool()
    def arcmap_set_layout_element_state(index: int = -1, name: str = "",
                                        element_type: str = "", x: float = None,
                                        y: float = None, width: float = None,
                                        height: float = None, text: str = None,
                                        font_size: float = None):
        """Edit position/size and text properties of one layout element live."""
        return s.call("set_layout_element_state", "live_write",
                      index=index, name=name, element_type=element_type,
                      x=x, y=y, width=width, height=height,
                      text=text, font_size=font_size)

    @mcp.tool()
    def arcmap_validate_layout_bounds():
        """Check layout elements against page bounds. Read only."""
        return s.call("validate_layout_bounds")

    @mcp.tool()
    def arcmap_apply_layout_recipe(updates: list[dict], atomic: bool = True):
        """Apply multiple layout updates as one reversible live batch."""
        return s.call("apply_layout_recipe", "live_write",
                      updates=updates, atomic=atomic)
