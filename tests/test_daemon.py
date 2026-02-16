"""Tests for daemon runner."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_daemon_starts_mcp_and_slack() -> None:
    """Test daemon starts MCP HTTP server and Slack listener."""
    with patch.dict(
        "os.environ",
        {
            "HERD_NOTIFY_SLACK_TOKEN": "xoxb-test",
            "HERD_NOTIFY_SLACK_APP_TOKEN": "xapp-test",
            "HERD_PROJECT_PATH": "/tmp/test",
        },
    ):
        with (
            patch("herd_mcp.daemon.create_http_app") as mock_create_app,
            patch("herd_mcp.daemon.SessionManager") as mock_session_mgr_class,
            patch("herd_mcp.daemon.SlackListener") as mock_slack_class,
            patch("herd_mcp.daemon.uvicorn") as mock_uvicorn,
        ):

            # Mock MCP app
            mock_app = MagicMock()
            mock_create_app.return_value = mock_app

            # Mock uvicorn server
            mock_server = MagicMock()
            mock_server.serve = AsyncMock(side_effect=KeyboardInterrupt())
            mock_uvicorn.Config.return_value = MagicMock()
            mock_uvicorn.Server.return_value = mock_server

            # Mock session manager
            mock_session_mgr = MagicMock()
            mock_session_mgr.start = AsyncMock()
            mock_session_mgr.stop = AsyncMock()
            mock_session_mgr_class.return_value = mock_session_mgr

            # Mock Slack listener
            mock_slack = MagicMock()
            mock_slack.start = AsyncMock()
            mock_slack.stop = AsyncMock()
            mock_slack_class.return_value = mock_slack

            # Import after patching
            from herd_mcp.daemon import start_daemon

            # Run daemon (will exit via KeyboardInterrupt from server.serve)
            await start_daemon()

            # Verify MCP HTTP app was created
            mock_create_app.assert_called_once()
            mock_uvicorn.Config.assert_called_once()
            mock_uvicorn.Server.assert_called_once()
            mock_server.serve.assert_called_once()

            # Verify session manager was started
            mock_session_mgr_class.assert_called_once_with("/tmp/test", 180)
            mock_session_mgr.start.assert_called_once()

            # Verify Slack listener was started
            mock_slack_class.assert_called_once_with(
                mock_session_mgr, "xoxb-test", "xapp-test"
            )
            mock_slack.start.assert_called_once()

            # Verify graceful shutdown
            mock_slack.stop.assert_called_once()
            mock_session_mgr.stop.assert_called_once()


@pytest.mark.asyncio
async def test_daemon_requires_slack_tokens() -> None:
    """Test daemon exits if required Slack tokens are missing."""
    with patch.dict("os.environ", {}, clear=True):
        from herd_mcp.daemon import start_daemon

        # Missing HERD_NOTIFY_SLACK_TOKEN should exit
        with pytest.raises(SystemExit):
            await start_daemon()

    with patch.dict("os.environ", {"HERD_NOTIFY_SLACK_TOKEN": "xoxb-test"}, clear=True):
        # Missing HERD_NOTIFY_SLACK_APP_TOKEN should exit
        with pytest.raises(SystemExit):
            await start_daemon()


@pytest.mark.asyncio
async def test_daemon_uses_env_configuration() -> None:
    """Test daemon uses environment variables for configuration."""
    with patch.dict(
        "os.environ",
        {
            "HERD_NOTIFY_SLACK_TOKEN": "xoxb-test",
            "HERD_NOTIFY_SLACK_APP_TOKEN": "xapp-test",
            "HERD_API_HOST": "127.0.0.1",
            "HERD_API_PORT": "9999",
            "HERD_PROJECT_PATH": "/custom/path",
            "HERD_IDLE_TIMEOUT": "300",
        },
    ):
        with (
            patch("herd_mcp.daemon.create_http_app") as mock_create_app,
            patch("herd_mcp.daemon.SessionManager") as mock_session_mgr_class,
            patch("herd_mcp.daemon.SlackListener") as mock_slack_class,
            patch("herd_mcp.daemon.uvicorn") as mock_uvicorn,
        ):

            # Mock all dependencies
            mock_app = MagicMock()
            mock_create_app.return_value = mock_app

            mock_server = MagicMock()
            mock_server.serve = AsyncMock(side_effect=KeyboardInterrupt())
            mock_uvicorn.Config.return_value = MagicMock()
            mock_uvicorn.Server.return_value = mock_server

            mock_session_mgr = MagicMock()
            mock_session_mgr.start = AsyncMock()
            mock_session_mgr.stop = AsyncMock()
            mock_session_mgr_class.return_value = mock_session_mgr

            mock_slack = MagicMock()
            mock_slack.start = AsyncMock()
            mock_slack.stop = AsyncMock()
            mock_slack_class.return_value = mock_slack

            # Import after patching
            from herd_mcp.daemon import start_daemon

            await start_daemon()

            # Verify configuration was used
            mock_uvicorn.Config.assert_called_once_with(
                mock_app, host="127.0.0.1", port=9999, log_level="info"
            )
            mock_session_mgr_class.assert_called_once_with("/custom/path", 300)
