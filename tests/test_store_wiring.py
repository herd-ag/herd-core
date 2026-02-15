"""Tests for StoreAdapter wiring in MCP tools.

These tests verify that:
1. Tools accept the registry parameter
2. Tools fall back to SQL when adapter unavailable
3. Server initializes registry with all adapter slots
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from herd_mcp.adapters import AdapterRegistry
from herd_mcp.tools import assign, lifecycle, log, metrics, record_decision, status, transition


@pytest.fixture
def seeded_db(in_memory_db):
    """Provide a database with test data."""
    conn = in_memory_db

    # Insert test agent
    conn.execute("""
        INSERT INTO herd.agent_def
          (agent_code, agent_role, agent_status, created_at)
        VALUES ('grunt', 'backend', 'active', CURRENT_TIMESTAMP)
        """)

    # Insert test agent instance
    conn.execute("""
        INSERT INTO herd.agent_instance
          (agent_instance_code, agent_code, model_code, agent_instance_started_at)
        VALUES ('inst-001', 'grunt', 'claude-sonnet-4', CURRENT_TIMESTAMP)
        """)

    # Insert test ticket
    conn.execute("""
        INSERT INTO herd.ticket_def
          (ticket_code, ticket_title, ticket_description, ticket_current_status, created_at)
        VALUES ('DBC-148', 'Test Ticket', 'Test description', 'backlog', CURRENT_TIMESTAMP)
        """)

    yield conn


# Lifecycle tests - verify SQL fallback works


@pytest.mark.asyncio
async def test_lifecycle_decommission_fallback_to_sql(seeded_db):
    """Test decommission falls back to SQL when StoreAdapter unavailable."""
    registry = AdapterRegistry()  # No store adapter

    with patch("herd_mcp.tools.lifecycle.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await lifecycle.decommission("grunt", "mini-mao", registry)

        assert result["success"] is True
        assert result["target_agent"] == "grunt"


@pytest.mark.asyncio
async def test_lifecycle_standdown_fallback_to_sql(seeded_db):
    """Test standdown falls back to SQL when StoreAdapter unavailable."""
    registry = AdapterRegistry()

    with patch("herd_mcp.tools.lifecycle.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await lifecycle.standdown("grunt", "mini-mao", registry)

        assert result["success"] is True
        assert result["target_agent"] == "grunt"


# Log tests


@pytest.mark.asyncio
async def test_log_fallback_to_sql(seeded_db):
    """Test log falls back to SQL when StoreAdapter unavailable."""
    registry = AdapterRegistry()

    with patch("herd_mcp.tools.log.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch("herd_mcp.tools.log._post_to_slack") as mock_slack:
            mock_slack.return_value = {"success": True, "response": {"ok": True}}

            result = await log.execute(
                message="Test message",
                channel="#herd-feed",
                await_response=False,
                agent_name="grunt",
                registry=registry,
            )

            assert result["posted"] is True


# Assign tests


@pytest.mark.asyncio
async def test_assign_fallback_to_sql(seeded_db):
    """Test assign falls back to SQL when StoreAdapter unavailable."""
    registry = AdapterRegistry()

    with patch("herd_mcp.tools.assign.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await assign.execute("DBC-148", "grunt", "normal", registry)

        assert result["assigned"] is True


# Transition tests


@pytest.mark.asyncio
async def test_transition_fallback_to_sql(seeded_db):
    """Test transition falls back to SQL when StoreAdapter unavailable."""
    registry = AdapterRegistry()

    with patch("herd_mcp.tools.transition.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await transition.execute("DBC-148", "in_progress", None, None, "grunt", registry)

        assert result["ticket"]["id"] == "DBC-148"


# Record decision tests


@pytest.mark.asyncio
async def test_record_decision_fallback_to_sql(in_memory_db):
    """Test record_decision falls back to SQL when StoreAdapter unavailable."""
    registry = AdapterRegistry()

    with patch("herd_mcp.tools.record_decision.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=in_memory_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await record_decision.execute(
            decision_type="implementation",
            context="Test context",
            decision="Test decision",
            rationale="Test rationale",
            alternatives_considered=None,
            ticket_code="DBC-148",
            agent_name="grunt",
            registry=registry,
        )

        assert result["success"] is True


# Status and Metrics tests (complex queries - kept as raw SQL)


@pytest.mark.asyncio
async def test_status_with_registry(seeded_db):
    """Test status accepts registry but uses SQL for complex queries."""
    registry = AdapterRegistry()

    with patch("herd_mcp.tools.status.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await status.execute("all", "grunt", registry)

        assert result["scope"] == "all"
        assert "agents" in result


@pytest.mark.asyncio
async def test_metrics_with_registry(seeded_db):
    """Test metrics accepts registry but uses SQL for complex queries."""
    registry = AdapterRegistry()

    with patch("herd_mcp.tools.metrics.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await metrics.execute("cost_per_ticket", None, None, "grunt", registry)

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
