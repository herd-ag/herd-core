"""Tests for herd_assign tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from herd_mcp.tools import assign


@pytest.fixture
def seeded_db(in_memory_db):
    """Provide a database with test data for assign tool."""
    conn = in_memory_db

    # Insert test agents
    conn.execute("""
        INSERT INTO herd.agent_def
          (agent_code, agent_role, agent_status, created_at)
        VALUES
          ('grunt', 'backend', 'active', CURRENT_TIMESTAMP),
          ('pikasso', 'frontend', 'active', CURRENT_TIMESTAMP)
        """)

    # Insert test tickets
    conn.execute("""
        INSERT INTO herd.ticket_def
          (ticket_code, ticket_title, ticket_description, ticket_current_status, created_at)
        VALUES
          ('DBC-100', 'Test ticket', 'Test description', 'backlog', CURRENT_TIMESTAMP),
          ('DBC-101', 'Another ticket', 'Another description', 'backlog', CURRENT_TIMESTAMP)
        """)

    # Insert test agent instance for grunt
    conn.execute("""
        INSERT INTO herd.agent_instance
          (agent_instance_code, agent_code, model_code, agent_instance_started_at)
        VALUES ('inst-001', 'grunt', 'claude-sonnet-4', CURRENT_TIMESTAMP)
        """)

    yield conn


@pytest.mark.asyncio
async def test_assign_success_with_instance(seeded_db):
    """Test successful ticket assignment with active agent instance."""
    with patch("herd_mcp.tools.assign.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await assign.execute(
            ticket_id="DBC-100",
            agent_name="grunt",
            priority="high",
        )

        assert result["assigned"] is True
        assert result["agent"] == "grunt"
        assert result["ticket"]["id"] == "DBC-100"
        assert result["ticket"]["title"] == "Test ticket"
        assert result["ticket"]["previous_status"] == "backlog"
        assert result["priority"] == "high"
        assert result["agent_instance_code"] == "inst-001"
        assert result["note"] is None

        # Verify ticket status was updated
        ticket_status = seeded_db.execute(
            "SELECT ticket_current_status FROM herd.ticket_def WHERE ticket_code = 'DBC-100'"
        ).fetchone()[0]
        assert ticket_status == "assigned"

        # Verify activity was recorded
        activity = seeded_db.execute("""
            SELECT ticket_event_type, ticket_status, ticket_activity_comment
            FROM herd.agent_instance_ticket_activity
            WHERE ticket_code = 'DBC-100'
            """).fetchone()
        assert activity is not None
        assert activity[0] == "assigned"
        assert activity[1] == "assigned"
        assert "high" in activity[2]


@pytest.mark.asyncio
async def test_assign_without_agent_instance(seeded_db):
    """Test ticket assignment when agent has no active instance."""
    with patch("herd_mcp.tools.assign.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await assign.execute(
            ticket_id="DBC-101",
            agent_name="pikasso",  # Has no active instance
            priority="medium",
        )

        # Should still succeed but note the missing instance
        assert result["assigned"] is True
        assert result["agent"] == "pikasso"
        assert result["agent_instance_code"] is None
        assert result["note"] == "No active agent instance found"

        # Verify ticket status was updated
        ticket_status = seeded_db.execute(
            "SELECT ticket_current_status FROM herd.ticket_def WHERE ticket_code = 'DBC-101'"
        ).fetchone()[0]
        assert ticket_status == "assigned"

        # Verify activity WAS recorded (with NULL agent_instance_code)
        activity = seeded_db.execute("""
            SELECT agent_instance_code, ticket_code, ticket_event_type, ticket_status
            FROM herd.agent_instance_ticket_activity
            WHERE ticket_code = 'DBC-101'
            """).fetchone()
        assert activity is not None
        assert activity[0] is None  # agent_instance_code is NULL
        assert activity[1] == "DBC-101"
        assert activity[2] == "assigned"
        assert activity[3] == "assigned"


@pytest.mark.asyncio
async def test_assign_missing_agent_name(seeded_db):
    """Test ticket assignment without agent name."""
    with patch("herd_mcp.tools.assign.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await assign.execute(
            ticket_id="DBC-100",
            agent_name=None,
            priority="high",
        )

        assert result["assigned"] is False
        assert "error" in result
        assert "agent_name is required" in result["error"]


@pytest.mark.asyncio
async def test_assign_ticket_not_found(seeded_db):
    """Test ticket assignment for nonexistent ticket."""
    with patch("herd_mcp.tools.assign.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await assign.execute(
            ticket_id="NONEXISTENT",
            agent_name="grunt",
            priority="high",
        )

        assert result["assigned"] is False
        assert "error" in result
        assert "not found" in result["error"]


@pytest.mark.asyncio
async def test_assign_agent_not_found(seeded_db):
    """Test ticket assignment to nonexistent agent."""
    with patch("herd_mcp.tools.assign.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await assign.execute(
            ticket_id="DBC-100",
            agent_name="nonexistent",
            priority="high",
        )

        assert result["assigned"] is False
        assert "error" in result
        assert "Agent nonexistent not found" in result["error"]


@pytest.mark.asyncio
async def test_assign_inactive_agent(seeded_db):
    """Test ticket assignment to inactive agent."""
    # First set pikasso to inactive
    seeded_db.execute(
        "UPDATE herd.agent_def SET agent_status = 'inactive' WHERE agent_code = 'pikasso'"
    )

    with patch("herd_mcp.tools.assign.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await assign.execute(
            ticket_id="DBC-100",
            agent_name="pikasso",
            priority="high",
        )

        assert result["assigned"] is False
        assert "error" in result
        assert "not active" in result["error"]
        assert "inactive" in result["error"]


@pytest.mark.asyncio
async def test_assign_updates_modified_at(seeded_db):
    """Test that ticket modified_at is updated on assignment."""
    with patch("herd_mcp.tools.assign.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        # Perform assignment
        result = await assign.execute(
            ticket_id="DBC-100",
            agent_name="grunt",
            priority="high",
        )

        assert result["assigned"] is True

        # Verify modified_at was set
        modified_at = seeded_db.execute(
            "SELECT modified_at FROM herd.ticket_def WHERE ticket_code = 'DBC-100'"
        ).fetchone()[0]
        assert modified_at is not None


@pytest.mark.asyncio
async def test_assign_auto_register_from_linear(seeded_db):
    """Test auto-registration of ticket from Linear when not in DB."""
    linear_issue = {
        "id": "linear-uuid-123",
        "identifier": "DBC-125",
        "title": "New ticket from Linear",
        "description": "Fetched from Linear API",
        "project": {"id": "proj-1", "name": "MCP Server"},
    }

    with patch("herd_mcp.tools.assign.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch("herd_mcp.linear_client.is_linear_identifier", return_value=True):
            with patch("herd_mcp.linear_client.get_issue", return_value=linear_issue):
                with patch("herd_mcp.linear_client.update_issue_state"):
                    result = await assign.execute(
                        ticket_id="DBC-125",
                        agent_name="grunt",
                        priority="high",
                    )

                    assert result["assigned"] is True
                    assert result["ticket"]["id"] == "DBC-125"
                    assert result["ticket"]["title"] == "New ticket from Linear"

                    # Verify ticket was inserted into DB
                    ticket = seeded_db.execute(
                        "SELECT ticket_code, ticket_title, project_code FROM herd.ticket_def WHERE ticket_code = 'DBC-125'"
                    ).fetchone()
                    assert ticket is not None
                    assert ticket[0] == "DBC-125"
                    assert ticket[1] == "New ticket from Linear"
                    assert ticket[2] == "MCP Server"


@pytest.mark.asyncio
async def test_assign_linear_sync_success(seeded_db):
    """Test successful Linear sync on assignment."""
    linear_issue = {
        "id": "linear-uuid-100",
        "identifier": "DBC-100",
    }

    with patch("herd_mcp.tools.assign.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch("herd_mcp.linear_client.is_linear_identifier", return_value=True):
            with patch("herd_mcp.linear_client.get_issue", return_value=linear_issue):
                with patch("herd_mcp.linear_client.update_issue_state") as mock_update:
                    result = await assign.execute(
                        ticket_id="DBC-100",
                        agent_name="grunt",
                        priority="high",
                    )

                    assert result["assigned"] is True
                    assert result["linear_synced"] is True

                    # Verify Linear API was called with correct state
                    mock_update.assert_called_once_with(
                        "linear-uuid-100",
                        "408b4cda-4d6e-403a-8030-78e8b0a6ffee",  # Assigned state
                    )


@pytest.mark.asyncio
async def test_assign_linear_sync_failure(seeded_db):
    """Test graceful handling of Linear sync failure."""
    with patch("herd_mcp.tools.assign.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch("herd_mcp.linear_client.is_linear_identifier", return_value=True):
            with patch(
                "herd_mcp.linear_client.get_issue", side_effect=Exception("API error")
            ):
                result = await assign.execute(
                    ticket_id="DBC-100",
                    agent_name="grunt",
                    priority="high",
                )

                # Assignment should still succeed
                assert result["assigned"] is True
                assert result["linear_synced"] is False
                assert "linear_sync_error" in result


@pytest.mark.asyncio
async def test_assign_non_linear_ticket_no_sync(seeded_db):
    """Test that non-Linear tickets don't attempt sync."""
    # Insert a non-Linear style ticket
    seeded_db.execute("""
        INSERT INTO herd.ticket_def
          (ticket_code, ticket_title, ticket_current_status, created_at)
        VALUES ('INTERNAL-001', 'Internal ticket', 'backlog', CURRENT_TIMESTAMP)
    """)

    with patch("herd_mcp.tools.assign.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch("herd_mcp.linear_client.is_linear_identifier", return_value=False):
            with patch("herd_mcp.linear_client.get_issue") as mock_get:
                result = await assign.execute(
                    ticket_id="INTERNAL-001",
                    agent_name="grunt",
                    priority="normal",
                )

                assert result["assigned"] is True
                assert result["linear_synced"] is False
                # Linear API should not have been called
                mock_get.assert_not_called()
