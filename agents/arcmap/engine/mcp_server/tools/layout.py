def register(mcp, s):
    @mcp.tool()
    def arcmap_set_title(title: str):
        """Change the primary map title live. Does not save the MXD."""
        if not title.strip():
            return {"ok": False, "error": "title cannot be empty"}
        return s.call("set_title", "live_write", value=title.strip())

    @mcp.tool()
    def arcmap_set_layout_text(text: str, element_name: str = "", index: int = -1):
        """Change a layout text element by name or index. MXD remains unsaved."""
        payload = {"text": text, "element_name": element_name}
        if index >= 0:
            payload["index"] = index
        return s.call("set_layout_text", "live_write", **payload)

    @mcp.tool()
    def arcmap_set_layout_element_position(element_name: str, x: float = None, y: float = None,
                                           width: float = None, height: float = None):
        """Move/resize a named layout element live."""
        return s.call("set_layout_element_position", "live_write",
                      element_name=element_name, x=x, y=y, width=width, height=height)

    @mcp.tool()
    def arcmap_set_map_scale(scale: float, data_frame: str = ""):
        """Set map scale for a data frame live."""
        return s.call("set_map_scale", "live_write", scale=scale, data_frame=data_frame)
