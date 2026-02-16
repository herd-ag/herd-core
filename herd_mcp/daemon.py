"""Daemon runner for Herd MCP server with Slack integration.

Runs the streamable-HTTP MCP server and Slack Socket Mode listener
in a single asyncio event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import uvicorn

from .server import create_http_app
from .session_manager import SessionManager
from .slack_listener import SlackListener

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def start_daemon() -> None:
    """Start the full daemon: MCP HTTP server + Slack listener.

    Reads configuration from environment variables:
    - HERD_API_HOST: MCP server bind address (default: 0.0.0.0)
    - HERD_API_PORT: MCP server port (default: 8420)
    - HERD_PROJECT_PATH: Path to project directory (default: cwd)
    - HERD_IDLE_TIMEOUT: Session idle timeout in seconds (default: 180)
    - HERD_NOTIFY_SLACK_TOKEN: Slack bot token (xoxb-...)
    - HERD_NOTIFY_SLACK_APP_TOKEN: Slack app token for Socket Mode (xapp-...)
    """
    host = os.getenv("HERD_API_HOST", "0.0.0.0")
    port = int(os.getenv("HERD_API_PORT", "8420"))
    project_path = os.getenv("HERD_PROJECT_PATH", str(Path.cwd()))
    idle_timeout = int(os.getenv("HERD_IDLE_TIMEOUT", "180"))
    bot_token = os.getenv("HERD_NOTIFY_SLACK_TOKEN")
    app_token = os.getenv("HERD_NOTIFY_SLACK_APP_TOKEN")

    if not bot_token:
        logger.error(
            "HERD_NOTIFY_SLACK_TOKEN environment variable is required for Slack integration"
        )
        sys.exit(1)

    if not app_token:
        logger.error(
            "HERD_NOTIFY_SLACK_APP_TOKEN environment variable is required for Socket Mode"
        )
        sys.exit(1)

    logger.info("Starting Herd MCP daemon")
    logger.info("MCP server: http://%s:%s/mcp", host, port)
    logger.info("Health check: http://%s:%s/health", host, port)
    logger.info("Project path: %s", project_path)
    logger.info("Idle timeout: %ss", idle_timeout)

    # Create MCP HTTP app with auth middleware
    app = create_http_app()
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    # Create session manager
    session_mgr = SessionManager(project_path, idle_timeout)
    await session_mgr.start()
    logger.info("Session manager started")

    # Create and start Slack listener
    slack = SlackListener(session_mgr, bot_token, app_token)
    await slack.start()
    logger.info("Slack listener started")

    # Run MCP server (blocks until shutdown)
    logger.info("Daemon running. Press Ctrl+C to stop.")
    try:
        await server.serve()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    finally:
        logger.info("Stopping Slack listener...")
        await slack.stop()

        logger.info("Stopping session manager...")
        await session_mgr.stop()

        logger.info("Daemon stopped")


def run_daemon() -> None:
    """Entry point for daemon mode.

    Runs the asyncio event loop with the daemon tasks.
    """
    try:
        asyncio.run(start_daemon())
    except KeyboardInterrupt:
        # Already handled in start_daemon
        pass
