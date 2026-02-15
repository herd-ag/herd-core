"""Simplified tests for herd_transition tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from herd_mcp.tools import transition


@pytest.fixture
def seeded_db(in_memory_db):
    """Provide a database with test data for transition tool."""
    conn = in_memory_db

    # Insert test agents
    conn.execute("""
        INSERT INTO herd.agent_def
          (agent_code, agent_role, agent_status, created_at)
        VALUES ('mason', 'backend', 'active', CURRENT_TIMESTAMP)
        """)

    # Insert test tickets
    conn.execute("""
        INSERT INTO herd.ticket_def
          (ticket_code, ticket_title, ticket_current_status, created_at)
        VALUES
          ('DBC-100', 'Test ticket', 'in_progress', CURRENT_TIMESTAMP),
          ('DBC-101', 'Another ticket', 'backlog', CURRENT_TIMESTAMP)
        """)

    # Insert test agent instance
    conn.execute("""
        INSERT INTO herd.agent_instance
          (agent_instance_code, agent_code, model_code, agent_instance_started_at)
        VALUES ('inst-001', 'mason', 'claude-sonnet-4', CURRENT_TIMESTAMP - INTERVAL '1 hour')
        """)

    # Insert initial ticket activity for DBC-100
    conn.execute("""
        INSERT INTO herd.agent_instance_ticket_activity
          (agent_instance_code, ticket_code, ticket_event_type, ticket_status, created_at)
        VALUES ('inst-001', 'DBC-100', 'status_changed', 'in_progress',
                CURRENT_TIMESTAMP - INTERVAL '30 minutes')
        """)

    yield conn


@pytest.mark.asyncio
async def test_transition_success(seeded_db):
    """Test successful ticket transition."""
    with patch("herd_mcp.tools.transition.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await transition.execute(
            ticket_id="DBC-100",
            to_status="done",
            blocked_by=None,
            note="Work completed",
            agent_name="mason",
        )

        assert result["transition_id"] is not None
        assert result["ticket"]["id"] == "DBC-100"
        assert result["ticket"]["previous_status"] == "in_progress"
        assert result["ticket"]["new_status"] == "done"
        assert result["event_type"] == "status_changed"
        assert result["agent"] == "mason"

        # Verify ticket status was updated
        ticket_status = seeded_db.execute(
            "SELECT ticket_current_status FROM herd.ticket_def WHERE ticket_code = 'DBC-100'"
        ).fetchone()[0]
        assert ticket_status == "done"


@pytest.mark.asyncio
async def test_transition_to_blocked(seeded_db):
    """Test transitioning ticket to blocked status."""
    with patch("herd_mcp.tools.transition.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await transition.execute(
            ticket_id="DBC-100",
            to_status="blocked",
            blocked_by="DBC-101",
            note="Waiting for DBC-101",
            agent_name="mason",
        )

        assert result["event_type"] == "blocked"
        assert result["blocked_by"] == "DBC-101"
        assert result["ticket"]["new_status"] == "blocked"


@pytest.mark.asyncio
async def test_transition_ticket_not_found(seeded_db):
    """Test transition for nonexistent ticket."""
    with patch("herd_mcp.tools.transition.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await transition.execute(
            ticket_id="NONEXISTENT",
            to_status="done",
            blocked_by=None,
            note=None,
            agent_name="mason",
        )

        assert result["transition_id"] is None
        assert "error" in result


@pytest.mark.asyncio
async def test_transition_without_agent(seeded_db):
    """Test transition when no agent specified."""
    with patch("herd_mcp.tools.transition.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await transition.execute(
            ticket_id="DBC-101",
            to_status="in_progress",
            blocked_by=None,
            note="System transition",
            agent_name=None,
        )

        assert result["transition_id"] is not None
        assert result["agent"] is None
        assert result["agent_instance_code"] is None

        # Verify ticket status was still updated
        ticket_status = seeded_db.execute(
            "SELECT ticket_current_status FROM herd.ticket_def WHERE ticket_code = 'DBC-101'"
        ).fetchone()[0]
        assert ticket_status == "in_progress"

        # Verify activity WAS recorded (with NULL agent_instance_code)
        activity = seeded_db.execute("""
            SELECT agent_instance_code, ticket_code, ticket_event_type, ticket_status
            FROM herd.agent_instance_ticket_activity
            WHERE ticket_code = 'DBC-101'
            """).fetchone()
        assert activity is not None
        assert activity[0] is None  # agent_instance_code is NULL
        assert activity[1] == "DBC-101"
        assert activity[2] == "status_changed"
        assert activity[3] == "in_progress"


@pytest.mark.asyncio
async def test_transition_linear_sync_success(seeded_db):
    """Test successful Linear sync on transition."""
    linear_issue = {
        "id": "linear-uuid-100",
        "identifier": "DBC-100",
    }

    with patch("herd_mcp.tools.transition.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch("herd_mcp.tools.transition.get_manager") as mock_manager:
            mock_manager.return_value.trigger_refresh = AsyncMock(
                return_value={"status": "success"}
            )

            with patch(
                "herd_mcp.linear_client.is_linear_identifier", return_value=True
            ):
                with patch(
                    "herd_mcp.linear_client.get_issue", return_value=linear_issue
                ):
                    with patch(
                        "herd_mcp.linear_client.update_issue_state"
                    ) as mock_update:
                        result = await transition.execute(
                            ticket_id="DBC-100",
                            to_status="done",
                            blocked_by=None,
                            note="Completed",
                            agent_name="mason",
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
async def test_transition_linear_sync_failure(seeded_db):
    """Test graceful handling of Linear sync failure."""
    linear_issue = {
        "id": "linear-uuid-100",
        "identifier": "DBC-100",
    }

    with patch("herd_mcp.tools.transition.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch("herd_mcp.tools.transition.get_manager") as mock_manager:
            mock_manager.return_value.trigger_refresh = AsyncMock(
                return_value={"status": "success"}
            )

            with patch(
                "herd_mcp.linear_client.is_linear_identifier", return_value=True
            ):
                with patch(
                    "herd_mcp.linear_client.get_issue", return_value=linear_issue
                ):
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
                        )

                        # Transition should still succeed in DuckDB
                        assert result["transition_id"] is not None
                        assert result["linear_synced"] is False
                        assert "linear_sync_error" in result

                        # Verify DuckDB was updated despite Linear failure
                        ticket_status = seeded_db.execute(
                            "SELECT ticket_current_status FROM herd.ticket_def WHERE ticket_code = 'DBC-100'"
                        ).fetchone()[0]
                        assert ticket_status == "done"


@pytest.mark.asyncio
async def test_transition_non_linear_ticket_no_sync(seeded_db):
    """Test that non-Linear tickets don't attempt sync."""
    # Insert a non-Linear style ticket
    seeded_db.execute("""
        INSERT INTO herd.ticket_def
          (ticket_code, ticket_title, ticket_current_status, created_at)
        VALUES ('INTERNAL-001', 'Internal ticket', 'backlog', CURRENT_TIMESTAMP)
    """)

    with patch("herd_mcp.tools.transition.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch("herd_mcp.linear_client.is_linear_identifier", return_value=False):
            with patch("herd_mcp.linear_client.get_issue") as mock_get:
                result = await transition.execute(
                    ticket_id="INTERNAL-001",
                    to_status="in_progress",
                    blocked_by=None,
                    note="Starting work",
                    agent_name="mason",
                )

                assert result["transition_id"] is not None
                assert result["linear_synced"] is False
                # Linear API should not have been called
                mock_get.assert_not_called()

                # Verify DuckDB was updated
                ticket_status = seeded_db.execute(
                    "SELECT ticket_current_status FROM herd.ticket_def WHERE ticket_code = 'INTERNAL-001'"
                ).fetchone()[0]
                assert ticket_status == "in_progress"


@pytest.mark.asyncio
async def test_transition_unmapped_status_no_sync(seeded_db):
    """Test that unmapped statuses don't attempt Linear sync."""
    with patch("herd_mcp.tools.transition.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch("herd_mcp.linear_client.is_linear_identifier", return_value=True):
            with patch("herd_mcp.linear_client.get_issue") as mock_get:
                with patch("herd_mcp.linear_client.update_issue_state") as mock_update:
                    result = await transition.execute(
                        ticket_id="DBC-100",
                        to_status="blocked",
                        blocked_by="DBC-101",
                        note="Waiting on dependency",
                        agent_name="mason",
                    )

                    assert result["transition_id"] is not None
                    assert result["linear_synced"] is False
                    assert result["event_type"] == "blocked"

                    # Linear get_issue should not be called for unmapped status
                    mock_get.assert_not_called()
                    mock_update.assert_not_called()

                    # Verify DuckDB was updated
                    ticket_status = seeded_db.execute(
                        "SELECT ticket_current_status FROM herd.ticket_def WHERE ticket_code = 'DBC-100'"
                    ).fetchone()[0]
                    assert ticket_status == "blocked"


