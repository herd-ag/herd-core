"""Herd MCP Server - Agent operations via Model Context Protocol."""

__version__ = "0.1.0"

# Export identity and linear_client modules for integration tests
from herd_mcp import identity, linear_client

__all__ = ["identity", "linear_client"]
