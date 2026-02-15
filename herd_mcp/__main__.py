"""Entry point for Herd MCP server.

Run with:
  python -m herd_mcp       # MCP stdio server
  python -m herd_mcp serve # REST API server
  python -m herd_mcp slack # Daemon with REST API + Slack Socket Mode
"""

from __future__ import annotations

import os
import sys

from .server import mcp


def main() -> None:
    """Main entry point with subcommand support."""
    # Load .env if python-dotenv is available
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        from .rest_server import run_server

        host = os.getenv("HERD_API_HOST", "0.0.0.0")
        port = int(os.getenv("HERD_API_PORT", "8420"))
        run_server(host=host, port=port)
    elif len(sys.argv) > 1 and sys.argv[1] == "slack":
        from .daemon import run_daemon

        run_daemon()
    else:
        mcp.run()


if __name__ == "__main__":
    main()
