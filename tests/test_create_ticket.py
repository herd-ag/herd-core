"""Tests for herd_create_ticket tool."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from herd_core.types import TicketEvent, TicketRecord
from herd_mcp.adapters import AdapterRegistry
from herd_mcp.tools import create_ticket


@pytest.fixture
def mock_tickets_adapter():
    """Provide a mock TicketAdapter that returns a ticket ID on create."""
    adapter = MagicMock()
    adapter.create.return_value = "DBC-200"
    return adapter


@pytest.fixture
def registry_with_tickets(mock_store, mock_tickets_adapter):
    """Provide an AdapterRegistry with both store and ticket adapters."""
    return AdapterRegistry(
        store=mock_store,
        tickets=mock_tickets_adapter,
        write_lock=asyncio.Lock(),
    )


@pytest.fixture
def registry_tickets_only(mock_tickets_adapter):
    """Provide an AdapterRegistry with ticket adapter but no store."""
    return AdapterRegistry(
        tickets=mock_tickets_adapter,
        write_lock=asyncio.Lock(),
    )


@pytest.fixture
def registry_no_tickets(mock_store):
    """Provide an AdapterRegistry with store but no ticket adapter."""
    return AdapterRegistry(
        store=mock_store,
        write_lock=asyncio.Lock(),
    )


@pytest.mark.asyncio
async def test_create_ticket_success(
    registry_with_tickets, mock_store, mock_tickets_adapter
):
    """Test successful ticket creation with all optional fields."""
    result = await create_ticket.execute(
        title="Implement dark mode",
        description="Add dark mode toggle to settings page",
        priority="high",
        labels=["label-1", "label-2"],
        agent_name="mason",
        registry=registry_with_tickets,
    )

    assert result["created"] is True
    assert result["ticket_id"] == "DBC-200"
    assert result["title"] == "Implement dark mode"
    assert result["description"] == "Add dark mode toggle to settings page"
    assert result["priority"] == "high"
    assert result["labels"] == ["label-1", "label-2"]
    assert result["agent"] == "mason"

    # Verify adapter was called with correct args
    mock_tickets_adapter.create.assert_called_once_with(
        "Implement dark mode",
        description="Add dark mode toggle to settings page",
        team_id=None,
        priority=2,  # "high" maps to 2
        labels=["label-1", "label-2"],
    )

    # Verify ticket was saved to store
    ticket = mock_store.get(TicketRecord, "DBC-200")
    assert ticket is not None
    assert ticket.id == "DBC-200"
    assert ticket.title == "Implement dark mode"
    assert ticket.description == "Add dark mode toggle to settings page"
    assert ticket.status == "backlog"
    assert ticket.labels == ["label-1", "label-2"]

    # Verify event was recorded
    events = mock_store.events(TicketEvent, entity_id="DBC-200")
    assert len(events) == 1
    assert events[0].event_type == "created"
    assert events[0].new_status == "backlog"
    assert "mason" in events[0].note


@pytest.mark.asyncio
async def test_create_ticket_minimal(
    registry_with_tickets, mock_store, mock_tickets_adapter
):
    """Test ticket creation with only required title field."""
    result = await create_ticket.execute(
        title="Fix bug",
        description=None,
        priority=None,
        labels=None,
        agent_name="steve",
        registry=registry_with_tickets,
    )

    assert result["created"] is True
    assert result["ticket_id"] == "DBC-200"
    assert result["title"] == "Fix bug"
    assert result["description"] is None
    assert result["priority"] is None
    assert result["labels"] is None

    # Verify adapter was called without priority
    mock_tickets_adapter.create.assert_called_once_with(
        "Fix bug",
        description=None,
        team_id=None,
        priority=None,
        labels=None,
    )

    # Verify ticket was saved with empty labels
    ticket = mock_store.get(TicketRecord, "DBC-200")
    assert ticket is not None
    assert ticket.labels == []


@pytest.mark.asyncio
async def test_create_ticket_empty_title():
    """Test that empty title is rejected."""
    registry = AdapterRegistry(
        tickets=MagicMock(),
        write_lock=asyncio.Lock(),
    )
    result = await create_ticket.execute(
        title="",
        description=None,
        priority=None,
        labels=None,
        agent_name="mason",
        registry=registry,
    )

    assert result["created"] is False
    assert "title is required" in result["error"]


@pytest.mark.asyncio
async def test_create_ticket_whitespace_title():
    """Test that whitespace-only title is rejected."""
    registry = AdapterRegistry(
        tickets=MagicMock(),
        write_lock=asyncio.Lock(),
    )
    result = await create_ticket.execute(
        title="   ",
        description=None,
        priority=None,
        labels=None,
        agent_name="mason",
        registry=registry,
    )

    assert result["created"] is False
    assert "title is required" in result["error"]


@pytest.mark.asyncio
async def test_create_ticket_no_ticket_adapter(registry_no_tickets):
    """Test error when TicketAdapter is not configured."""
    result = await create_ticket.execute(
        title="Some ticket",
        description=None,
        priority=None,
        labels=None,
        agent_name="mason",
        registry=registry_no_tickets,
    )

    assert result["created"] is False
    assert "TicketAdapter not configured" in result["error"]


@pytest.mark.asyncio
async def test_create_ticket_no_registry():
    """Test error when registry is None."""
    result = await create_ticket.execute(
        title="Some ticket",
        description=None,
        priority=None,
        labels=None,
        agent_name="mason",
        registry=None,
    )

    assert result["created"] is False
    assert "TicketAdapter not configured" in result["error"]


@pytest.mark.asyncio
async def test_create_ticket_invalid_priority(registry_with_tickets):
    """Test error for invalid priority string."""
    result = await create_ticket.execute(
        title="Some ticket",
        description=None,
        priority="critical",
        labels=None,
        agent_name="mason",
        registry=registry_with_tickets,
    )

    assert result["created"] is False
    assert "Invalid priority" in result["error"]
    assert "critical" in result["error"]


@pytest.mark.asyncio
async def test_create_ticket_all_priorities(
    registry_with_tickets, mock_tickets_adapter
):
    """Test that all valid priority strings map correctly."""
    expected_map = {
        "none": 0,
        "urgent": 1,
        "high": 2,
        "normal": 3,
        "low": 4,
    }

    for priority_str, priority_int in expected_map.items():
        mock_tickets_adapter.create.reset_mock()
        mock_tickets_adapter.create.return_value = "DBC-200"

        result = await create_ticket.execute(
            title=f"Ticket with {priority_str} priority",
            description=None,
            priority=priority_str,
            labels=None,
            agent_name="mason",
            registry=registry_with_tickets,
        )

        assert result["created"] is True
        mock_tickets_adapter.create.assert_called_once_with(
            f"Ticket with {priority_str} priority",
            description=None,
            team_id=None,
            priority=priority_int,
            labels=None,
        )


@pytest.mark.asyncio
async def test_create_ticket_priority_case_insensitive(
    registry_with_tickets, mock_tickets_adapter
):
    """Test that priority matching is case-insensitive."""
    result = await create_ticket.execute(
        title="Test ticket",
        description=None,
        priority="HIGH",
        labels=None,
        agent_name="mason",
        registry=registry_with_tickets,
    )

    assert result["created"] is True
    mock_tickets_adapter.create.assert_called_once_with(
        "Test ticket",
        description=None,
        team_id=None,
        priority=2,
        labels=None,
    )


@pytest.mark.asyncio
async def test_create_ticket_adapter_error(registry_with_tickets, mock_tickets_adapter):
    """Test graceful handling when adapter raises an exception."""
    mock_tickets_adapter.create.side_effect = Exception("Linear API timeout")

    result = await create_ticket.execute(
        title="Test ticket",
        description=None,
        priority=None,
        labels=None,
        agent_name="mason",
        registry=registry_with_tickets,
    )

    assert result["created"] is False
    assert "Adapter error" in result["error"]
    assert "Linear API timeout" in result["error"]


@pytest.mark.asyncio
async def test_create_ticket_without_store(registry_tickets_only, mock_tickets_adapter):
    """Test ticket creation succeeds even without a local store."""
    result = await create_ticket.execute(
        title="Test ticket",
        description="No store available",
        priority="normal",
        labels=None,
        agent_name="mason",
        registry=registry_tickets_only,
    )

    assert result["created"] is True
    assert result["ticket_id"] == "DBC-200"

    # Adapter should still have been called
    mock_tickets_adapter.create.assert_called_once()


@pytest.mark.asyncio
async def test_create_ticket_agent_name_in_event(registry_with_tickets, mock_store):
    """Test that agent_name appears in the ticket event note."""
    await create_ticket.execute(
        title="Test ticket",
        description=None,
        priority=None,
        labels=None,
        agent_name="steve",
        registry=registry_with_tickets,
    )

    events = mock_store.events(TicketEvent, entity_id="DBC-200")
    assert len(events) == 1
    assert "steve" in events[0].note


@pytest.mark.asyncio
async def test_create_ticket_unknown_agent(registry_with_tickets, mock_store):
    """Test that None agent_name records 'unknown' in event."""
    await create_ticket.execute(
        title="Test ticket",
        description=None,
        priority=None,
        labels=None,
        agent_name=None,
        registry=registry_with_tickets,
    )

    events = mock_store.events(TicketEvent, entity_id="DBC-200")
    assert len(events) == 1
    assert "unknown" in events[0].note
