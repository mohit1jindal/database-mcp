"""Launch the server exactly as Claude Code will (python -m database_mcp.server
over stdio) and complete a real MCP initialize + tools/list handshake.

No database required: we only list tools, we don't call them.
"""

import asyncio
import sys

from fastmcp import Client
from fastmcp.client.transports import StdioTransport


async def main() -> int:
    transport = StdioTransport(
        command=sys.executable,
        args=["-m", "database_mcp.server"],
    )
    async with Client(transport) as client:
        tools = await client.list_tools()
        names = sorted(t.name for t in tools)
        print("HANDSHAKE OK — server responded over stdio")
        print("tools:", names)
        expected = {"test_connection", "run_query", "list_schemas", "list_tables", "describe_table", "get_table_sample"}
        missing = expected - set(names)
        if missing:
            print("MISSING:", missing)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
