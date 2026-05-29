"""Entry point: ``python -m backend.mcp_server``."""

from __future__ import annotations

import asyncio
import logging

from .server import main

if __name__ == "__main__":
    # Surface tool failures in stderr so Claude Desktop's log pane
    # picks them up. stdout is reserved for the MCP protocol stream.
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
