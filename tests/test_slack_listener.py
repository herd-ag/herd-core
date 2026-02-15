"""Tests for Slack listener."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from herd_mcp.session_manager import SessionManager
from herd_mcp.slack_listener import SlackListener


@pytest.fixture
def mock_session_manager() -> MagicMock:
    """Create a mock session manager.

    Returns:
        Mock SessionManager instance.
    """
    manager = MagicMock(spec=SessionManager)
    manager.send_message = AsyncMock(return_value="Response from Mini-Mao")
    return manager


@pytest.fixture
def mock_web_client() -> MagicMock:
    """Create a mock Slack web client.

    Returns:
        Mock AsyncWebClient instance.
    """
    client = MagicMock()
    client.auth_test = AsyncMock(return_value={"user_id": "U_MINIMAO"})
    client.conversations_list = AsyncMock(
        return_value={
            "channels": [
                {"id": "C_MAO123", "name": "mao"},
                {"id": "C_OTHER", "name": "other"},
            ]
        }
    )
    client.users_info = AsyncMock(
        return_value={
            "user": {
                "name": "architect",
                "profile": {"display_name": "Architect"},
            }
        }
    )
    client.chat_postMessage = AsyncMock(return_value={"ok": True})
    return client


@pytest.mark.asyncio
async def test_authorized_user_filter(
    mock_session_manager: MagicMock, mock_web_client: MagicMock
) -> None:
    """Test messages from authorized users are processed."""
    with patch.dict("os.environ", {"HERD_AUTHORIZED_USERS": "U_ARCHITECT,U_ADMIN"}):
        listener = SlackListener(mock_session_manager, "xoxb-test", "xapp-test")

        # Inject mocked web client
        listener.web_client = mock_web_client
        listener.mao_channel_id = "C_MAO123"
        listener.bot_user_id = "U_MINIMAO"

        # Message from authorized user
        event = {
            "type": "message",
            "channel": "C_MAO123",
            "user": "U_ARCHITECT",
            "text": "Hello Mini-Mao",
            "ts": "1234.5678",
        }

        await listener._handle_message(event)

        # Verify message was sent to session manager
        mock_session_manager.send_message.assert_called_once_with(
            "1234.5678", "Hello Mini-Mao", "Architect"
        )

        # Verify response was posted
        mock_web_client.chat_postMessage.assert_called_once()
        call_args = mock_web_client.chat_postMessage.call_args[1]
        assert call_args["text"] == "Response from Mini-Mao"
        assert call_args["thread_ts"] == "1234.5678"


@pytest.mark.asyncio
async def test_unauthorized_user_ignored(
    mock_session_manager: MagicMock, mock_web_client: MagicMock
) -> None:
    """Test messages from unauthorized users are rejected."""
    with patch.dict("os.environ", {"HERD_AUTHORIZED_USERS": "U_ARCHITECT"}):
        listener = SlackListener(mock_session_manager, "xoxb-test", "xapp-test")

        listener.web_client = mock_web_client
        listener.mao_channel_id = "C_MAO123"
        listener.bot_user_id = "U_MINIMAO"

        # Message from unauthorized user
        event = {
            "type": "message",
            "channel": "C_MAO123",
            "user": "U_UNAUTHORIZED",
            "text": "Hello Mini-Mao",
            "ts": "1234.5678",
        }

        await listener._handle_message(event)

        # Verify message was NOT sent to session manager
        mock_session_manager.send_message.assert_not_called()

        # Verify rejection message was posted
        mock_web_client.chat_postMessage.assert_called_once()
        call_args = mock_web_client.chat_postMessage.call_args[1]
        assert "not authorized" in call_args["text"]


@pytest.mark.asyncio
async def test_bot_message_filtering(
    mock_session_manager: MagicMock, mock_web_client: MagicMock
) -> None:
    """Test bot messages are ignored."""
    listener = SlackListener(mock_session_manager, "xoxb-test", "xapp-test")

    listener.web_client = mock_web_client
    listener.mao_channel_id = "C_MAO123"
    listener.bot_user_id = "U_MINIMAO"

    # Bot message
    event = {
        "type": "message",
        "channel": "C_MAO123",
        "user": "U_MINIMAO",
        "bot_id": "B_MINIMAO",
        "text": "Response from Mini-Mao",
        "ts": "1234.5678",
    }

    await listener._handle_message(event)

    # Verify message was NOT processed
    mock_session_manager.send_message.assert_not_called()
    mock_web_client.chat_postMessage.assert_not_called()


@pytest.mark.asyncio
async def test_new_thread_creates_session(
    mock_session_manager: MagicMock, mock_web_client: MagicMock
) -> None:
    """Test new thread creates a new session."""
    listener = SlackListener(mock_session_manager, "xoxb-test", "xapp-test")

    listener.web_client = mock_web_client
    listener.mao_channel_id = "C_MAO123"
    listener.bot_user_id = "U_MINIMAO"
    listener.authorized_users = set()  # No auth filtering

    # New message (not in a thread)
    event = {
        "type": "message",
        "channel": "C_MAO123",
        "user": "U_ARCHITECT",
        "text": "Start new session",
        "ts": "1234.5678",
    }

    await listener._handle_message(event)

    # Verify session manager was called with ts as thread_ts
    mock_session_manager.send_message.assert_called_once_with(
        "1234.5678", "Start new session", "Architect"
    )


@pytest.mark.asyncio
async def test_existing_thread_routes_to_session(
    mock_session_manager: MagicMock, mock_web_client: MagicMock
) -> None:
    """Test reply in existing thread routes to same session."""
    listener = SlackListener(mock_session_manager, "xoxb-test", "xapp-test")

    listener.web_client = mock_web_client
    listener.mao_channel_id = "C_MAO123"
    listener.bot_user_id = "U_MINIMAO"
    listener.authorized_users = set()

    # Reply in thread
    event = {
        "type": "message",
        "channel": "C_MAO123",
        "user": "U_ARCHITECT",
        "text": "Follow-up message",
        "ts": "1234.9999",
        "thread_ts": "1234.5678",  # Original thread timestamp
    }

    await listener._handle_message(event)

    # Verify session manager was called with thread_ts
    mock_session_manager.send_message.assert_called_once_with(
        "1234.5678", "Follow-up message", "Architect"
    )


@pytest.mark.asyncio
async def test_wrong_channel_ignored(
    mock_session_manager: MagicMock, mock_web_client: MagicMock
) -> None:
    """Test messages from other channels are ignored."""
    listener = SlackListener(mock_session_manager, "xoxb-test", "xapp-test")

    listener.web_client = mock_web_client
    listener.mao_channel_id = "C_MAO123"
    listener.bot_user_id = "U_MINIMAO"

    # Message from wrong channel
    event = {
        "type": "message",
        "channel": "C_OTHER",
        "user": "U_ARCHITECT",
        "text": "Hello",
        "ts": "1234.5678",
    }

    await listener._handle_message(event)

    # Verify message was NOT processed
    mock_session_manager.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_error_handling_posts_error_to_thread(
    mock_session_manager: MagicMock, mock_web_client: MagicMock
) -> None:
    """Test errors during message processing are posted to thread."""
    listener = SlackListener(mock_session_manager, "xoxb-test", "xapp-test")

    listener.web_client = mock_web_client
    listener.mao_channel_id = "C_MAO123"
    listener.bot_user_id = "U_MINIMAO"
    listener.authorized_users = set()

    # Make session manager raise an error
    mock_session_manager.send_message.side_effect = Exception("Session error")

    event = {
        "type": "message",
        "channel": "C_MAO123",
        "user": "U_ARCHITECT",
        "text": "Test",
        "ts": "1234.5678",
    }

    await listener._handle_message(event)

    # Verify error message was posted
    mock_web_client.chat_postMessage.assert_called()
    call_args = mock_web_client.chat_postMessage.call_args[1]
    assert "Error processing message" in call_args["text"]
    assert "Session error" in call_args["text"]


@pytest.mark.asyncio
async def test_no_auth_mode_allows_all_users(
    mock_session_manager: MagicMock, mock_web_client: MagicMock
) -> None:
    """Test with no HERD_AUTHORIZED_USERS set, all users are allowed."""
    with patch.dict("os.environ", {}, clear=True):
        listener = SlackListener(mock_session_manager, "xoxb-test", "xapp-test")

        listener.web_client = mock_web_client
        listener.mao_channel_id = "C_MAO123"
        listener.bot_user_id = "U_MINIMAO"

        # Message from any user
        event = {
            "type": "message",
            "channel": "C_MAO123",
            "user": "U_ANYONE",
            "text": "Hello",
            "ts": "1234.5678",
        }

        await listener._handle_message(event)

        # Verify message was processed
        mock_session_manager.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_start_connects_to_slack(
    mock_session_manager: MagicMock, mock_web_client: MagicMock
) -> None:
    """Test start() connects to Slack and finds #mao channel."""
    listener = SlackListener(mock_session_manager, "xoxb-test", "xapp-test")

    # Mock socket client
    mock_socket_client = MagicMock()
    mock_socket_client.socket_mode_request_listeners = []
    mock_socket_client.connect = AsyncMock()
    listener.socket_client = mock_socket_client

    # Inject mocked web client
    listener.web_client = mock_web_client

    await listener.start()

    # Verify auth_test was called
    mock_web_client.auth_test.assert_called_once()

    # Verify conversations_list was called
    mock_web_client.conversations_list.assert_called_once()

    # Verify channel ID was found
    assert listener.mao_channel_id == "C_MAO123"
    assert listener.bot_user_id == "U_MINIMAO"

    # Verify socket client connected
    mock_socket_client.connect.assert_called_once()

    # Verify event handler was registered
    assert len(mock_socket_client.socket_mode_request_listeners) == 1


