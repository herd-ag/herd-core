"""Tests for StoreAdapter wiring in MCP tools.

These tests verify that:
1. Tools accept the registry parameter
2. Tools use StoreAdapter when provided via registry
3. Tools return error when registry/store is not configured
4. Server initializes registry with all adapter slots
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from herd_core.types import (
    AgentRecord,
    AgentState,
    TicketRecord,
)
from herd_mcp.adapters import AdapterRegistry
from herd_mcp.tools import (
    assign,
    lifecycle,
    log,
    metrics,
    record_decision,
    status,
    transition,
)


@pytest.fixture
def mock_registry(mock_store):
    """Create an AdapterRegistry with MockStore."""
    return AdapterRegistry(store=mock_store, write_lock=asyncio.Lock())


@pytest.fixture
def seeded_store(mock_store):
    """Seed mock_store with test data."""
    mock_store.save(
        AgentRecord(
            id="inst-001",
            agent="mason",
            model="claude-sonnet-4",
            state=AgentState.RUNNING,
            started_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    mock_store.save(
        TicketRecord(
            id="DBC-148",
            title="Test Ticket",
            description="Test description",
            status="backlog",
        )
    )
    return mock_store


@pytest.fixture
def seeded_registry(seeded_store):
    """Create an AdapterRegistry with seeded MockStore."""
    return AdapterRegistry(store=seeded_store, write_lock=asyncio.Lock())


# Lifecycle tests - verify tools work with StoreAdapter


@pytest.mark.asyncio
async def test_lifecycle_decommission_with_store(seeded_store, seeded_registry):
    """Test decommission works with StoreAdapter."""
    result = await lifecycle.decommission("mason", "steve", seeded_registry)

    assert result["success"] is True
    assert result["target_agent"] == "mason"


@pytest.mark.asyncio
async def test_lifecycle_standdown_with_store(seeded_store, seeded_registry):
    """Test standdown works with StoreAdapter."""
    result = await lifecycle.standdown("mason", "steve", seeded_registry)

    assert result["success"] is True
    assert result["target_agent"] == "mason"


@pytest.mark.asyncio
async def test_lifecycle_decommission_no_store():
    """Test decommission returns error when StoreAdapter unavailable."""
    registry = AdapterRegistry()  # No store adapter

    result = await lifecycle.decommission("mason", "steve", registry)

    assert "error" in result
    assert result["error"] == "StoreAdapter not configured"


@pytest.mark.asyncio
async def test_lifecycle_standdown_no_store():
    """Test standdown returns error when StoreAdapter unavailable."""
    registry = AdapterRegistry()

    result = await lifecycle.standdown("mason", "steve", registry)

    assert "error" in result
    assert result["error"] == "StoreAdapter not configured"


# Log tests


@pytest.mark.asyncio
async def test_log_with_store(seeded_store, seeded_registry):
    """Test log works with StoreAdapter."""
    with patch("herd_mcp.tools.log._post_to_slack") as mock_slack:
        mock_slack.return_value = {"success": True, "response": {"ok": True}}

        result = await log.execute(
            message="Test message",
            channel="#herd-feed",
            await_response=False,
            agent_name="mason",
            registry=seeded_registry,
        )

        assert result["posted"] is True


# Assign tests


@pytest.mark.asyncio
async def test_assign_with_store(seeded_store, seeded_registry):
    """Test assign works with StoreAdapter."""
    with patch("herd_mcp.linear_client.is_linear_identifier", return_value=False):
        result = await assign.execute("DBC-148", "mason", "normal", seeded_registry)

    assert result["assigned"] is True


# Transition tests


@pytest.mark.asyncio
async def test_transition_with_store(seeded_store, seeded_registry):
    """Test transition works with StoreAdapter."""
    with patch("herd_mcp.linear_client.is_linear_identifier", return_value=False):
        result = await transition.execute(
            "DBC-148", "in_progress", None, None, "mason", seeded_registry
        )

    assert result["ticket"]["id"] == "DBC-148"


# Record decision tests


@pytest.mark.asyncio
async def test_record_decision_with_store(mock_store, mock_registry):
    """Test record_decision works with StoreAdapter."""
    with patch("herd_mcp.tools.record_decision._post_to_slack_decisions") as mock_slack:
        mock_slack.return_value = {"success": True}

        result = await record_decision.execute(
            decision_type="implementation",
            context="Test context",
            decision="Test decision",
            rationale="Test rationale",
            alternatives_considered=None,
            ticket_code="DBC-148",
            agent_name="mason",
            registry=mock_registry,
        )

    assert result["success"] is True


# Status and Metrics tests


@pytest.mark.asyncio
async def test_status_with_registry(seeded_store, seeded_registry):
    """Test status works with StoreAdapter."""
    result = await status.execute("all", "mason", seeded_registry)

    assert result["scope"] == "all"
    assert "agents" in result


@pytest.mark.asyncio
async def test_metrics_with_registry(seeded_store, seeded_registry):
    """Test metrics works with StoreAdapter."""
    result = await metrics.execute(
        "cost_per_ticket", None, None, "mason", seeded_registry
    )

    assert "data" in result
    assert "summary" in result


# Registry initialization test


def test_adapter_registry_has_all_slots():
    """Test that AdapterRegistry dataclass has all expected slots."""
    registry = AdapterRegistry()

    assert registry is not None
    assert hasattr(registry, "notify")
    assert hasattr(registry, "tickets")
    assert hasattr(registry, "store")
    assert hasattr(registry, "repo")
    assert hasattr(registry, "agent")

    # All should be None by default
    assert registry.notify is None
    assert registry.tickets is None
    assert registry.store is None
    assert registry.repo is None
    assert registry.agent is None


# Server registry parameter tests


def test_lifecycle_decommission_signature():
    """Verify decommission accepts registry parameter."""
    import inspect

    sig = inspect.signature(lifecycle.decommission)
    assert "registry" in sig.parameters


def test_lifecycle_standdown_signature():
    """Verify standdown accepts registry parameter."""
    import inspect

    sig = inspect.signature(lifecycle.standdown)
    assert "registry" in sig.parameters


def test_log_execute_signature():
    """Verify log.execute accepts registry parameter."""
    import inspect

    sig = inspect.signature(log.execute)
    assert "registry" in sig.parameters


def test_assign_execute_signature():
    """Verify assign.execute accepts registry parameter."""
    import inspect

    sig = inspect.signature(assign.execute)
    assert "registry" in sig.parameters


def test_transition_execute_signature():
    """Verify transition.execute accepts registry parameter."""
    import inspect

    sig = inspect.signature(transition.execute)
    assert "registry" in sig.parameters


def test_record_decision_execute_signature():
    """Verify record_decision.execute accepts registry parameter."""
    import inspect

    sig = inspect.signature(record_decision.execute)
    assert "registry" in sig.parameters


def test_status_execute_signature():
    """Verify status.execute accepts registry parameter."""
    import inspect

    sig = inspect.signature(status.execute)
    assert "registry" in sig.parameters


def test_metrics_execute_signature():
    """Verify metrics.execute accepts registry parameter."""
    import inspect

    sig = inspect.signature(metrics.execute)
    assert "registry" in sig.parameters
