"""Single authenticated context boundary for every registered ArcMap tool."""
import time
from contextvars import ContextVar
from mcp.server import MCPServer
from .execution_context import verify, request_meta

correlation = ContextVar("zagent_arcmap_correlation", default={})
READ_TOOLS = frozenset((
    'arcmap_ping', 'arcmap_status', 'arcmap_goal_plan', 'arcmap_goal_validate',
    'arcmap_goal_status', 'arcmap_goal_report', 'arcmap_inspect_current_map',
    'arcmap_list_layers', 'arcmap_list_layout_elements', 'arcmap_get_dataframe_state',
    'arcmap_visual_latest', 'arcmap_visual_list', 'arcmap_edit_guard_status',
))


class CorrelatedMCPServer(MCPServer):
    async def call_tool(self, name, arguments, context=None):
        values = verify(request_meta(context), name, arguments or {})
        resources = [r for r in values['effective_resources'] if r['kind'] in ('arcmap', 'gis')]
        if len(resources) != 1:
            raise PermissionError('ONE_ARCMAP_RESOURCE_REQUIRED')
        if name not in READ_TOOLS and values['effective_access'] != 'write':
            raise PermissionError('WRITE_SCOPE_REQUIRED')
        values['resource_id'] = resources[0]['resource_id']
        values['mcp_receive_epoch'] = time.time()
        values['mcp_tool_name'] = name
        token = correlation.set(values)
        try:
            return await super().call_tool(name, arguments, context)
        finally:
            correlation.reset(token)


def current():
    return dict(correlation.get())
