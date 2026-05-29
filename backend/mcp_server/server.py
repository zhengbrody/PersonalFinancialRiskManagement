"""MCP server entry point — exposes MindMarket data + scoring as
tools that any MCP-compatible client (Claude Desktop, Claude Code,
custom agents) can call.

Why an MCP server alongside the FastAPI HTTP server:

* HTTP routes are for the Next.js frontend and browser clients.
* MCP tools are for **LLM agents** — they speak the tool-use protocol
  natively and can chain calls (e.g. "fetch macro → score portfolio").

Both layers reuse the same ``services/`` modules so an LLM agent and
a browser user can never see different numbers.

Run from the repo root::

    python -m backend.mcp_server

The default transport is stdio (Claude Desktop's default). Add this
to your Claude Desktop ``config.json``:

    {
      "mcpServers": {
        "mindmarket": {
          "command": "python",
          "args": ["-m", "backend.mcp_server"],
          "cwd": "/path/to/RiskManagement"
        }
      }
    }
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from .tools import TOOLS

logger = logging.getLogger(__name__)

SERVER_NAME = "mindmarket"


def _build_server() -> Server:
    """Wire the tool registry into an MCP ``Server`` instance.

    Kept as a function (not module-level) so tests can construct a
    fresh server per test without leaking handler registrations
    across runs.
    """
    server: Server = Server(SERVER_NAME)

    # Build the lookup once; the call_tool handler reads it on every
    # invocation. Names → (handler, schema).
    _by_name: dict[str, Any] = {t["name"]: t for t in TOOLS}

    @server.list_tools()
    async def _list_tools() -> list[Tool]:
        return [
            Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["input_schema"],
            )
            for t in TOOLS
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        entry = _by_name.get(name)
        if entry is None:
            # Per MCP convention, return an error payload in the content
            # rather than raising — the LLM can read the message and
            # retry with a different tool. Raising would surface as
            # an opaque protocol error.
            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": f"Unknown tool: {name}"}),
                )
            ]

        handler = entry["handler"]
        try:
            result = await handler(arguments or {})
        except Exception as exc:
            logger.warning("mcp.tool.failed tool=%s err=%s", name, exc, exc_info=False)
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {
                            "error": type(exc).__name__,
                            "message": str(exc),
                        }
                    ),
                )
            ]

        # All our tools return JSON-serialisable dicts. Hand them back
        # as a single text block — the LLM can parse it cleanly.
        return [TextContent(type="text", text=json.dumps(result, default=str))]

    return server


async def main() -> None:
    """Run the server over stdio.

    Stdio is the right transport for Claude Desktop / Claude Code on
    the same machine — no port to manage, automatic lifecycle tied to
    the client process.
    """
    server = _build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
