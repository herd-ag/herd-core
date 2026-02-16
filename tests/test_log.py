"""Tests for herd_log tool."""

from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import MagicMock, patch

import pytest
from herd_core.types import (
    AgentRecord,
    AgentState,
    LifecycleEvent,
)
from herd_mcp.adapters import AdapterRegistry
from herd_mcp.tools import log


@pytest.fixture
def mock_registry(mock_store):
    """Provide an AdapterRegistry with MockStore for log tool tests."""
    return AdapterRegistry(store=mock_store, write_lock=asyncio.Lock())


@pytest.fixture
def seeded_store(mock_store):
    """Seed the mock store with test data for log tool."""
    # Seed agent instance for mason (running)
    mock_store.save(
        AgentRecord(
            id="inst-001",
            agent="mason",
            model="claude-sonnet-4",
            state=AgentState.RUNNING,
        )
    )
    return mock_store


@pytest.fixture
def seeded_registry(seeded_store):
    """Provide an AdapterRegistry with seeded MockStore."""
    return AdapterRegistry(store=seeded_store, write_lock=asyncio.Lock())


def test_classify_event_type_pr():
    """Test event classification for PR submissions."""
    assert log._classify_event_type("Created PR #123") == "pr_submitted"
    assert log._classify_event_type("Opened pull request") == "pr_submitted"


def test_classify_event_type_review():
    """Test event classification for reviews."""
    assert log._classify_event_type("Code review complete") == "review_complete"
    assert log._classify_event_type("QA passed") == "review_complete"


def test_classify_event_type_blocked():
    """Test event classification for blockers."""
    assert log._classify_event_type("Blocked by missing API") == "blocked"


def test_classify_event_type_started():
    """Test event classification for work start."""
    assert log._classify_event_type("Started working on DBC-91") == "work_started"
    assert log._classify_event_type("Beginning implementation") == "work_started"


def test_classify_event_type_commit():
    """Test event classification for commits."""
    assert log._classify_event_type("Pushed commit abc123") == "code_pushed"
    assert log._classify_event_type("New commit to branch") == "code_pushed"


def test_classify_event_type_default():
    """Test event classification for generic updates."""
    assert log._classify_event_type("Making progress") == "status_update"
    assert log._classify_event_type("Random message") == "status_update"


@pytest.mark.asyncio
async def test_execute_with_agent_instance(seeded_registry, seeded_store):
    """Test log execution with valid agent instance."""
    with patch("herd_mcp.tools.log._post_to_slack") as mock_slack:
        mock_slack.return_value = {"success": True, "response": {"ok": True}}

        result = await log.execute(
            message="Started working on DBC-91",
            channel="#herd-feed",
            await_response=False,
            agent_name="mason",
            registry=seeded_registry,
        )

        assert result["posted"] is True
        assert result["agent"] == "mason"
        assert result["event_type"] == "work_started"
        assert result["event_id"] is not None

        # Verify lifecycle activity was recorded
        events = seeded_store.events(LifecycleEvent, entity_id="inst-001")
        assert len(events) == 1
        assert events[0].event_type == "work_started"
        assert events[0].detail == "Started working on DBC-91"


@pytest.mark.asyncio
async def test_execute_without_agent_instance(mock_registry):
    """Test log execution without active agent instance."""
    with patch("herd_mcp.tools.log._post_to_slack") as mock_slack:
        mock_slack.return_value = {"success": True, "response": {"ok": True}}

        result = await log.execute(
            message="Testing without instance",
            channel="#herd-feed",
            await_response=False,
            agent_name="nonexistent",
            registry=mock_registry,
        )

        assert result["posted"] is True
        assert result["agent"] == "nonexistent"
        assert result["event_type"] == "status_update"

        # Verify no lifecycle activity was recorded (no instance found)
        events = mock_registry.store.events(LifecycleEvent)
        assert len(events) == 0


@pytest.mark.asyncio
async def test_execute_slack_failure(seeded_registry):
    """Test log execution when Slack posting fails."""
    with patch("herd_mcp.tools.log._post_to_slack") as mock_slack:
        mock_slack.return_value = {"success": False, "error": "Token not set"}

        result = await log.execute(
            message="Test message",
            channel="#herd-feed",
            await_response=False,
            agent_name="mason",
            registry=seeded_registry,
        )

        assert result["posted"] is False
        assert result["event_id"] is None
        assert "slack_response" in result
        assert result["slack_response"]["error"] == "Token not set"


def test_post_to_slack_no_token():
    """Test Slack posting without token."""
    with patch.dict(os.environ, {}, clear=True):
        result = log._post_to_slack("Test message", "#test", "TestAgent")
        assert result["success"] is False
        assert "error" in result
        assert "HERD_NOTIFY_SLACK_TOKEN" in result["error"]


