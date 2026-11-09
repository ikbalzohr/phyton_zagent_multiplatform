"""Explicit ArcMap headless print job; never falls back to CURRENT."""
from mcp.types import ToolAnnotations

_WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False,
                         idempotent_hint=False, open_world_hint=True)


def register(mcp, s):
    @mcp.tool(annotations=_WRITE,
              meta={'zagent.mode_worker_timeout_seconds': {'headless': 300}})
    def arcmap_print_ready_template(mode: str, template_mxd: str,
                                    data_root: str, output_root: str,
                                    scale: float = 0, dpi: int = 400,
                                    main_frame: str = 'Layers',
                                    expected_crs: str = 'WGS_1984_UTM_Zone_51N'):
        """Use a disk MXD copy and local GIS data to export A4 landscape PDF+PNG.

        Scale=0 selects automatic scale from global/project ZAGENT.md;
        a positive scale is a one-job override.
        Requires authenticated ArcMap write authority plus headless-print and export
        permissions; does not grant CURRENT MXD save or live write.
        Export is a candidate; independent PDF and visual QA remain required.
        """
        if mode != 'headless':
            return {'ok': False, 'code': 'HEADLESS_MODE_REQUIRED',
                    'message': 'Attached/CURRENT is not supported by this tool'}
        return s.print_ready_template(
            template_mxd=template_mxd, data_root=data_root,
            output_root=output_root, scale=scale, dpi=dpi,
            main_frame=main_frame, expected_crs=expected_crs)

    tool = mcp._tool_manager._tools['arcmap_print_ready_template']
    model = tool.fn_metadata.arg_model
    model.model_config = dict(model.model_config, extra='forbid')
    model.model_rebuild(force=True)
    tool.parameters = model.model_json_schema(by_alias=True)
