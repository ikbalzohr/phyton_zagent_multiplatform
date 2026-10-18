def register(mcp, s):
    @mcp.tool()
    def arcmap_export_preflight(output_path: str):
        """Validate an export path and report broken sources/page state without exporting."""
        return s.call("export_preflight", output_path=output_path)

    @mcp.tool()
    def arcmap_export_bundle(output_dir: str, base_name: str,
                             resolution: int = 400, jpeg_quality: int = 90,
                             overwrite: bool = False,
                             include_pdf: bool = True,
                             include_png: bool = True,
                             include_jpeg: bool = False):
        """Export PDF/PNG/JPEG as one bundle without saving the MXD."""
        return s.call("export_bundle", "export",
                      output_dir=output_dir, base_name=base_name,
                      resolution=resolution, jpeg_quality=jpeg_quality,
                      overwrite=overwrite, include_pdf=include_pdf,
                      include_png=include_png, include_jpeg=include_jpeg,
                      timeout=60)

    @mcp.tool()
    def arcmap_export_tiff(output_path: str, resolution: int = 400,
                           overwrite: bool = False):
        """Export CURRENT layout to TIFF without saving MXD."""
        return s.call("export_tiff", "export", output_path=output_path,
                      resolution=resolution, overwrite=overwrite, timeout=60)

    @mcp.tool()
    def arcmap_get_data_driven_pages_state():
        """Read Data Driven Pages status and current page information."""
        return s.call("get_data_driven_pages_state")

    @mcp.tool()
    def arcmap_export_data_driven_pages_pdf(output_path: str,
                                            page_range_type: str = "ALL",
                                            page_range_string: str = "",
                                            overwrite: bool = False):
        """Export Data Driven Pages to PDF when DDP is enabled."""
        return s.call("export_data_driven_pages_pdf", "export",
                      output_path=output_path,
                      page_range_type=page_range_type,
                      page_range_string=page_range_string,
                      overwrite=overwrite, timeout=120)
