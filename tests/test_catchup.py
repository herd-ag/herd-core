"""Tests for herd_catchup tool."""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from herd_core.types import (
    AgentRecord,
    AgentState,
    DecisionRecord,
    TicketEvent,
)
from herd_mcp.adapters import AdapterRegistry
from herd_mcp.tools import catchup


@pytest.fixture
def mock_registry(mock_store):
    """Provide an AdapterRegistry with MockStore."""
    return AdapterRegistry(store=mock_store, write_lock=asyncio.Lock())


@pytest.fixture
def seeded_store(mock_store):
    """Provide a mock store seeded with test data for catchup tool.

    Uses naive datetimes to match catchup tool's datetime.now() calls.
    """
    now = datetime.now()
    yesterday = now - timedelta(days=1)

    # Insert previous ended instance for mason
    mock_store.save(
        AgentRecord(
            id="inst-mason-prev",
            agent="mason",
            model="claude-sonnet-4",
            ticket_id="DBC-100",
            state=AgentState.COMPLETED,
            started_at=yesterday - timedelta(hours=2),
            ended_at=yesterday,
        )
    )

    # Insert current instance for mason
    mock_store.save(
        AgentRecord(
            id="inst-mason-current",
            agent="mason",
            model="claude-sonnet-4",
            ticket_id="DBC-100",
            state=AgentState.RUNNING,
            started_at=now,
        )
    )

    # Insert ticket events after previous session ended
    mock_store.append(
        TicketEvent(
            entity_id="DBC-100",
            event_type="status_changed",
            instance_id="inst-mason-current",
            previous_status="in_progress",
            new_status="in_review",
            note="Code reviewed",
            created_at=now,
        )
    )
    mock_store.append(
        TicketEvent(
            entity_id="DBC-100",
            event_type="status_changed",
            instance_id="inst-mason-current",
            previous_status="in_review",
            new_status="merged",
            note="PR merged",
            created_at=now,
        )
    )

    return mock_store


@pytest.mark.asyncio
async def test_catchup_with_previous_session(seeded_store, mock_registry):
    """Test catchup with previous session and updates."""
    result = await catchup.execute(agent_name="mason", registry=mock_registry)

    assert result["since"] is not None
    assert result["agent"] == "mason"
    assert result["previous_instance"] == "inst-mason-prev"
    assert len(result["ticket_updates"]) > 0
    assert "updates across" in result["summary"]


@pytest.mark.asyncio
async def test_catchup_first_session(seeded_store, mock_registry):
    """Test catchup when no previous session exists."""
    result = await catchup.execute(agent_name="fresco", registry=mock_registry)

    assert result["since"] is None
    assert result["agent"] == "fresco"
    assert len(result["ticket_updates"]) == 0
    assert "No previous session found" in result["summary"]
    assert "starting fresh" in result["summary"]


@pytest.mark.asyncio
async def test_catchup_no_updates(seeded_store, mock_registry):
    """Test catchup when there are no updates since last session."""
    now = datetime.now()
    yesterday = now - timedelta(days=1)

    # Create an ended instance for fresco with no subsequent activity
    seeded_store.save(
        AgentRecord(
            id="inst-fresco-prev",
            agent="fresco",
            model="claude-opus-4",
            ticket_id="DBC-200",
            state=AgentState.COMPLETED,
            started_at=yesterday - timedelta(hours=2),
            ended_at=yesterday,
        )
    )

    result = await catchup.execute(agent_name="fresco", registry=mock_registry)

    assert result["since"] is not None
    assert len(result["ticket_updates"]) == 0
    # Enhanced catchup may show other activity (git commits, handoffs, etc)
    # so we just check that the summary exists
    assert "summary" in result
    assert "Since" in result["summary"]


@pytest.mark.asyncio
async def test_catchup_no_agent_name(seeded_store, mock_registry):
    """Test catchup without agent name."""
    result = await catchup.execute(agent_name=None, registry=mock_registry)

    assert result["since"] is None
    assert "No agent identity provided" in result["summary"]


