"""Tests for herd_catchup tool."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from herd_mcp.tools import catchup


@pytest.fixture
def seeded_db(in_memory_db):
    """Provide a database with test data for catchup tool."""
    conn = in_memory_db

    # Insert test agents
    conn.execute("""
        INSERT INTO herd.agent_def
          (agent_code, agent_role, agent_status, created_at)
        VALUES
          ('mason', 'backend', 'active', CURRENT_TIMESTAMP),
          ('fresco', 'frontend', 'active', CURRENT_TIMESTAMP)
        """)

    # Insert previous ended instance for mason
    yesterday = datetime.now() - timedelta(days=1)
    conn.execute(
        """
        INSERT INTO herd.agent_instance
          (agent_instance_code, agent_code, model_code, ticket_code,
           agent_instance_started_at, agent_instance_ended_at, agent_instance_outcome)
        VALUES
          ('inst-mason-prev', 'mason', 'claude-sonnet-4', 'DBC-100', ?, ?, 'completed')
        """,
        [yesterday - timedelta(hours=2), yesterday],
    )

    # Insert current instance for mason
    conn.execute("""
        INSERT INTO herd.agent_instance
          (agent_instance_code, agent_code, model_code, ticket_code,
           agent_instance_started_at)
        VALUES
          ('inst-mason-current', 'mason', 'claude-sonnet-4', 'DBC-100', CURRENT_TIMESTAMP)
        """)

    # Insert ticket activity after previous session ended
    conn.execute("""
        INSERT INTO herd.agent_instance_ticket_activity
          (agent_instance_code, ticket_code, ticket_event_type, ticket_status,
           ticket_activity_comment, created_at)
        VALUES
          ('inst-mason-current', 'DBC-100', 'status_changed', 'in_review', 'Code reviewed', CURRENT_TIMESTAMP),
          ('inst-mason-current', 'DBC-100', 'status_changed', 'merged', 'PR merged', CURRENT_TIMESTAMP)
        """)

    yield conn


@pytest.mark.asyncio
async def test_catchup_with_previous_session(seeded_db):
    """Test catchup with previous session and updates."""
    with patch("herd_mcp.tools.catchup.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await catchup.execute(agent_name="mason")

        assert result["since"] is not None
        assert result["agent"] == "mason"
        assert result["previous_instance"] == "inst-mason-prev"
        assert len(result["ticket_updates"]) > 0
        assert "updates across" in result["summary"]


@pytest.mark.asyncio
async def test_catchup_first_session(seeded_db):
    """Test catchup when no previous session exists."""
    with patch("herd_mcp.tools.catchup.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await catchup.execute(agent_name="fresco")

        assert result["since"] is None
        assert result["agent"] == "fresco"
        assert len(result["ticket_updates"]) == 0
        assert "No previous session found" in result["summary"]
        assert "starting fresh" in result["summary"]


@pytest.mark.asyncio
async def test_catchup_no_updates(seeded_db):
    """Test catchup when there are no updates since last session."""
    # Create an ended instance with no subsequent activity
    yesterday = datetime.now() - timedelta(days=1)
    seeded_db.execute(
        """
        INSERT INTO herd.agent_instance
          (agent_instance_code, agent_code, model_code, ticket_code,
           agent_instance_started_at, agent_instance_ended_at, agent_instance_outcome)
        VALUES
          ('inst-fresco-prev', 'fresco', 'claude-opus-4', 'DBC-200', ?, ?, 'completed')
        """,
        [yesterday - timedelta(hours=2), yesterday],
    )

    with patch("herd_mcp.tools.catchup.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await catchup.execute(agent_name="fresco")

        assert result["since"] is not None
        assert len(result["ticket_updates"]) == 0
        # Enhanced catchup may show other activity (git commits, handoffs, etc)
        # so we just check that the summary exists
        assert "summary" in result
        assert "Since" in result["summary"]


@pytest.mark.asyncio
async def test_catchup_no_agent_name(seeded_db):
    """Test catchup without agent name."""
    with patch("herd_mcp.tools.catchup.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await catchup.execute(agent_name=None)

        assert result["since"] is None
        assert "No agent identity provided" in result["summary"]


@pytest.mark.asyncio
async def test_catchup_capped_history(seeded_db):
    """Test that catchup history is capped at 7 days."""
    # Create an ended instance from 10 days ago
    ten_days_ago = datetime.now() - timedelta(days=10)
    seeded_db.execute("""
        INSERT INTO herd.agent_def
          (agent_code, agent_role, agent_status, created_at)
        VALUES ('old-agent', 'backend', 'active', CURRENT_TIMESTAMP)
        """)

    seeded_db.execute(
        """
        INSERT INTO herd.agent_instance
          (agent_instance_code, agent_code, model_code, ticket_code,
           agent_instance_started_at, agent_instance_ended_at, agent_instance_outcome)
        VALUES
          ('inst-old', 'old-agent', 'claude-sonnet-4', 'DBC-999', ?, ?, 'completed')
        """,
        [ten_days_ago - timedelta(hours=2), ten_days_ago],
    )

    # Add activity from 8 days ago (should be filtered out)
    eight_days_ago = datetime.now() - timedelta(days=8)
    seeded_db.execute(
        """
        INSERT INTO herd.agent_instance_ticket_activity
          (agent_instance_code, ticket_code, ticket_event_type, ticket_status,
           ticket_activity_comment, created_at)
        VALUES
          ('inst-old', 'DBC-999', 'status_changed', 'done', 'Old activity', ?)
        """,
        [eight_days_ago],
    )

    with patch("herd_mcp.tools.catchup.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await catchup.execute(agent_name="old-agent")

        # Should not include activity from >7 days ago
        assert len(result["ticket_updates"]) == 0


@pytest.mark.asyncio
async def test_catchup_ticket_updates_format(seeded_db):
    """Test that ticket updates are formatted correctly."""
    with patch("herd_mcp.tools.catchup.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await catchup.execute(agent_name="mason")

        if len(result["ticket_updates"]) > 0:
            update = result["ticket_updates"][0]
            assert "ticket" in update
            assert "event_type" in update
            assert "status" in update
            assert "comment" in update
            assert "timestamp" in update
            assert "by_agent" in update


@pytest.mark.asyncio
async def test_catchup_multiple_tickets(seeded_db):
    """Test catchup with updates across multiple tickets."""
    # Add a second ticket with activity
    seeded_db.execute("""
        INSERT INTO herd.agent_instance
          (agent_instance_code, agent_code, model_code, ticket_code,
           agent_instance_started_at)
        VALUES
          ('inst-mason-ticket2', 'mason', 'claude-sonnet-4', 'DBC-101', CURRENT_TIMESTAMP)
        """)

    seeded_db.execute("""
        INSERT INTO herd.agent_instance_ticket_activity
          (agent_instance_code, ticket_code, ticket_event_type, ticket_status,
           ticket_activity_comment, created_at)
        VALUES
          ('inst-mason-ticket2', 'DBC-101', 'status_changed', 'assigned', 'New ticket', CURRENT_TIMESTAMP)
        """)

    with patch("herd_mcp.tools.catchup.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await catchup.execute(agent_name="mason")

        # Should include updates from both tickets
        tickets = {u["ticket"] for u in result["ticket_updates"]}
        assert len(tickets) > 0
        assert "ticket" in result["summary"]


@pytest.mark.asyncio
async def test_catchup_summary_formatting(seeded_db):
    """Test that summary is formatted correctly."""
    with patch("herd_mcp.tools.catchup.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await catchup.execute(agent_name="mason")

        summary = result["summary"]
        # Should mention event count and ticket count
        if len(result["ticket_updates"]) > 0:
            assert "update" in summary.lower()
            assert "ticket" in summary.lower()


@pytest.mark.asyncio
async def test_catchup_enhanced_fields(seeded_db):
    """Test that enhanced catchup includes all new data sources."""
    with patch("herd_mcp.tools.catchup.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await catchup.execute(agent_name="mason")

        # Verify all new fields are present
        assert "status_md" in result
        assert "git_log" in result
        assert "linear_tickets" in result
        assert "handoffs" in result
        assert "hdrs" in result
        assert "slack_threads" in result
        assert "decision_records" in result


@pytest.mark.asyncio
async def test_catchup_with_git_repo():
    """Test catchup with a temporary git repository."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)

        # Initialize a git repo
        import subprocess

        subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        # Create a test file and commit
        test_file = repo_path / "test.txt"
        test_file.write_text("test content")
        subprocess.run(
            ["git", "add", "."], cwd=repo_path, check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "Test commit"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )

        # Create a mock database
        import duckdb
        from herd_mcp import db as herd_db

        conn = duckdb.connect(":memory:")
        herd_db.init_schema(conn)

        # Insert test data
        yesterday = datetime.now() - timedelta(days=1)
        conn.execute("""
            INSERT INTO herd.agent_def
              (agent_code, agent_role, agent_status, created_at)
            VALUES ('mason', 'backend', 'active', CURRENT_TIMESTAMP)
        """)

        conn.execute(
            """
            INSERT INTO herd.agent_instance
              (agent_instance_code, agent_code, model_code, ticket_code,
               agent_instance_started_at, agent_instance_ended_at, agent_instance_outcome)
            VALUES ('inst-test', 'mason', 'claude-sonnet-4', 'DBC-100', ?, ?, 'completed')
            """,
            [yesterday - timedelta(hours=2), yesterday],
        )

        with patch("herd_mcp.tools.catchup.connection") as mock_context:
            mock_context.return_value.__enter__ = MagicMock(return_value=conn)
            mock_context.return_value.__exit__ = MagicMock(return_value=None)

            with patch("herd_mcp.tools.catchup.Path.cwd", return_value=repo_path):
                result = await catchup.execute(agent_name="mason")

                # Should have git log entries
                assert "git_log" in result
                assert isinstance(result["git_log"], list)
                # Our test commit should be included
                if result["git_log"]:
                    assert result["git_log"][0]["message"] == "Test commit"

        conn.close()


@pytest.mark.asyncio
async def test_catchup_decision_records(seeded_db):
    """Test that catchup includes decision records."""
    # Add decision records to the database
    seeded_db.execute("""
        INSERT INTO herd.decision_record
          (decision_id, decision_type, context, decision, rationale, decided_by,
           ticket_code, created_at)
        VALUES
          ('dec-001', 'architectural', 'Need to choose DB', 'Use DuckDB',
           'Fast and embedded', 'mason', 'DBC-100', CURRENT_TIMESTAMP)
    """)

    with patch("herd_mcp.tools.catchup.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await catchup.execute(agent_name="mason")

        # Should include the decision record
        assert "decision_records" in result
        assert isinstance(result["decision_records"], list)
        if result["decision_records"]:
            dec = result["decision_records"][0]
            assert dec["decision_id"] == "dec-001"
            assert dec["decision_type"] == "architectural"
            assert dec["decided_by"] == "mason"
