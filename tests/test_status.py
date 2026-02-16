"""Tests for herd_status tool."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from herd_core.types import (
    AgentRecord,
    AgentState,
    SprintRecord,
    TicketEvent,
    TicketRecord,
)
from herd_mcp.adapters import AdapterRegistry
from herd_mcp.tools import status


@pytest.fixture
def mock_registry(mock_store):
    """Provide an AdapterRegistry with MockStore for status tool tests."""
    return AdapterRegistry(store=mock_store, write_lock=asyncio.Lock())


@pytest.fixture
def seeded_store(mock_store):
    """Seed the mock store with test data for status tool."""
    # Seed agent instances (representing the active roster)
    mock_store.save(
        AgentRecord(
            id="inst-001",
            agent="mason",
            model="claude-sonnet-4",
            state=AgentState.RUNNING,
            ticket_id="DBC-91",
            started_at=datetime.now(timezone.utc),
        )
    )
    mock_store.save(
        AgentRecord(
            id="inst-fresco",
            agent="fresco",
            model="claude-sonnet-4",
            state=AgentState.STOPPED,
        )
    )
    mock_store.save(
        AgentRecord(
            id="inst-steve",
            agent="steve",
            model="claude-opus-4",
            state=AgentState.STOPPED,
        )
    )

    # Seed sprint
    mock_store.save(
        SprintRecord(
            id="SP-001",
            name="Sprint 1",
            goal="Build core tools",
            status="active",
            started_at=datetime.now(timezone.utc),
        )
    )

    # Seed tickets
    mock_store.save(
        TicketRecord(
            id="DBC-91",
            title="Core tools",
            description="Implement core MCP tools",
            status="in_progress",
        )
    )
    mock_store.save(
        TicketRecord(
            id="DBC-92",
            title="Documentation",
            description="Write docs",
            status="backlog",
        )
    )
    mock_store.save(
        TicketRecord(
            id="DBC-93",
            title="Blocked ticket",
            description="Cannot proceed",
            status="blocked",
        )
    )

    # Seed ticket activity for blocked ticket
    mock_store.append(
        TicketEvent(
            entity_id="DBC-93",
            event_type="blocked",
            instance_id="inst-001",
            previous_status="in_progress",
            new_status="blocked",
            note="Waiting for core tools",
            blocked_by=["DBC-91"],
            created_at=datetime.now(timezone.utc),
        )
    )

    return mock_store


@pytest.fixture
def seeded_registry(seeded_store):
    """Provide an AdapterRegistry with seeded MockStore."""
    return AdapterRegistry(store=seeded_store, write_lock=asyncio.Lock())


@pytest.mark.asyncio
async def test_status_scope_all(seeded_registry):
    """Test status query with scope='all'."""
    with patch("herd_mcp.graph.is_available", return_value=False):
        result = await status.execute(
            scope="all", agent_name="steve", registry=seeded_registry
        )

    assert result["scope"] == "all"
    assert "agents" in result
    assert "sprint" in result
    assert "blockers" in result
    assert result["requesting_agent"] == "steve"

    # Check agents -- we have 3 agents (mason, fresco, steve)
    assert len(result["agents"]) == 3
    agent_codes = [a["agent_code"] for a in result["agents"]]
    assert "mason" in agent_codes
    assert "fresco" in agent_codes
    assert "steve" in agent_codes

    # Check that mason has assignment (running with ticket_id)
    mason = next(a for a in result["agents"] if a["agent_code"] == "mason")
    assert mason["current_assignment"] is not None
    assert mason["current_assignment"]["ticket_code"] == "DBC-91"

    # Check sprint
    assert result["sprint"] is not None
    assert result["sprint"]["sprint_code"] == "SP-001"
    # All 3 active tickets appear in the sprint listing
    assert len(result["sprint"]["tickets"]) == 3

    # Check blockers
    assert len(result["blockers"]) == 1
    assert result["blockers"][0]["ticket_code"] == "DBC-93"
    assert result["blockers"][0]["blocker_ticket_code"] == "DBC-91"


@pytest.mark.asyncio
async def test_status_scope_sprint(seeded_registry):
    """Test status query with scope='sprint'."""
    result = await status.execute(
        scope="sprint", agent_name="steve", registry=seeded_registry
    )

    assert result["scope"] == "sprint"
    assert "sprint" in result
    assert "agents" not in result
    assert "blockers" not in result

    assert result["sprint"]["sprint_code"] == "SP-001"
    assert len(result["sprint"]["tickets"]) == 3


@pytest.mark.asyncio
async def test_status_scope_agent(seeded_registry):
    """Test status query with scope='agent:<name>'."""
    result = await status.execute(
        scope="agent:mason", agent_name="steve", registry=seeded_registry
    )

    assert result["scope"] == "agent:mason"
    assert "agent_status" in result

    agent_status = result["agent_status"]
    assert agent_status["agent_code"] == "mason"
    assert agent_status["agent_role"] == "mason"
    assert agent_status["agent_status"] == "running"
    assert len(agent_status["recent_instances"]) == 1
    assert agent_status["recent_instances"][0]["ticket_code"] == "DBC-91"


@pytest.mark.asyncio
async def test_status_scope_agent_not_found(seeded_registry):
    """Test status query for nonexistent agent."""
    result = await status.execute(
        scope="agent:nonexistent", agent_name="steve", registry=seeded_registry
    )

    assert result["scope"] == "agent:nonexistent"
    assert "agent_status" in result
    assert "error" in result["agent_status"]


@pytest.mark.asyncio
async def test_status_scope_ticket(seeded_registry):
    """Test status query with scope='ticket:<id>'."""
    result = await status.execute(
        scope="ticket:DBC-91", agent_name="steve", registry=seeded_registry
    )

    assert result["scope"] == "ticket:DBC-91"
    assert "ticket_status" in result

    ticket_status = result["ticket_status"]
    assert ticket_status["ticket_code"] == "DBC-91"
    assert ticket_status["ticket_title"] == "Core tools"
    assert ticket_status["current_status"] == "in_progress"
    # sprint_code is None in the new types -- no sprint link on TicketRecord
    assert ticket_status["sprint_code"] is None


@pytest.mark.asyncio
async def test_status_scope_ticket_not_found(seeded_registry):
    """Test status query for nonexistent ticket."""
    result = await status.execute(
        scope="ticket:NONEXISTENT", agent_name="steve", registry=seeded_registry
    )

    assert result["scope"] == "ticket:NONEXISTENT"
    assert "ticket_status" in result
    assert "error" in result["ticket_status"]


@pytest.mark.asyncio
async def test_status_scope_available(seeded_registry):
    """Test status query with scope='available'."""
    result = await status.execute(
        scope="available", agent_name="steve", registry=seeded_registry
    )

    assert result["scope"] == "available"
    assert "available_agents" in result

    # fresco and steve should be available (no RUNNING instances)
    available_codes = [a["agent_code"] for a in result["available_agents"]]
    assert "fresco" in available_codes
    assert "steve" in available_codes
    assert "mason" not in available_codes  # mason has running instance


@pytest.mark.asyncio
async def test_status_scope_blocked(seeded_registry):
    """Test status query with scope='blocked'."""
    result = await status.execute(
        scope="blocked", agent_name="steve", registry=seeded_registry
    )

    assert result["scope"] == "blocked"
    assert "blockers" in result
    assert len(result["blockers"]) == 1
    assert result["blockers"][0]["ticket_code"] == "DBC-93"


@pytest.mark.asyncio
async def test_status_scope_unknown_defaults_to_all(seeded_registry):
    """Test status query with unknown scope defaults to 'all'."""
    with patch("herd_mcp.graph.is_available", return_value=False):
        result = await status.execute(
            scope="unknown_scope", agent_name="steve", registry=seeded_registry
        )

    assert result["scope"] == "all"
    assert "agents" in result
    assert "sprint" in result
    assert "blockers" in result


@pytest.mark.asyncio
async def test_status_no_active_sprint(mock_registry):
    """Test status query when no active sprint exists."""
    result = await status.execute(
        scope="sprint", agent_name="steve", registry=mock_registry
    )

    assert result["scope"] == "sprint"
    assert result["sprint"] is None
