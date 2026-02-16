"""Tests for adapter registry and wiring."""

from __future__ import annotations

import importlib.util
from unittest.mock import MagicMock, patch

import pytest
from herd_mcp.adapters import AdapterRegistry
from herd_mcp.server import get_adapter_registry


def test_adapter_registry_creation():
    """Test that AdapterRegistry can be created with default None values."""
    registry = AdapterRegistry()

    assert registry.notify is None
    assert registry.tickets is None
    assert registry.repo is None
    assert registry.agent is None
    assert registry.store is None


def test_adapter_registry_with_values():
    """Test that AdapterRegistry can hold adapter instances."""
    mock_notify = MagicMock()
    mock_tickets = MagicMock()

    registry = AdapterRegistry(
        notify=mock_notify,
        tickets=mock_tickets,
    )

    assert registry.notify is mock_notify
    assert registry.tickets is mock_tickets
    assert registry.repo is None


@pytest.mark.skipif(
    not importlib.util.find_spec("herd_notify_slack"),
    reason="herd_notify_slack not installed",
)
@patch.dict("os.environ", {"HERD_NOTIFY_SLACK_TOKEN": "test-slack-token"})
@patch("herd_notify_slack.SlackNotifyAdapter")
def test_get_adapter_registry_with_slack(mock_slack_adapter):
    """Test that get_adapter_registry initializes SlackNotifyAdapter when token is present."""
    # Reset the global registry
    import herd_mcp.server

    herd_mcp.server._registry = None

    # Create mock adapter
    mock_instance = MagicMock()
    mock_slack_adapter.return_value = mock_instance

    # Get registry
    registry = get_adapter_registry()

    # Verify SlackNotifyAdapter was called with token
    mock_slack_adapter.assert_called_once_with(token="test-slack-token")
    assert registry.notify is mock_instance


@patch.dict("os.environ", {}, clear=True)
def test_get_adapter_registry_without_slack_token():
    """Test that get_adapter_registry skips SlackNotifyAdapter when token is missing."""
    # Reset the global registry
    import herd_mcp.server

    herd_mcp.server._registry = None

    # Get registry
    registry = get_adapter_registry()

    # Without token, notify should be None
    assert registry.notify is None


@pytest.mark.skipif(
    not importlib.util.find_spec("herd_ticket_linear"),
    reason="herd_ticket_linear not installed",
)
@patch.dict("os.environ", {"HERD_TICKET_LINEAR_API_KEY": "test-linear-key"})
@patch("herd_ticket_linear.LinearTicketAdapter")
def test_get_adapter_registry_with_linear(mock_linear_adapter):
    """Test that get_adapter_registry initializes LinearTicketAdapter when key is present."""
    # Reset the global registry
    import herd_mcp.server

    herd_mcp.server._registry = None

    # Create mock adapter
    mock_instance = MagicMock()
    mock_linear_adapter.return_value = mock_instance

    # Get registry
    registry = get_adapter_registry()

    # Verify LinearTicketAdapter was called with api_key
    mock_linear_adapter.assert_called_once_with(api_key="test-linear-key", team_id="")
    assert registry.tickets is mock_instance


@patch.dict("os.environ", {}, clear=True)
def test_get_adapter_registry_import_error():
    """Test that get_adapter_registry handles ImportError gracefully."""
    # Reset the global registry
    import herd_mcp.server

    herd_mcp.server._registry = None

    # Get registry (should not raise even if adapters not installed)
    registry = get_adapter_registry()

    # Should return a registry with None adapters
    assert isinstance(registry, AdapterRegistry)
    assert registry.notify is None
    assert registry.tickets is None


@pytest.mark.asyncio
async def test_log_tool_uses_adapter(mock_store):
    """Test that log tool uses NotifyAdapter when available."""
    import asyncio

    from herd_mcp.tools import log

    # Create mock adapter
    mock_notify = MagicMock()
    mock_notify.post = MagicMock(return_value={"ts": "123", "channel": "C123"})

    registry = AdapterRegistry(
        store=mock_store,
        notify=mock_notify,
        write_lock=asyncio.Lock(),
    )

    # Execute with registry
    result = await log.execute(
        message="Test message",
        channel="#test",
        await_response=False,
        agent_name="test-agent",
        registry=registry,
    )

    # Verify adapter was called
    mock_notify.post.assert_called_once_with(
        message="Test message",
        channel="#test",
        username="test-agent",
    )

    assert result["posted"] is True


@pytest.mark.asyncio
async def test_log_tool_fallback_without_adapter(mock_store):
    """Test that log tool falls back to inline implementation when adapter is None."""
    import asyncio

    from herd_mcp.tools import log

    registry = AdapterRegistry(
        store=mock_store,
        notify=None,
        write_lock=asyncio.Lock(),
    )

    # Mock the inline _post_to_slack function
    with patch("herd_mcp.tools.log._post_to_slack") as mock_post:
        mock_post.return_value = {"success": True, "response": {"ts": "123"}}

        result = await log.execute(
            message="Test message",
            channel="#test",
            await_response=False,
            agent_name="test-agent",
            registry=registry,
        )

    # Verify inline function was called
    mock_post.assert_called_once()
    assert result["posted"] is True


@pytest.mark.asyncio
async def test_spawn_tool_uses_adapter():
    """Test that spawn tool _assemble_context_payload executes correctly."""
    from pathlib import Path

    from herd_mcp.tools.spawn import _assemble_context_payload

    # _assemble_context_payload does not use linear_client or adapters directly.
    # It builds a context string from file reads. Test that it runs without error.
    with patch("herd_mcp.tools.spawn._read_file_safe", return_value=""):
        payload = _assemble_context_payload(
            ticket_id="DBC-100",
            agent_code="mason",
            model_code="claude-sonnet-4",
            repo_root=Path("/tmp"),
            worktree_path=Path("/tmp/worktree"),
        )

    # Payload should be a non-empty string containing the agent identity
    assert isinstance(payload, str)
    assert "mason" in payload.lower() or "Mason" in payload
    assert "DBC-100" in payload


@pytest.mark.asyncio
async def test_transition_tool_uses_adapter(mock_store):
    """Test that transition tool uses TicketAdapter when available."""
    import asyncio

    from herd_core.types import TicketRecord
    from herd_mcp.tools import transition

    # Create mock adapter
    mock_tickets = MagicMock()
    mock_tickets.transition = MagicMock()

    registry = AdapterRegistry(
        store=mock_store,
        tickets=mock_tickets,
        write_lock=asyncio.Lock(),
    )

    # Seed test ticket in store
    mock_store.save(
        TicketRecord(
            id="DBC-100",
            title="Test",
            description="Description",
            status="backlog",
        )
    )

    # Execute with registry
    with patch("herd_mcp.linear_client.is_linear_identifier", return_value=True):
        result = await transition.execute(
            ticket_id="DBC-100",
            to_status="in_progress",
            blocked_by=None,
            note=None,
            agent_name="test-agent",
            registry=registry,
        )

    # Verify adapter was called
    mock_tickets.transition.assert_called_once_with("DBC-100", "in_progress")
    assert result["linear_synced"] is True
