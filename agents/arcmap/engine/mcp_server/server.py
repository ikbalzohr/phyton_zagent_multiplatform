import inspect
import os
import re
import sys

from .request_context import CorrelatedMCPServer as MCPServer
from .services import AgentServices
from .workflow_runtime_client import TunnelWorkflowRuntime
from .tools import (
    connection, inspection, layers, layout, labels, symbology, selection,
    geoprocessing, export, project, observability, layer_management,
    cartography, analysis_extended, layout_automation, export_qa,
    map_recipe, analytics, stage2, window_capture, goals,
    native_layer_properties, native_grids, smart_corner, arc_backlog,
)

mcp = MCPServer("Zagent ArcMap")
services = AgentServices()
services.goal_runtime = TunnelWorkflowRuntime.from_environment()

TOOL_MODULES = (
    connection, inspection, layers, layout, labels, symbology,
    selection, geoprocessing, export, project, observability,
    layer_management, cartography, analysis_extended,
    layout_automation, export_qa, map_recipe, analytics, stage2, window_capture, goals,
    native_layer_properties, native_grids, smart_corner, arc_backlog,
)


def _declared_tool_count(module):
    try:
        source = inspect.getsource(module)
    except Exception:
        return 0
    return len(re.findall(r"@mcp\.tool\s*\(", source))


def _registered_tool_names(server):
    names = set()
    for attr in ("_tool_manager", "tool_manager"):
        mgr = getattr(server, attr, None)
        if mgr is None:
            continue
        for tool_attr in ("_tools", "tools"):
            tools_obj = getattr(mgr, tool_attr, None)
            if isinstance(tools_obj, dict):
                names.update(tools_obj.keys())
    return names


# Register all stable baseline + Stage 2 tools first.
for module in TOOL_MODULES:
    module.register(mcp, services)

BASE_MCP_TOOL_COUNT = sum(_declared_tool_count(module) for module in TOOL_MODULES)
STAGE2_MCP_TOOL_COUNT = _declared_tool_count(stage2)
STAGE2_MCP_LOADED = STAGE2_MCP_TOOL_COUNT >= 8

# Stage 3 is intentionally registered here, after the MCPServer and AgentServices
# objects exist but before counts are published or HTTP transport starts.
WORK_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if WORK_ROOT not in sys.path:
    sys.path.insert(0, WORK_ROOT)

STAGE3_MCP_LOADED = False
STAGE3_MCP_TOOL_COUNT = 0
STAGE3_MCP_STATUS = {"ok": False, "error": "not loaded"}
STAGE3_MCP_ERROR = ""
try:
    from stage3.mcp_tools import (
        auto_install as _stage3_auto_install,
        STAGE3_TOOL_NAMES,
    )
    STAGE3_MCP_STATUS = _stage3_auto_install(globals())
    STAGE3_MCP_TOOL_COUNT = int(STAGE3_MCP_STATUS.get("count", 0) or 0)
    STAGE3_MCP_LOADED = bool(STAGE3_MCP_STATUS.get("ok")) and STAGE3_MCP_TOOL_COUNT == len(STAGE3_TOOL_NAMES)
    if not STAGE3_MCP_LOADED:
        STAGE3_MCP_ERROR = repr(STAGE3_MCP_STATUS)
except Exception as _stage3_exc:
    STAGE3_MCP_LOADED = False
    STAGE3_MCP_TOOL_COUNT = 0
    STAGE3_MCP_ERROR = repr(_stage3_exc)
    STAGE3_MCP_STATUS = {"ok": False, "error": STAGE3_MCP_ERROR}

# Prefer the MCP server's real registered-tool table when available.  Fall back
# to the stable declared baseline plus the successfully registered Stage 3 tools.
_registered = _registered_tool_names(mcp)
if _registered:
    MCP_TOOL_COUNT = len(_registered)
else:
    MCP_TOOL_COUNT = BASE_MCP_TOOL_COUNT + STAGE3_MCP_TOOL_COUNT

# Values are read at call time by arcmap_ping(), so connection.register can be
# executed before these assignments without losing the final counts.
services.mcp_tool_count = MCP_TOOL_COUNT
services.stage2_mcp_tool_count = STAGE2_MCP_TOOL_COUNT
services.stage2_mcp_loaded = STAGE2_MCP_LOADED
services.stage3_mcp_tool_count = STAGE3_MCP_TOOL_COUNT
services.stage3_mcp_loaded = STAGE3_MCP_LOADED
services.stage3_mcp_status = STAGE3_MCP_STATUS

if __name__ == "__main__":
    print("ZAGENT MCP TOOLS      :", MCP_TOOL_COUNT)
    print("ZAGENT STAGE2 TOOLS   :", STAGE2_MCP_TOOL_COUNT)
    print("ZAGENT STAGE2 LOADED  :", STAGE2_MCP_LOADED)
    print("ZAGENT STAGE3 TOOLS   :", STAGE3_MCP_TOOL_COUNT)
    print("ZAGENT STAGE3 LOADED  :", STAGE3_MCP_LOADED)
    if STAGE3_MCP_ERROR:
        print("ZAGENT STAGE3 ERROR   :", STAGE3_MCP_ERROR)
    mcp.run(transport="stdio")
