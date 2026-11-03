import os

from .server import (
    mcp,
    MCP_TOOL_COUNT,
    STAGE2_MCP_TOOL_COUNT,
    STAGE2_MCP_LOADED,
    STAGE3_MCP_TOOL_COUNT,
    STAGE3_MCP_LOADED,
    STAGE3_MCP_ERROR,
)

HOST = os.environ.get("ZAGENT_ARCMAP_HOST", "127.0.0.3")
if HOST not in ('localhost', '127.0.0.1', '127.0.0.3', '::1'):
    raise ValueError('ArcMap backend must bind private loopback')
PORT = int(os.environ.get("ZAGENT_ARCMAP_PORT", "19140"))
PATH = os.environ.get("ZAGENT_ARCMAP_MCP_PATH", "/mcp")
if not PATH.startswith("/"):
    PATH = "/" + PATH

if __name__ == "__main__":
    print("ZAGENT ARCMAP MCP HTTP")
    print("Endpoint          : http://{0}:{1}{2}".format(HOST, PORT, PATH))
    print("Exposure          : loopback only")
    print("MCP tools         : {0}".format(MCP_TOOL_COUNT))
    print("Stage 2 MCP tools : {0}".format(STAGE2_MCP_TOOL_COUNT))
    print("Stage 2 loaded    : {0}".format(STAGE2_MCP_LOADED))
    print("Stage 3 MCP tools : {0}".format(STAGE3_MCP_TOOL_COUNT))
    print("Stage 3 loaded    : {0}".format(STAGE3_MCP_LOADED))
    if STAGE3_MCP_ERROR:
        print("Stage 3 error     : {0}".format(STAGE3_MCP_ERROR))
    mcp.run(
        transport="streamable-http",
        host=HOST,
        port=PORT,
        streamable_http_path=PATH,
        stateless_http=True,
        json_response=True,
    )