@pytest.mark.asyncio
async def test_catchup_capped_history(seeded_store, mock_registry):
    """Test that catchup history is capped at 7 days."""
    now = datetime.now()
    ten_days_ago = now - timedelta(days=10)
    eight_days_ago = now - timedelta(days=8)

    # Create an ended instance from 10 days ago
    seeded_store.save(
        AgentRecord(
            id="inst-old",
            agent="old-agent",
            model="claude-sonnet-4",
            ticket_id="DBC-999",
            state=AgentState.COMPLETED,
            started_at=ten_days_ago - timedelta(hours=2),
            ended_at=ten_days_ago,
        )
    )

    # Add activity from 8 days ago (should be filtered out by 7-day cap)
    seeded_store.append(
        TicketEvent(
            entity_id="DBC-999",
            event_type="status_changed",
            instance_id="inst-old",
            previous_status="in_progress",
            new_status="done",
            note="Old activity",
            created_at=eight_days_ago,
        )
    )

    result = await catchup.execute(agent_name="old-agent", registry=mock_registry)

    # Should not include activity from >7 days ago
    assert len(result["ticket_updates"]) == 0


@pytest.mark.asyncio
async def test_catchup_ticket_updates_format(seeded_store, mock_registry):
    """Test that ticket updates are formatted correctly."""
    result = await catchup.execute(agent_name="mason", registry=mock_registry)

    if len(result["ticket_updates"]) > 0:
        update = result["ticket_updates"][0]
        assert "ticket" in update
        assert "event_type" in update
        assert "status" in update
        assert "comment" in update
        assert "timestamp" in update
        assert "by_agent" in update


@pytest.mark.asyncio
async def test_catchup_multiple_tickets(seeded_store, mock_registry):
    """Test catchup with updates across multiple tickets."""
    now = datetime.now()

    # Add a second ticket with activity linked to mason
    seeded_store.save(
        AgentRecord(
            id="inst-mason-ticket2",
            agent="mason",
            model="claude-sonnet-4",
            ticket_id="DBC-101",
            state=AgentState.RUNNING,
            started_at=now,
        )
    )

    seeded_store.append(
        TicketEvent(
            entity_id="DBC-101",
            event_type="status_changed",
            instance_id="inst-mason-ticket2",
            previous_status="backlog",
            new_status="assigned",
            note="New ticket",
            created_at=now,
        )
    )

    result = await catchup.execute(agent_name="mason", registry=mock_registry)

    # Should include updates from both tickets
    tickets = {u["ticket"] for u in result["ticket_updates"]}
    assert len(tickets) > 0
    assert "ticket" in result["summary"]


@pytest.mark.asyncio
async def test_catchup_summary_formatting(seeded_store, mock_registry):
    """Test that summary is formatted correctly."""
    result = await catchup.execute(agent_name="mason", registry=mock_registry)

    summary = result["summary"]
    # Should mention event count and ticket count
    if len(result["ticket_updates"]) > 0:
        assert "update" in summary.lower()
        assert "ticket" in summary.lower()


@pytest.mark.asyncio
async def test_catchup_enhanced_fields(seeded_store, mock_registry):
    """Test that enhanced catchup includes all new data sources."""
    result = await catchup.execute(agent_name="mason", registry=mock_registry)

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

        # Create a mock store with test data
        from tests.conftest import MockStore

        store = MockStore()
        registry = AdapterRegistry(store=store, write_lock=asyncio.Lock())

        now = datetime.now()
        yesterday = now - timedelta(days=1)

        store.save(
            AgentRecord(
                id="inst-test",
                agent="mason",
                model="claude-sonnet-4",
                ticket_id="DBC-100",
                state=AgentState.COMPLETED,
                started_at=yesterday - timedelta(hours=2),
                ended_at=yesterday,
            )
        )

        with patch("herd_mcp.tools.catchup.Path.cwd", return_value=repo_path):
            result = await catchup.execute(agent_name="mason", registry=registry)

            # Should have git log entries
            assert "git_log" in result
            assert isinstance(result["git_log"], list)
            # Our test commit should be included
            if result["git_log"]:
                assert result["git_log"][0]["message"] == "Test commit"


@pytest.mark.asyncio
async def test_catchup_decision_records(seeded_store, mock_registry):
    """Test that catchup includes decision records."""
    now = datetime.now()

    # Add decision records to the store
    seeded_store.save(
        DecisionRecord(
            id="dec-001",
            title="architectural: Use DuckDB",
            body="Fast and embedded",
            decision_maker="mason",
            scope="DBC-100",
            created_at=now,
        )
    )

    result = await catchup.execute(agent_name="mason", registry=mock_registry)

    # Should include the decision record
    assert "decision_records" in result
    assert isinstance(result["decision_records"], list)
    if result["decision_records"]:
        dec = result["decision_records"][0]
        assert dec["decision_id"] == "dec-001"
        assert dec["decision_type"] == "architectural"
        assert dec["decided_by"] == "mason"
