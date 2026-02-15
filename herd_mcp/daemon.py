"""Daemon runner for Herd MCP server with Slack integration.

Runs both the REST API server and Slack Socket Mode listener in a single
asyncio event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from aiohttp import web

from .rest_server import create_app
from .session_manager import SessionManager
from .slack_listener import SlackListener

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def start_daemon() -> None:
    """Start the full daemon: REST API + Slack listener.

    Reads configuration from environment variables:
    - HERD_API_HOST: REST API bind address (default: 0.0.0.0)
    - HERD_API_PORT: REST API port (default: 8420)
    - HERD_PROJECT_PATH: Path to dbt-conceptual project (default: cwd)
    - HERD_IDLE_TIMEOUT: Session idle timeout in seconds (default: 180)
    - HERD_SLACK_TOKEN: Slack bot token (xoxb-...)
    - SLACK_APP_TOKEN: Slack app token for Socket Mode (xapp-...)
    """
    # Get configuration from environment
    host = os.getenv("HERD_API_HOST", "0.0.0.0")
    port = int(os.getenv("HERD_API_PORT", "8420"))
    project_path = os.getenv("HERD_PROJECT_PATH", str(Path.cwd()))
    idle_timeout = int(os.getenv("HERD_IDLE_TIMEOUT", "180"))
    bot_token = os.getenv("HERD_SLACK_TOKEN")
    app_token = os.getenv("SLACK_APP_TOKEN")

    # Validate required tokens
    if not bot_token:
        logger.error(
            "HERD_SLACK_TOKEN environment variable is required for Slack integration"
        )
        sys.exit(1)

    if not app_token:
        logger.error("SLACK_APP_TOKEN environment variable is required for Socket Mode")
        sys.exit(1)

    logger.info("Starting Herd MCP daemon")
    logger.info(f"REST API: http://{host}:{port}")
    logger.info(f"Project path: {project_path}")
    logger.info(f"Idle timeout: {idle_timeout}s")

    # Create REST app
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info(f"REST API server started on http://{host}:{port}")

    # Create session manager
    session_mgr = SessionManager(project_path, idle_timeout)
    await session_mgr.start()
    logger.info("Session manager started")

    # Create and start Slack listener
    slack = SlackListener(session_mgr, bot_token, app_token)
    await slack.start()
    logger.info("Slack listener started")

    # Run until cancelled (Ctrl+C)
    logger.info("Daemon running. Press Ctrl+C to stop.")
    try:
        # Wait forever (until interrupted)
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
    finally:
        # Graceful shutdown
        logger.info("Stopping Slack listener...")
        await slack.stop()

        logger.info("Stopping session manager...")
        await session_mgr.stop()

        logger.info("Stopping REST API server...")
        await runner.cleanup()

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
