"""Tests for herd_lifecycle tool (decommission and standdown)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from herd_mcp.tools import lifecycle


@pytest.fixture
def seeded_db(in_memory_db):
    """Provide a database with test data for lifecycle tool."""
    conn = in_memory_db

    # Insert test agents
    conn.execute("""
        INSERT INTO herd.agent_def
          (agent_code, agent_role, agent_status, created_at)
        VALUES
          ('grunt', 'backend', 'active', CURRENT_TIMESTAMP),
          ('pikasso', 'frontend', 'active', CURRENT_TIMESTAMP),
          ('old-agent', 'backend', 'decommissioned', CURRENT_TIMESTAMP)
        """)

    # Insert active agent instances
    conn.execute("""
        INSERT INTO herd.agent_instance
          (agent_instance_code, agent_code, model_code, agent_instance_started_at)
        VALUES
          ('inst-grunt-001', 'grunt', 'claude-sonnet-4', CURRENT_TIMESTAMP),
          ('inst-grunt-002', 'grunt', 'claude-sonnet-4', CURRENT_TIMESTAMP),
          ('inst-pikasso-001', 'pikasso', 'claude-opus-4', CURRENT_TIMESTAMP)
        """)

    yield conn


@pytest.mark.asyncio
async def test_decommission_agent(seeded_db):
    """Test decommissioning an agent."""
    with patch("herd_mcp.tools.lifecycle.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await lifecycle.decommission(
            agent_name="grunt",
            current_agent="mini-mao",
        )

        assert result["success"] is True
        assert result["target_agent"] == "grunt"
        assert result["previous_status"] == "active"
        assert result["new_status"] == "decommissioned"
        assert result["instances_ended"] == 2  # Two active instances
        assert result["requested_by"] == "mini-mao"

    # Verify agent_def was updated
    agent_status = seeded_db.execute(
        "SELECT agent_status FROM herd.agent_def WHERE agent_code = 'grunt'"
    ).fetchone()[0]
    assert agent_status == "decommissioned"

    # Verify instances were ended
    ended_count = seeded_db.execute("""
        SELECT COUNT(*)
        FROM herd.agent_instance
        WHERE agent_code = 'grunt'
          AND agent_instance_ended_at IS NOT NULL
          AND agent_instance_outcome = 'decommissioned'
        """).fetchone()[0]
    assert ended_count == 2

    # Verify lifecycle activity was recorded
    activity_count = seeded_db.execute("""
        SELECT COUNT(*)
        FROM herd.agent_instance_lifecycle_activity
        WHERE lifecycle_event_type = 'decommissioned'
        """).fetchone()[0]
    assert activity_count == 2


@pytest.mark.asyncio
async def test_decommission_nonexistent_agent(seeded_db):
    """Test decommissioning a nonexistent agent."""
    with patch("herd_mcp.tools.lifecycle.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await lifecycle.decommission(
            agent_name="nonexistent",
            current_agent="mini-mao",
        )

        assert result["success"] is False
        assert "error" in result
        assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_decommission_without_current_agent(seeded_db):
    """Test decommissioning without specifying current agent (system)."""
    with patch("herd_mcp.tools.lifecycle.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await lifecycle.decommission(
            agent_name="pikasso",
            current_agent=None,
        )

        assert result["success"] is True
        assert result["requested_by"] is None

    # Verify lifecycle detail mentions "system"
    activity = seeded_db.execute("""
        SELECT lifecycle_detail
        FROM herd.agent_instance_lifecycle_activity
        WHERE lifecycle_event_type = 'decommissioned'
        LIMIT 1
        """).fetchone()
    assert "system" in activity[0]


@pytest.mark.asyncio
async def test_decommission_already_decommissioned(seeded_db):
    """Test decommissioning an already decommissioned agent."""
    with patch("herd_mcp.tools.lifecycle.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await lifecycle.decommission(
            agent_name="old-agent",
            current_agent="mini-mao",
        )

        # Should succeed but show previous status was decommissioned
        assert result["success"] is True
        assert result["previous_status"] == "decommissioned"
        assert result["new_status"] == "decommissioned"


@pytest.mark.asyncio
async def test_standdown_agent(seeded_db):
    """Test standing down an agent."""
    with patch("herd_mcp.tools.lifecycle.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await lifecycle.standdown(
            agent_name="grunt",
            current_agent="mini-mao",
        )

        assert result["success"] is True
        assert result["target_agent"] == "grunt"
        assert result["previous_status"] == "active"
        assert result["new_status"] == "standby"
        assert result["instances_ended"] == 2
        assert result["requested_by"] == "mini-mao"

    # Verify agent_def was updated to standby
    agent_status = seeded_db.execute(
        "SELECT agent_status FROM herd.agent_def WHERE agent_code = 'grunt'"
    ).fetchone()[0]
    assert agent_status == "standby"

    # Verify instances were ended with standdown outcome
    ended_count = seeded_db.execute("""
        SELECT COUNT(*)
        FROM herd.agent_instance
        WHERE agent_code = 'grunt'
          AND agent_instance_ended_at IS NOT NULL
          AND agent_instance_outcome = 'standdown'
        """).fetchone()[0]
    assert ended_count == 2

    # Verify lifecycle activity was recorded
    activity_count = seeded_db.execute("""
        SELECT COUNT(*)
        FROM herd.agent_instance_lifecycle_activity
        WHERE lifecycle_event_type = 'standdown'
        """).fetchone()[0]
    assert activity_count == 2


@pytest.mark.asyncio
async def test_standdown_nonexistent_agent(seeded_db):
    """Test standing down a nonexistent agent."""
    with patch("herd_mcp.tools.lifecycle.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await lifecycle.standdown(
            agent_name="nonexistent",
            current_agent="mini-mao",
        )

        assert result["success"] is False
        assert "error" in result
        assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_standdown_without_current_agent(seeded_db):
    """Test standing down without specifying current agent (system)."""
    with patch("herd_mcp.tools.lifecycle.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await lifecycle.standdown(
            agent_name="pikasso",
            current_agent=None,
        )

        assert result["success"] is True
        assert result["requested_by"] is None

    # Verify lifecycle detail mentions "system"
    activity = seeded_db.execute("""
        SELECT lifecycle_detail
        FROM herd.agent_instance_lifecycle_activity
        WHERE lifecycle_event_type = 'standdown'
        LIMIT 1
        """).fetchone()
    assert "system" in activity[0]


@pytest.mark.asyncio
async def test_standdown_agent_no_active_instances(seeded_db):
    """Test standing down an agent with no active instances."""
    # Create an agent with no active instances
    seeded_db.execute("""
        INSERT INTO herd.agent_def
          (agent_code, agent_role, agent_status, created_at)
        VALUES ('inactive-agent', 'backend', 'active', CURRENT_TIMESTAMP)
        """)

    with patch("herd_mcp.tools.lifecycle.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await lifecycle.standdown(
            agent_name="inactive-agent",
            current_agent="mini-mao",
        )

        assert result["success"] is True
        assert result["instances_ended"] == 0  # No instances to end


@pytest.mark.asyncio
async def test_decommission_agent_no_active_instances(seeded_db):
    """Test decommissioning an agent with no active instances."""
    # Create an agent with no active instances
    seeded_db.execute("""
        INSERT INTO herd.agent_def
          (agent_code, agent_role, agent_status, created_at)
        VALUES ('inactive-agent2', 'backend', 'active', CURRENT_TIMESTAMP)
        """)

    with patch("herd_mcp.tools.lifecycle.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await lifecycle.decommission(
            agent_name="inactive-agent2",
            current_agent="mini-mao",
        )

        assert result["success"] is True
        assert result["instances_ended"] == 0


@pytest.mark.asyncio
async def test_decommission_updates_modified_at(seeded_db):
    """Test that decommission updates modified_at timestamp."""
    with patch("herd_mcp.tools.lifecycle.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await lifecycle.decommission(
            agent_name="grunt",
            current_agent="mini-mao",
        )

        assert result["success"] is True

    # Verify modified_at was set
    modified_at = seeded_db.execute(
        "SELECT modified_at FROM herd.agent_def WHERE agent_code = 'grunt'"
    ).fetchone()[0]
    assert modified_at is not None


@pytest.mark.asyncio
async def test_standdown_updates_modified_at(seeded_db):
    """Test that standdown updates modified_at timestamp."""
    with patch("herd_mcp.tools.lifecycle.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await lifecycle.standdown(
            agent_name="pikasso",
            current_agent="mini-mao",
        )

        assert result["success"] is True

    # Verify modified_at was set
    modified_at = seeded_db.execute(
        "SELECT modified_at FROM herd.agent_def WHERE agent_code = 'pikasso'"
    ).fetchone()[0]
    assert modified_at is not None
