"""Simplified tests for herd_transition tool."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from herd_core.types import (
    AgentRecord,
    AgentState,
    TicketEvent,
    TicketRecord,
)
from herd_mcp.adapters import AdapterRegistry
from herd_mcp.tools import transition


@pytest.fixture
def mock_registry(mock_store):
    """Create an AdapterRegistry with MockStore."""
    return AdapterRegistry(store=mock_store, write_lock=asyncio.Lock())


@pytest.fixture
def seeded_store(mock_store):
    """Seed mock_store with test data for transition tool."""
    # Insert test tickets
    mock_store.save(
        TicketRecord(
            id="DBC-100",
            title="Test ticket",
            status="in_progress",
        )
    )
    mock_store.save(
        TicketRecord(
            id="DBC-101",
            title="Another ticket",
            status="backlog",
        )
    )

    # Insert test agent instance
    mock_store.save(
        AgentRecord(
            id="inst-001",
            agent="mason",
            model="claude-sonnet-4",
            state=AgentState.RUNNING,
            started_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )

    # Insert initial ticket activity for DBC-100
    mock_store.append(
        TicketEvent(
            entity_id="DBC-100",
            event_type="status_changed",
            instance_id="inst-001",
            previous_status="backlog",
            new_status="in_progress",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=30),
        )
    )

    return mock_store


@pytest.fixture
def seeded_registry(seeded_store):
    """Create an AdapterRegistry with seeded MockStore."""
    return AdapterRegistry(store=seeded_store, write_lock=asyncio.Lock())


@pytest.mark.asyncio
async def test_transition_success(seeded_store, seeded_registry):
    """Test successful ticket transition."""
    result = await transition.execute(
        ticket_id="DBC-100",
        to_status="done",
        blocked_by=None,
        note="Work completed",
        agent_name="mason",
        registry=seeded_registry,
    )

    assert result["transition_id"] is not None
    assert result["ticket"]["id"] == "DBC-100"
    assert result["ticket"]["previous_status"] == "in_progress"
    assert result["ticket"]["new_status"] == "done"
    assert result["event_type"] == "status_changed"
    assert result["agent"] == "mason"

    # Verify ticket status was updated
    ticket = seeded_store.get(TicketRecord, "DBC-100")
    assert ticket.status == "done"


@pytest.mark.asyncio
async def test_transition_to_blocked(seeded_store, seeded_registry):
    """Test transitioning ticket to blocked status."""
    result = await transition.execute(
        ticket_id="DBC-100",
        to_status="blocked",
        blocked_by="DBC-101",
        note="Waiting for DBC-101",
        agent_name="mason",
        registry=seeded_registry,
    )

    assert result["event_type"] == "blocked"
    assert result["blocked_by"] == "DBC-101"
    assert result["ticket"]["new_status"] == "blocked"


@pytest.mark.asyncio
async def test_transition_ticket_not_found(seeded_store, seeded_registry):
    """Test transition for nonexistent ticket."""
    with patch("herd_mcp.linear_client.is_linear_identifier", return_value=False):
        result = await transition.execute(
            ticket_id="NONEXISTENT",
            to_status="done",
            blocked_by=None,
            note=None,
            agent_name="mason",
            registry=seeded_registry,
        )

    assert result["transition_id"] is None
    assert "error" in result


@pytest.mark.asyncio
async def test_transition_without_agent(seeded_store, seeded_registry):
    """Test transition when no agent specified."""
    result = await transition.execute(
        ticket_id="DBC-101",
        to_status="in_progress",
        blocked_by=None,
        note="System transition",
        agent_name=None,
        registry=seeded_registry,
    )

    assert result["transition_id"] is not None
    assert result["agent"] is None
    assert result["agent_instance_code"] is None

    # Verify ticket status was updated
    ticket = seeded_store.get(TicketRecord, "DBC-101")
    assert ticket.status == "in_progress"

    # Verify activity WAS recorded (with empty instance_id)
    events = seeded_store.events(TicketEvent, entity_id="DBC-101")
    assert len(events) >= 1
    latest = events[-1]
    assert latest.entity_id == "DBC-101"
    assert latest.event_type == "status_changed"
    assert latest.new_status == "in_progress"
    assert latest.instance_id == ""  # No agent instance


@pytest.mark.asyncio
async def test_transition_linear_sync_success(seeded_store, seeded_registry):
    """Test successful Linear sync on transition."""
    linear_issue = {
        "id": "linear-uuid-100",
        "identifier": "DBC-100",
    }

    with patch("herd_mcp.tools.transition.get_manager") as mock_manager:
        mock_manager.return_value.trigger_refresh = AsyncMock(
            return_value={"status": "success"}
        )

        with patch("herd_mcp.linear_client.is_linear_identifier", return_value=True):
            with patch("herd_mcp.linear_client.get_issue", return_value=linear_issue):
                with patch("herd_mcp.linear_client.update_issue_state") as mock_update:
                    result = await transition.execute(
                        ticket_id="DBC-100",
                        to_status="done",
                        blocked_by=None,
                        note="Completed",
                        agent_name="mason",
                        registry=seeded_registry,
                    )

                    assert result["transition_id"] is not None
                    assert result["linear_synced"] is True
                    assert result["ticket"]["new_status"] == "done"

                    # Verify Linear API was called with correct state
                    mock_update.assert_called_once_with(
                        "linear-uuid-100",
                        "42bad6cf-cfb7-4dd2-9dc4-c0c3014bfc5f",  # Done state
                    )


@pytest.mark.asyncio
async def test_transition_linear_sync_failure(seeded_store, seeded_registry):
    """Test graceful handling of Linear sync failure."""
    linear_issue = {
        "id": "linear-uuid-100",
        "identifier": "DBC-100",
    }

    with patch("herd_mcp.tools.transition.get_manager") as mock_manager:
        mock_manager.return_value.trigger_refresh = AsyncMock(
            return_value={"status": "success"}
        )

        with patch("herd_mcp.linear_client.is_linear_identifier", return_value=True):
            with patch("herd_mcp.linear_client.get_issue", return_value=linear_issue):
                with patch(
                    "herd_mcp.linear_client.update_issue_state",
                    side_effect=Exception("API error"),
                ):
                    result = await transition.execute(
                        ticket_id="DBC-100",
                        to_status="done",
                        blocked_by=None,
                        note="Completed",
                        agent_name="mason",
                        registry=seeded_registry,
                    )

                    # Transition should still succeed in store
                    assert result["transition_id"] is not None
                    assert result["linear_synced"] is False
                    assert "linear_sync_error" in result

                    # Verify store was updated despite Linear failure
                    ticket = seeded_store.get(TicketRecord, "DBC-100")
                    assert ticket.status == "done"


@pytest.mark.asyncio
async def test_transition_non_linear_ticket_no_sync(seeded_store, seeded_registry):
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
            result = await transition.execute(
                ticket_id="INTERNAL-001",
                to_status="in_progress",
                blocked_by=None,
                note="Starting work",
                agent_name="mason",
                registry=seeded_registry,
            )

            assert result["transition_id"] is not None
            assert result["linear_synced"] is False
            # Linear API should not have been called
            mock_get.assert_not_called()

            # Verify store was updated
            ticket = seeded_store.get(TicketRecord, "INTERNAL-001")
            assert ticket.status == "in_progress"


@pytest.mark.asyncio
async def test_transition_unmapped_status_no_sync(seeded_store, seeded_registry):
    """Test that unmapped statuses don't attempt Linear sync."""
    with patch("herd_mcp.linear_client.is_linear_identifier", return_value=True):
        with patch("herd_mcp.linear_client.get_issue") as mock_get:
            with patch("herd_mcp.linear_client.update_issue_state") as mock_update:
                result = await transition.execute(
                    ticket_id="DBC-100",
                    to_status="blocked",
                    blocked_by="DBC-101",
                    note="Waiting on dependency",
                    agent_name="mason",
                    registry=seeded_registry,
                )

                assert result["transition_id"] is not None
                assert result["linear_synced"] is False
                assert result["event_type"] == "blocked"

                # Linear get_issue should not be called for unmapped status
                mock_get.assert_not_called()
                mock_update.assert_not_called()

                # Verify store was updated
                ticket = seeded_store.get(TicketRecord, "DBC-100")
                assert ticket.status == "blocked"