def test_post_to_slack_with_token():
    """Test Slack posting with token (mocked)."""
    with patch.dict(os.environ, {"HERD_NOTIFY_SLACK_TOKEN": "xoxb-test-token"}):
        with patch("urllib.request.urlopen") as mock_urlopen:
            # Mock successful Slack API response
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"ok": true, "ts": "1234567890.123"}'
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=None)
            mock_urlopen.return_value = mock_response

            result = log._post_to_slack("Test message", "#test", "TestAgent")
            assert result["success"] is True
            assert "response" in result
            assert result["response"]["ok"] is True


@pytest.mark.asyncio
async def test_execute_await_response_false(seeded_registry):
    """Test log execution with await_response=False returns empty responses."""
    with patch("herd_mcp.tools.log._post_to_slack") as mock_slack:
        mock_slack.return_value = {
            "success": True,
            "response": {
                "ok": True,
                "ts": "1234567890.123",
                "channel": "C12345",
            },
        }

        result = await log.execute(
            message="Test message",
            channel="#herd-feed",
            await_response=False,
            agent_name="mason",
            registry=seeded_registry,
        )

        assert result["posted"] is True
        assert result["responses"] == []


@pytest.mark.asyncio
async def test_execute_await_response_with_replies(seeded_registry):
    """Test log execution with await_response=True finds replies."""
    with patch("herd_mcp.tools.log._post_to_slack") as mock_slack:
        mock_slack.return_value = {
            "success": True,
            "response": {
                "ok": True,
                "ts": "1234567890.123",
                "channel": "C12345",
            },
        }

        with patch("herd_mcp.tools.log._get_thread_replies") as mock_replies:
            mock_replies.return_value = [
                {
                    "user": "U12345",
                    "text": "Test reply",
                    "ts": "1234567891.123",
                }
            ]

            with patch("asyncio.sleep"):
                with patch.dict(os.environ, {"HERD_NOTIFY_SLACK_TOKEN": "xoxb-test"}):
                    result = await log.execute(
                        message="Test message",
                        channel="#herd-feed",
                        await_response=True,
                        agent_name="mason",
                        registry=seeded_registry,
                    )

                    assert result["posted"] is True
                    assert len(result["responses"]) == 1
                    assert result["responses"][0]["user"] == "U12345"
                    assert result["responses"][0]["text"] == "Test reply"
                    assert result["responses"][0]["ts"] == "1234567891.123"


@pytest.mark.asyncio
async def test_execute_await_response_timeout(seeded_registry):
    """Test log execution with await_response=True times out after 24 polls."""
    with patch("herd_mcp.tools.log._post_to_slack") as mock_slack:
        mock_slack.return_value = {
            "success": True,
            "response": {
                "ok": True,
                "ts": "1234567890.123",
                "channel": "C12345",
            },
        }

        with patch("herd_mcp.tools.log._get_thread_replies") as mock_replies:
            mock_replies.return_value = []

            with patch("asyncio.sleep") as mock_sleep:
                with patch.dict(os.environ, {"HERD_NOTIFY_SLACK_TOKEN": "xoxb-test"}):
                    result = await log.execute(
                        message="Test message",
                        channel="#herd-feed",
                        await_response=True,
                        agent_name="mason",
                        registry=seeded_registry,
                    )

                    assert result["posted"] is True
                    assert result["responses"] == []
                    # Verify we polled 24 times
                    assert mock_sleep.call_count == 24


def test_get_thread_replies_success():
    """Test get_thread_replies helper returns filtered replies."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "ok": True,
                "messages": [
                    {
                        "user": "U00000",
                        "text": "Parent message",
                        "ts": "1234567890.123",
                    },
                    {"user": "U12345", "text": "Reply 1", "ts": "1234567891.123"},
                    {"user": "U67890", "text": "Reply 2", "ts": "1234567892.123"},
                ],
            }
        ).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=None)
        mock_urlopen.return_value = mock_response

        replies = log._get_thread_replies("C12345", "1234567890.123", "xoxb-token")

        assert len(replies) == 2
        assert replies[0]["text"] == "Reply 1"
        assert replies[1]["text"] == "Reply 2"


def test_get_thread_replies_no_replies():
    """Test get_thread_replies helper with empty thread."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "ok": True,
                "messages": [
                    {
                        "user": "U00000",
                        "text": "Parent message",
                        "ts": "1234567890.123",
                    },
                ],
            }
        ).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=None)
        mock_urlopen.return_value = mock_response

        replies = log._get_thread_replies("C12345", "1234567890.123", "xoxb-token")

        assert replies == []


