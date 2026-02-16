"""Tests for herd_assign tool."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from herd_core.types import (
    AgentRecord,
    AgentState,
    TicketEvent,
    TicketRecord,
)
from herd_mcp.adapters import AdapterRegistry
from herd_mcp.tools import assign


@pytest.fixture
def mock_registry(mock_store):
    """Provide an AdapterRegistry with MockStore for assign tool tests."""
    return AdapterRegistry(store=mock_store, write_lock=asyncio.Lock())


@pytest.fixture
def seeded_store(mock_store):
    """Seed the mock store with test data for assign tool."""
    # Seed tickets
    mock_store.save(
        TicketRecord(
            id="DBC-100",
            title="Test ticket",
            description="Test description",
            status="backlog",
        )
    )
    mock_store.save(
        TicketRecord(
            id="DBC-101",
            title="Another ticket",
            description="Another description",
            status="backlog",
        )
    )

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


@pytest.mark.asyncio
async def test_assign_success_with_instance(seeded_registry, seeded_store):
    """Test successful ticket assignment with active agent instance."""
    with patch("herd_mcp.linear_client.is_linear_identifier", return_value=False):
        result = await assign.execute(
            ticket_id="DBC-100",
            agent_name="mason",
            priority="high",
            registry=seeded_registry,
        )

        assert result["assigned"] is True
        assert result["agent"] == "mason"
        assert result["ticket"]["id"] == "DBC-100"
        assert result["ticket"]["title"] == "Test ticket"
        assert result["priority"] == "high"
        assert result["agent_instance_code"] == "inst-001"
        assert result["note"] is None

        # Verify ticket status was updated
        ticket = seeded_store.get(TicketRecord, "DBC-100")
        assert ticket.status == "assigned"

        # Verify activity was recorded
        events = seeded_store.events(TicketEvent, entity_id="DBC-100")
        assert len(events) == 1
        assert events[0].event_type == "assigned"
        assert events[0].new_status == "assigned"
        assert "high" in events[0].note


@pytest.mark.asyncio
async def test_assign_without_agent_instance(seeded_registry, seeded_store):
    """Test ticket assignment when agent has no active instance."""
    with patch("herd_mcp.linear_client.is_linear_identifier", return_value=False):
        result = await assign.execute(
            ticket_id="DBC-101",
            agent_name="fresco",  # Has no active instance
            priority="medium",
            registry=seeded_registry,
        )

        # Should still succeed but note the missing instance
        assert result["assigned"] is True
        assert result["agent"] == "fresco"
        assert result["agent_instance_code"] is None
        assert result["note"] == "No active agent instance found"

        # Verify ticket status was updated
        ticket = seeded_store.get(TicketRecord, "DBC-101")
        assert ticket.status == "assigned"

        # Verify activity was recorded (with empty agent_instance_code)
        events = seeded_store.events(TicketEvent, entity_id="DBC-101")
        assert len(events) == 1
        assert events[0].instance_id == ""
        assert events[0].entity_id == "DBC-101"
        assert events[0].event_type == "assigned"
        assert events[0].new_status == "assigned"


@pytest.mark.asyncio
async def test_assign_missing_agent_name(seeded_registry):
    """Test ticket assignment without agent name."""
    result = await assign.execute(
        ticket_id="DBC-100",
        agent_name=None,
        priority="high",
        registry=seeded_registry,
    )

    assert result["assigned"] is False
    assert "error" in result
    assert "agent_name is required" in result["error"]


@pytest.mark.asyncio
async def test_assign_ticket_not_found(seeded_registry):
    """Test ticket assignment for nonexistent ticket."""
    with patch("herd_mcp.linear_client.is_linear_identifier", return_value=False):
        result = await assign.execute(
            ticket_id="NONEXISTENT",
            agent_name="mason",
            priority="high",
            registry=seeded_registry,
        )

        assert result["assigned"] is False
        assert "error" in result
        assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_assign_agent_not_in_store(seeded_registry):
    """Test ticket assignment to agent with no instances in store.

    The new adapter-based assign tool does not check an agent definition table.
    It simply proceeds with agent_instance_code=None and sets a note.
    """
    with patch("herd_mcp.linear_client.is_linear_identifier", return_value=False):
        result = await assign.execute(
            ticket_id="DBC-100",
            agent_name="nonexistent",
            priority="high",
            registry=seeded_registry,
        )

        # Assignment succeeds even without a running instance
        assert result["assigned"] is True
        assert result["agent_instance_code"] is None
        assert result["note"] == "No active agent instance found"


@pytest.mark.asyncio
async def test_assign_no_running_instance(seeded_registry, seeded_store):
    """Test ticket assignment when agent has an instance but not running."""
    # Add a stopped instance for fresco
    seeded_store.save(
        AgentRecord(
            id="inst-fresco-001",
            agent="fresco",
            model="claude-sonnet-4",
            state=AgentState.STOPPED,
        )
    )

    with patch("herd_mcp.linear_client.is_linear_identifier", return_value=False):
        result = await assign.execute(
            ticket_id="DBC-100",
            agent_name="fresco",
            priority="high",
            registry=seeded_registry,
        )

        # Assignment succeeds but agent_instance_code is None (no RUNNING instance)
        assert result["assigned"] is True
        assert result["agent_instance_code"] is None
        assert result["note"] == "No active agent instance found"


@pytest.mark.asyncio
async def test_assign_updates_modified_at(seeded_registry, seeded_store):
    """Test that ticket modified_at is updated on assignment."""
    with patch("herd_mcp.linear_client.is_linear_identifier", return_value=False):
        result = await assign.execute(
            ticket_id="DBC-100",
            agent_name="mason",
            priority="high",
            registry=seeded_registry,
        )

        assert result["assigned"] is True

        # Verify modified_at was set (MockStore.save sets it)
        ticket = seeded_store.get(TicketRecord, "DBC-100")
        assert ticket.modified_at is not None


@pytest.mark.asyncio
async def test_assign_auto_register_from_linear(seeded_registry, seeded_store):
    """Test auto-registration of ticket from Linear when not in DB."""
    linear_issue = {
        "id": "linear-uuid-123",
        "identifier": "DBC-125",
        "title": "New ticket from Linear",
        "description": "Fetched from Linear API",
        "state": {"name": "Backlog"},
        "project": {"id": "proj-1", "name": "MCP Server"},
    }

    with patch("herd_mcp.linear_client.is_linear_identifier", return_value=True):
        with patch("herd_mcp.linear_client.get_issue", return_value=linear_issue):
            result = await assign.execute(
                ticket_id="DBC-125",
                agent_name="mason",
                priority="high",
                registry=seeded_registry,
            )

            assert result["assigned"] is True
            assert result["ticket"]["id"] == "DBC-125"
            assert result["ticket"]["title"] == "New ticket from Linear"

            # Verify ticket was saved to store
            ticket = seeded_store.get(TicketRecord, "DBC-125")
            assert ticket is not None
            assert ticket.id == "DBC-125"
            assert ticket.title == "New ticket from Linear"


@pytest.mark.asyncio
async def test_assign_linear_sync_success(seeded_registry, seeded_store):
    """Test successful Linear sync on assignment."""
    # Add a tickets adapter to the registry for Linear sync
    mock_tickets = MagicMock()
    seeded_registry.tickets = mock_tickets

    with patch("herd_mcp.linear_client.is_linear_identifier", return_value=True):
        result = await assign.execute(
            ticket_id="DBC-100",
            agent_name="mason",
            priority="high",
            registry=seeded_registry,
        )

        assert result["assigned"] is True
        assert result["linear_synced"] is True

        # Verify ticket adapter transition was called
        mock_tickets.transition.assert_called_once_with("DBC-100", "assigned")


@pytest.mark.asyncio
async def test_assign_linear_sync_failure(seeded_registry, seeded_store):
    """Test graceful handling of Linear sync failure."""
    with patch("herd_mcp.linear_client.is_linear_identifier", return_value=True):
        with patch(
            "herd_mcp.linear_client.get_issue", side_effect=Exception("API error")
        ):
            result = await assign.execute(
                ticket_id="DBC-100",
                agent_name="mason",
                priority="high",
                registry=seeded_registry,
            )

            # Assignment should still succeed
            assert result["assigned"] is True
            assert result["linear_synced"] is False
            assert "linear_sync_error" in result


@pytest.mark.asyncio
async def test_assign_non_linear_ticket_no_sync(seeded_registry, seeded_store):
    """Test that non-Linear tickets don't attempt sync."""
    # Insert a non-Linear style ticket
    seeded_store.save(
        TicketRecord(
            id="INTERNAL-001",
            title="Internal ticket",
            status="backlog",
        )
    )

    with patch("herd_mcp.linear_client.is_linear_identifier", return_value=False):
        with patch("herd_mcp.linear_client.get_issue") as mock_get:
            result = await assign.execute(
                ticket_id="INTERNAL-001",
                agent_name="mason",
                priority="normal",
                registry=seeded_registry,
            )

            assert result["assigned"] is True
            assert result["linear_synced"] is False
            # Linear API should not have been called
            mock_get.assert_not_called()
