from mcp.types import ToolAnnotations
from ..execution_modes import inspect_map

_READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False,
                             idempotent_hint=True, open_world_hint=True)


def register(mcp, s):
    @mcp.tool(annotations=_READ_ONLY)
    def arcmap_execution_capabilities():
        """Authenticated source-only inspection-mode contract; no readiness probe."""
        return s.execution_capabilities()

    @mcp.tool(annotations=_READ_ONLY,
              meta={'zagent.mode_worker_timeout_seconds': {'headless': 60}})
    def arcmap_inspect_map(mode: str, mxd_path: str = '', expected_context: dict = None):
        """Inspect one explicit execution lane; never silently switch targets."""
        return inspect_map(s, mode, mxd_path, expected_context)

    # This SDK otherwise silently ignores unknown input fields. Constrain only
    # these two tools, leaving legacy schemas and authenticated ingress intact.
    for name in ('arcmap_execution_capabilities', 'arcmap_inspect_map'):
        tool = mcp._tool_manager._tools[name]
        model = tool.fn_metadata.arg_model
        model.model_config = dict(model.model_config, extra='forbid')
        model.model_rebuild(force=True)
        tool.parameters = model.model_json_schema(by_alias=True)