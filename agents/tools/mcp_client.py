"""
MCP Client — Loads tools from the real sqlite_mcp_server.py via stdio transport.

Uses langchain-mcp-adapters to spawn the MCP server as a subprocess,
discover all 14 @mcp.tool() functions, and convert them into LangChain tools.

The returned tools can be passed directly to create_react_agent().
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_mcp_adapters.tools import load_mcp_tools

logger = logging.getLogger(__name__)

# Resolve paths
_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent.parent
_MCP_RUNNER = str(_PROJECT_ROOT / "runners" / "run_sqlite_mcp_server.py")

# Use the same Python interpreter that's running this process
_PYTHON_EXE = sys.executable


async def _load_mcp_tools_async():
    """Async: spawn MCP server subprocess, load all tools, return them."""
    server_params = StdioServerParameters(
        command=_PYTHON_EXE,
        args=[_MCP_RUNNER],
        cwd=str(_PROJECT_ROOT),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)
            logger.info(f"Loaded {len(tools)} MCP tools from sqlite_mcp_server.py")
            return tools


def get_mcp_tools() -> list:
    """
    Synchronously load all 14 tools from the SQLite MCP server.

    Returns a list of LangChain-compatible Tool objects that can be
    passed to create_react_agent() or llm.bind_tools().

    Tools include:
        - db_health_check
        - create_incident
        - append_incident_event
        - save_monitor_alert
        - save_diagnosis
        - save_repair_proposal
        - save_validation_result
        - save_simulation_result
        - create_approval_request
        - save_human_decision
        - save_execution_run
        - log_command_audit
        - save_optimizer_recommendation
        - get_incident_timeline
    """
    try:
        # If there's already a running event loop (e.g., Jupyter), use nest_asyncio
        loop = asyncio.get_running_loop()
        import nest_asyncio
        nest_asyncio.apply()
        return loop.run_until_complete(_load_mcp_tools_async())
    except RuntimeError:
        # No running event loop — safe to use asyncio.run()
        return asyncio.run(_load_mcp_tools_async())
