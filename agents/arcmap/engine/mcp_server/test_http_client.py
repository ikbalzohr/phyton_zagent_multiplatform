import asyncio
import os
from mcp import Client

URL = "http://{}:{}{}".format(
    os.environ.get("ZAGENT_ARCMAP_HOST", "127.0.0.3"),
    os.environ.get("ZAGENT_ARCMAP_PORT", "18840"),
    os.environ.get("ZAGENT_ARCMAP_MCP_PATH", "/mcp"),
)

async def main():
    async with Client(URL) as client:
        tools = await client.list_tools()
        print("TOOLS:")
        for tool in tools.tools:
            print("-", tool.name)
        result = await client.call_tool("arcmap_ping", {})
        print("PING:", result.structured_content)

if __name__ == "__main__":
    asyncio.run(main())