def test_get_thread_replies_api_error():
    """Test get_thread_replies helper graceful error handling."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = Exception("Network error")

        replies = log._get_thread_replies("C12345", "1234567890.123", "xoxb-token")

        assert replies == []


@pytest.mark.asyncio
async def test_execute_await_response_slack_post_fails(seeded_registry):
    """Test await_response=True when Slack post fails - polling should be skipped."""
    with patch("herd_mcp.tools.log._post_to_slack") as mock_slack:
        mock_slack.return_value = {"success": False, "error": "Token not set"}

        with patch("herd_mcp.tools.log._get_thread_replies") as mock_replies:
            mock_replies.return_value = []

            with patch("asyncio.sleep") as mock_sleep:
                result = await log.execute(
                    message="Test message",
                    channel="#herd-feed",
                    await_response=True,
                    agent_name="mason",
                    registry=seeded_registry,
                )

                assert result["posted"] is False
                assert result["responses"] == []
                # Verify polling was NOT triggered (sleep never called)
                assert mock_sleep.call_count == 0
                # Verify _get_thread_replies was NOT called
                assert mock_replies.call_count == 0


@pytest.mark.asyncio
async def test_execute_await_response_token_missing_at_poll_time(seeded_registry):
    """Test await_response=True when token is missing at poll time - polling should be skipped."""
    with patch("herd_mcp.tools.log._post_to_slack") as mock_slack:
        mock_slack.return_value = {
            "success": True,
            "response": {
                "ok": True,
                "ts": "1234567890.123",
                "channel": "C12345",
            },
        }

        with patch("herd_mcp.tools.log._get_thread_replies") as mock_replies:
            mock_replies.return_value = []

            with patch("asyncio.sleep") as mock_sleep:
                # Token present for post, but missing at poll time
                with patch.dict(os.environ, {}, clear=True):
                    result = await log.execute(
                        message="Test message",
                        channel="#herd-feed",
                        await_response=True,
                        agent_name="mason",
                        registry=seeded_registry,
                    )

                    assert result["posted"] is True
                    assert result["responses"] == []
                    # Verify polling was NOT triggered (sleep never called)
                    assert mock_sleep.call_count == 0
                    # Verify _get_thread_replies was NOT called
                    assert mock_replies.call_count == 0


@pytest.mark.asyncio
async def test_execute_await_response_replies_on_third_poll(seeded_registry):
    """Test await_response=True when replies arrive on 3rd poll (not immediately)."""
    with patch("herd_mcp.tools.log._post_to_slack") as mock_slack:
        mock_slack.return_value = {
            "success": True,
            "response": {
                "ok": True,
                "ts": "1234567890.123",
                "channel": "C12345",
            },
        }

        with patch("herd_mcp.tools.log._get_thread_replies") as mock_replies:
            # Return empty on first two calls, replies on third call
            mock_replies.side_effect = [
                [],
                [],
                [
                    {
                        "user": "U12345",
                        "text": "Late reply",
                        "ts": "1234567893.123",
                    }
                ],
            ]

            with patch("asyncio.sleep") as mock_sleep:
                with patch.dict(os.environ, {"HERD_NOTIFY_SLACK_TOKEN": "xoxb-test"}):
                    result = await log.execute(
                        message="Test message",
                        channel="#herd-feed",
                        await_response=True,
                        agent_name="mason",
                        registry=seeded_registry,
                    )

                    assert result["posted"] is True
                    assert len(result["responses"]) == 1
                    assert result["responses"][0]["user"] == "U12345"
                    assert result["responses"][0]["text"] == "Late reply"
                    # Verify asyncio.sleep called 3 times (before each poll)
                    assert mock_sleep.call_count == 3
                    # Verify _get_thread_replies called 3 times
                    assert mock_replies.call_count == 3


def test_get_thread_replies_api_returns_not_ok():
    """Test get_thread_replies when API returns ok:false."""
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {
                "ok": False,
                "error": "channel_not_found",
            }
        ).encode()
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=None)
        mock_urlopen.return_value = mock_response

        replies = log._get_thread_replies("C12345", "1234567890.123", "xoxb-token")

        assert replies == []


@pytest.mark.asyncio
async def test_execute_with_sync_notify_adapter(seeded_store):
    """Test log execution with synchronous notify adapter (no await)."""
    import inspect

    # Create a mock NotifyAdapter that returns a dict-like PostResult
    class MockPostResult(dict):
        """Mock PostResult that behaves like a dict."""
        def __init__(self):
            super().__init__(ok=True, ts="1234567890.123", channel="C12345")

    mock_notify = MagicMock()

    # Mock sync post() method
    mock_notify.post = MagicMock(return_value=MockPostResult())
    mock_notify.get_thread_replies = MagicMock(return_value=[])

    registry = AdapterRegistry(
        store=seeded_store,
        notify=mock_notify,
        write_lock=asyncio.Lock(),
    )

    result = await log.execute(
        message="Test with sync adapter",
        channel="#herd-feed",
        await_response=False,
        agent_name="mason",
        registry=registry,
    )

    assert result["posted"] is True
    assert result["agent"] == "mason"

    # Verify sync method was called (WITHOUT await - it's a sync function)
    mock_notify.post.assert_called_once_with(
        message="Test with sync adapter",
        channel="#herd-feed",
        username="mason",
    )
    # Verify it was NOT called as a coroutine
    assert not inspect.iscoroutinefunction(mock_notify.post)
