"""Tests for MCP server setup and tool registration."""

from __future__ import annotations

import pytest
from herd_mcp.server import mcp


def test_server_instantiates():
    """Test that the FastMCP server instantiates correctly."""
    assert mcp is not None
    assert hasattr(mcp, "name")
    assert mcp.name == "herd"


@pytest.mark.asyncio
async def test_all_tools_registered():
    """Test that all expected tools are registered."""
    # Get list of registered tool names
    tools = await mcp.list_tools()
    tool_names = [tool.name for tool in tools]

    expected_tools = [
        "herd_log",
        "herd_status",
        "herd_spawn",
        "herd_assign",
        "herd_transition",
        "herd_review",
        "herd_metrics",
        "herd_catchup",
        "herd_decommission",
        "herd_standdown",
        "herd_harvest_tokens",
        "herd_record_decision",
    ]

    for expected_tool in expected_tools:
        assert expected_tool in tool_names, f"Tool {expected_tool} not registered"


@pytest.mark.asyncio
async def test_tool_count():
    """Test that we have exactly 13 tools registered."""
    tools = await mcp.list_tools()
    assert len(tools) == 13
