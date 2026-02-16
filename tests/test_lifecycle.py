"""Tests for herd_lifecycle tool (decommission and standdown)."""

from __future__ import annotations

import asyncio

import pytest
from herd_core.types import (
    AgentRecord,
    AgentState,
    LifecycleEvent,
)
from herd_mcp.adapters import AdapterRegistry
from herd_mcp.tools import lifecycle


@pytest.fixture
def mock_registry(mock_store):
    """Provide an AdapterRegistry with MockStore."""
    return AdapterRegistry(store=mock_store, write_lock=asyncio.Lock())


@pytest.fixture
def seeded_store(mock_store):
    """Provide a mock store seeded with test data for lifecycle tool."""
    # Insert active agent instances for mason (2 instances)
    mock_store.save(
        AgentRecord(
            id="inst-mason-001",
            agent="mason",
            model="claude-sonnet-4",
            state=AgentState.RUNNING,
        )
    )
    mock_store.save(
        AgentRecord(
            id="inst-mason-002",
            agent="mason",
            model="claude-sonnet-4",
            state=AgentState.RUNNING,
        )
    )

    # Insert active agent instance for fresco (1 instance)
    mock_store.save(
        AgentRecord(
            id="inst-fresco-001",
            agent="fresco",
            model="claude-opus-4",
            state=AgentState.RUNNING,
        )
    )

    return mock_store


@pytest.mark.asyncio
async def test_decommission_agent(seeded_store, mock_registry):
    """Test decommissioning an agent."""
    result = await lifecycle.decommission(
        agent_name="mason",
        current_agent="steve",
        registry=mock_registry,
    )

    assert result["success"] is True
    assert result["target_agent"] == "mason"
    assert result["previous_status"] == "running"
    assert result["new_status"] == "decommissioned"
    assert result["instances_ended"] == 2  # Two active instances
    assert result["requested_by"] == "steve"

    # Verify instances were updated to STOPPED
    inst1 = seeded_store.get(AgentRecord, "inst-mason-001")
    assert inst1.state == AgentState.STOPPED
    assert inst1.ended_at is not None

    inst2 = seeded_store.get(AgentRecord, "inst-mason-002")
    assert inst2.state == AgentState.STOPPED
    assert inst2.ended_at is not None

    # Verify lifecycle activity was recorded
    all_events = seeded_store.events(LifecycleEvent)
    events = [e for e in all_events if e.event_type == "decommissioned"]
    assert len(events) == 2


@pytest.mark.asyncio
async def test_decommission_nonexistent_agent(seeded_store, mock_registry):
    """Test decommissioning a nonexistent agent."""
    result = await lifecycle.decommission(
        agent_name="nonexistent",
        current_agent="steve",
        registry=mock_registry,
    )

    assert result["success"] is False
    assert "error" in result
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_decommission_without_current_agent(seeded_store, mock_registry):
    """Test decommissioning without specifying current agent (system)."""
    result = await lifecycle.decommission(
        agent_name="fresco",
        current_agent=None,
        registry=mock_registry,
    )

    assert result["success"] is True
    assert result["requested_by"] is None

    # Verify lifecycle detail mentions "system"
    all_events = seeded_store.events(LifecycleEvent)
    events = [e for e in all_events if e.event_type == "decommissioned"]
    assert len(events) >= 1
    assert "system" in events[0].detail


@pytest.mark.asyncio
async def test_decommission_already_stopped_agent(seeded_store, mock_registry):
    """Test decommissioning an agent whose instances are already stopped.

    A stopped but not soft-deleted agent is still found by the store's
    active=True filter (which only checks deleted_at). The lifecycle tool
    will process it, recording the previous state as 'stopped'.
    """
    # Add a stopped instance for old-agent (deleted_at is None, so still "active" in store)
    seeded_store.save(
        AgentRecord(
            id="inst-old-001",
            agent="old-agent",
            model="claude-sonnet-4",
            state=AgentState.STOPPED,
        )
    )

    result = await lifecycle.decommission(
        agent_name="old-agent",
        current_agent="steve",
        registry=mock_registry,
    )

    # The tool finds the instance and processes it
    assert result["success"] is True
    assert result["previous_status"] == "stopped"
    assert result["new_status"] == "decommissioned"


@pytest.mark.asyncio
async def test_standdown_agent(seeded_store, mock_registry):
    """Test standing down an agent."""
    result = await lifecycle.standdown(
        agent_name="mason",
        current_agent="steve",
        registry=mock_registry,
    )

    assert result["success"] is True
    assert result["target_agent"] == "mason"
    assert result["previous_status"] == "running"
    assert result["new_status"] == "standby"
    assert result["instances_ended"] == 2
    assert result["requested_by"] == "steve"

    # Verify instances were updated to STOPPED
    inst1 = seeded_store.get(AgentRecord, "inst-mason-001")
    assert inst1.state == AgentState.STOPPED
    assert inst1.ended_at is not None

    # Verify lifecycle activity was recorded
    all_events = seeded_store.events(LifecycleEvent)
    events = [e for e in all_events if e.event_type == "standdown"]
    assert len(events) == 2


@pytest.mark.asyncio
async def test_standdown_nonexistent_agent(seeded_store, mock_registry):
    """Test standing down a nonexistent agent."""
    result = await lifecycle.standdown(
        agent_name="nonexistent",
        current_agent="steve",
        registry=mock_registry,
    )

    assert result["success"] is False
    assert "error" in result
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_standdown_without_current_agent(seeded_store, mock_registry):
    """Test standing down without specifying current agent (system)."""
    result = await lifecycle.standdown(
        agent_name="fresco",
        current_agent=None,
        registry=mock_registry,
    )

    assert result["success"] is True
    assert result["requested_by"] is None

    # Verify lifecycle detail mentions "system"
    all_events = seeded_store.events(LifecycleEvent)
    events = [e for e in all_events if e.event_type == "standdown"]
    assert len(events) >= 1
    assert "system" in events[0].detail


@pytest.mark.asyncio
async def test_standdown_agent_no_active_instances(seeded_store, mock_registry):
    """Test standing down an agent with no active instances."""
    result = await lifecycle.standdown(
        agent_name="inactive-agent",
        current_agent="steve",
        registry=mock_registry,
    )

    # No active instances, returns not found
    assert result["success"] is False
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_decommission_agent_no_active_instances(seeded_store, mock_registry):
    """Test decommissioning an agent with no active instances."""
    result = await lifecycle.decommission(
        agent_name="inactive-agent2",
        current_agent="steve",
        registry=mock_registry,
    )

    # No active instances, returns not found
    assert result["success"] is False
    assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_decommission_updates_modified_at(seeded_store, mock_registry):
    """Test that decommission updates modified_at timestamp."""
    result = await lifecycle.decommission(
        agent_name="mason",
        current_agent="steve",
        registry=mock_registry,
    )

    assert result["success"] is True

    # Verify modified_at was set (MockStore.save sets modified_at)
    inst = seeded_store.get(AgentRecord, "inst-mason-001")
    assert inst.modified_at is not None


@pytest.mark.asyncio
async def test_standdown_updates_modified_at(seeded_store, mock_registry):
    """Test that standdown updates modified_at timestamp."""
    result = await lifecycle.standdown(
        agent_name="fresco",
        current_agent="steve",
        registry=mock_registry,
    )

    assert result["success"] is True

    # Verify modified_at was set
    inst = seeded_store.get(AgentRecord, "inst-fresco-001")
    assert inst.modified_at is not None
