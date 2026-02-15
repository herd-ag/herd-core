"""Tests for daemon runner."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_daemon_starts_rest_and_slack() -> None:
    """Test daemon starts both REST API and Slack listener."""
    with patch.dict(
        "os.environ",
        {
            "HERD_SLACK_TOKEN": "xoxb-test",
            "SLACK_APP_TOKEN": "xapp-test",
            "HERD_PROJECT_PATH": "/tmp/test",
        },
    ):
        with (
            patch("herd_mcp.daemon.create_app") as mock_create_app,
            patch("herd_mcp.daemon.SessionManager") as mock_session_mgr_class,
            patch("herd_mcp.daemon.SlackListener") as mock_slack_class,
            patch("herd_mcp.daemon.web.AppRunner") as mock_runner_class,
        ):

            # Mock REST app and runner
            mock_app = MagicMock()
            mock_create_app.return_value = mock_app

            mock_runner = MagicMock()
            mock_runner.setup = AsyncMock()
            mock_runner.cleanup = AsyncMock()
            mock_runner_class.return_value = mock_runner

            mock_site = MagicMock()
            mock_site.start = AsyncMock()

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

            # Patch TCPSite and Event to avoid blocking
            with (
                patch("herd_mcp.daemon.web.TCPSite", return_value=mock_site),
                patch("herd_mcp.daemon.asyncio.Event") as mock_event_class,
            ):
                # Make Event().wait() raise KeyboardInterrupt to exit loop
                mock_event = MagicMock()
                mock_event.wait = AsyncMock(side_effect=KeyboardInterrupt())
                mock_event_class.return_value = mock_event

                # Run daemon (will exit via KeyboardInterrupt)
                await start_daemon()

            # Verify REST API was started
            mock_create_app.assert_called_once()
            mock_runner.setup.assert_called_once()
            mock_site.start.assert_called_once()

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
            mock_runner.cleanup.assert_called_once()


@pytest.mark.asyncio
async def test_daemon_requires_slack_tokens() -> None:
    """Test daemon exits if required Slack tokens are missing."""
    with patch.dict("os.environ", {}, clear=True):
        from herd_mcp.daemon import start_daemon

        # Missing HERD_SLACK_TOKEN should exit
        with pytest.raises(SystemExit):
            await start_daemon()

    with patch.dict("os.environ", {"HERD_SLACK_TOKEN": "xoxb-test"}, clear=True):
        # Missing SLACK_APP_TOKEN should exit
        with pytest.raises(SystemExit):
            await start_daemon()


@pytest.mark.asyncio
async def test_daemon_uses_env_configuration() -> None:
    """Test daemon uses environment variables for configuration."""
    with patch.dict(
        "os.environ",
        {
            "HERD_SLACK_TOKEN": "xoxb-test",
            "SLACK_APP_TOKEN": "xapp-test",
            "HERD_API_HOST": "127.0.0.1",
            "HERD_API_PORT": "9999",
            "HERD_PROJECT_PATH": "/custom/path",
            "HERD_IDLE_TIMEOUT": "300",
        },
    ):
        with (
            patch("herd_mcp.daemon.create_app") as mock_create_app,
            patch("herd_mcp.daemon.SessionManager") as mock_session_mgr_class,
            patch("herd_mcp.daemon.SlackListener") as mock_slack_class,
            patch("herd_mcp.daemon.web.AppRunner") as mock_runner_class,
            patch("herd_mcp.daemon.web.TCPSite") as mock_site_class,
        ):

            # Mock all dependencies
            mock_app = MagicMock()
            mock_create_app.return_value = mock_app

            mock_runner = MagicMock()
            mock_runner.setup = AsyncMock()
            mock_runner.cleanup = AsyncMock()
            mock_runner_class.return_value = mock_runner

            mock_site = MagicMock()
            mock_site.start = AsyncMock()
            mock_site_class.return_value = mock_site

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

            # Make Event().wait() raise KeyboardInterrupt
            with patch("herd_mcp.daemon.asyncio.Event") as mock_event_class:
                mock_event = MagicMock()
                mock_event.wait = AsyncMock(side_effect=KeyboardInterrupt())
                mock_event_class.return_value = mock_event

                await start_daemon()

            # Verify configuration was used
            mock_site_class.assert_called_once_with(mock_runner, "127.0.0.1", 9999)
            mock_session_mgr_class.assert_called_once_with("/custom/path", 300)
