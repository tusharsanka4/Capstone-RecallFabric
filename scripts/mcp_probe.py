"""Connect with the official MCP client and verify tool discovery without writing memories.

Run from the repository root. Defaults to a real stdio subprocess; --url checks HTTP.
HTTP uses RECALLFABRIC_API_KEY from the environment, never a command-line secret.
"""

import argparse
import os
import sys
from pathlib import Path

import anyio
import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

EXPECTED_TOOLS = {
    "remember",
    "recall",
    "update_memory",
    "forget",
    "list_memories",
    "get_profile",
    "get_memory_history",
    "get_provenance",
}


async def inspect(reader, writer):
    async with ClientSession(reader, writer) as session:
        initialized = await session.initialize()
        tools = (await session.list_tools()).tools
        names = {tool.name for tool in tools}
        if not EXPECTED_TOOLS <= names:
            raise RuntimeError("MCP server is missing required memory tools")
        if any("user_id" in tool.input_schema.get("properties", {}) for tool in tools):
            raise RuntimeError("MCP tools must derive identity from credentials")
        await session.list_resources()
        await session.get_prompt("use_memory")
        print(f"Connected: {initialized.server_info.name}; protocol {initialized.protocol_version}")
        print("Memory tools: " + ", ".join(sorted(EXPECTED_TOOLS)))
        print("Discovery passed. Database-backed memory calls were not exercised.")


async def run(url):
    if url:
        key = os.environ.get("RECALLFABRIC_API_KEY", "")
        if not key:
            raise RuntimeError("Set RECALLFABRIC_API_KEY for authenticated HTTP")
        async with httpx.AsyncClient(headers={"Authorization": f"Bearer {key}"}) as client:
            async with streamable_http_client(url, http_client=client) as (reader, writer):
                await inspect(reader, writer)
    else:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "recallfabric.mcp_server"],
            cwd=str(Path(__file__).resolve().parents[1]),
            env={**os.environ, "RECALLFABRIC_MCP_TRANSPORT": "stdio"},
        )
        async with stdio_client(params) as (reader, writer):
            await inspect(reader, writer)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", help="Authenticated HTTP endpoint, e.g. http://127.0.0.1:8000/mcp/"
    )
    args = parser.parse_args()
    anyio.run(run, args.url)


if __name__ == "__main__":
    main()