@pytest.mark.asyncio
async def test_stop_disconnects_from_slack(
    mock_session_manager: MagicMock,
) -> None:
    """Test stop() disconnects from Slack gracefully."""
    listener = SlackListener(mock_session_manager, "xoxb-test", "xapp-test")

    # Mock socket client
    mock_socket_client = MagicMock()
    mock_socket_client.disconnect = AsyncMock()
    mock_socket_client.close = AsyncMock()
    listener.socket_client = mock_socket_client

    await listener.stop()

    # Verify disconnect and close were called
    mock_socket_client.disconnect.assert_called_once()
    mock_socket_client.close.assert_called_once()


@pytest.mark.asyncio
async def test_handle_socket_event_processes_events_api(
    mock_session_manager: MagicMock, mock_web_client: MagicMock
) -> None:
    """Test _handle_socket_event processes events_api requests."""
    listener = SlackListener(mock_session_manager, "xoxb-test", "xapp-test")

    listener.web_client = mock_web_client
    listener.mao_channel_id = "C_MAO123"
    listener.bot_user_id = "U_MINIMAO"
    listener.authorized_users = set()

    # Mock socket client
    mock_socket_client = MagicMock()
    mock_socket_client.send_socket_mode_response = AsyncMock()

    # Create a socket mode request
    request = MagicMock()
    request.type = "events_api"
    request.envelope_id = "test-envelope-123"
    request.payload = {
        "event": {
            "type": "message",
            "channel": "C_MAO123",
            "user": "U_ARCHITECT",
            "text": "Test message",
            "ts": "1234.5678",
        }
    }

    # Handle the event
    await listener._handle_socket_event(mock_socket_client, request)

    # Verify acknowledgment was sent
    mock_socket_client.send_socket_mode_response.assert_called_once()
    response = mock_socket_client.send_socket_mode_response.call_args[0][0]
    assert response.envelope_id == "test-envelope-123"

    # Give async task time to process (the message handling is fire-and-forget)
    await asyncio.sleep(0.1)

    # Verify message was processed
    mock_session_manager.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_handle_socket_event_ignores_non_events_api(
    mock_session_manager: MagicMock,
) -> None:
    """Test _handle_socket_event ignores non-events_api requests."""
    listener = SlackListener(mock_session_manager, "xoxb-test", "xapp-test")

    # Mock socket client
    mock_socket_client = MagicMock()
    mock_socket_client.send_socket_mode_response = AsyncMock()

    # Create a non-events_api request
    request = MagicMock()
    request.type = "slash_commands"
    request.envelope_id = "test-envelope-123"
    request.payload = {}

    # Handle the event
    await listener._handle_socket_event(mock_socket_client, request)

    # Verify acknowledgment was sent
    mock_socket_client.send_socket_mode_response.assert_called_once()

    # Verify no message was processed
    mock_session_manager.send_message.assert_not_called()
