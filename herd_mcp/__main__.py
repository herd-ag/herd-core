"""Entry point for Herd MCP server.

Run with:
  python -m herd_mcp          # Streamable-HTTP MCP server (default)
  python -m herd_mcp --stdio  # MCP stdio transport (debugging)
  python -m herd_mcp slack    # Daemon with MCP HTTP + Slack Socket Mode
"""

from __future__ import annotations

import os
import sys

from .server import mcp


def main() -> None:
    """Main entry point with subcommand support."""
    # Load .env if python-dotenv is available
    try:
        from pathlib import Path

        from dotenv import load_dotenv

        # Explicit path resolution: HERD_PROJECT_PATH > ~/herd/.env > cwd search
        project_path = os.getenv("HERD_PROJECT_PATH")
        if project_path:
            env_file = Path(project_path) / ".env"
            if env_file.exists():
                load_dotenv(env_file)
            else:
                load_dotenv()
        else:
            herd_env = Path.home() / "herd" / ".env"
            if herd_env.exists():
                load_dotenv(herd_env)
            else:
                load_dotenv()
    except ImportError:
        pass

    if len(sys.argv) > 1 and sys.argv[1] == "slack":
        from .daemon import run_daemon

        run_daemon()
    elif len(sys.argv) > 1 and sys.argv[1] == "--stdio":
        mcp.run()
    else:
        # Default: streamable-HTTP transport
        mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
