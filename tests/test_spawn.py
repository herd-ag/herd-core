"""Tests for herd_spawn tool."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from herd_core.types import (
    AgentRecord,
    AgentState,
    LifecycleEvent,
    TicketEvent,
    TicketRecord,
)
from herd_mcp.adapters import AdapterRegistry
from herd_mcp.tools import spawn


@pytest.fixture
def mock_registry(mock_store):
    """Provide an AdapterRegistry with MockStore."""
    return AdapterRegistry(store=mock_store, write_lock=asyncio.Lock())


@pytest.fixture
def seeded_store(mock_store, mock_registry):
    """Provide a mock store seeded with test data for spawn tool."""
    # Seed a running steve instance (spawner)
    mock_store.save(
        AgentRecord(
            id="inst-steve-001",
            agent="steve",
            model="claude-opus-4",
            state=AgentState.RUNNING,
        )
    )
    return mock_store


@pytest.mark.asyncio
async def test_spawn_single_agent(seeded_store, mock_registry):
    """Test spawning a single agent."""
    result = await spawn.execute(
        count=1,
        role="backend",
        model=None,
        agent_name="steve",
        registry=mock_registry,
    )

    assert result["spawned"] == 1
    assert len(result["agents"]) == 1
    assert result["agents"][0].startswith("inst-")
    assert result["role"] == "backend"
    assert result["agent_code"] == "mason"
    assert result["model"] == "claude-sonnet-4"  # Default from _AGENT_DEFAULT_MODEL
    assert result["spawned_by"] == "steve"
    assert result["spawned_by_instance"] == "inst-steve-001"

    # Verify instance was created in store
    instance_id = result["agents"][0]
    instance = seeded_store.get(AgentRecord, instance_id)
    assert instance is not None
    assert instance.agent == "mason"
    assert instance.model == "claude-sonnet-4"

    # Verify lifecycle activity was recorded
    events = seeded_store.events(LifecycleEvent, entity_id=instance_id)
    assert len(events) >= 1
    assert events[0].event_type == "spawned"
    assert "steve" in events[0].detail


@pytest.mark.asyncio
async def test_spawn_multiple_agents(seeded_store, mock_registry):
    """Test spawning multiple agents."""
    result = await spawn.execute(
        count=3,
        role="frontend",
        model=None,
        agent_name="steve",
        registry=mock_registry,
    )

    assert result["spawned"] == 3
    assert len(result["agents"]) == 3
    assert result["agent_code"] == "fresco"

    # Verify all instances were created
    fresco_instances = seeded_store.list(AgentRecord, agent="fresco")
    assert len(fresco_instances) == 3


@pytest.mark.asyncio
async def test_spawn_with_model_override(seeded_store, mock_registry):
    """Test spawning with model override."""
    result = await spawn.execute(
        count=1,
        role="backend",
        model="claude-haiku-4",
        agent_name="steve",
        registry=mock_registry,
    )

    assert result["model"] == "claude-haiku-4"  # Override applied

    # Verify instance has overridden model
    instance_id = result["agents"][0]
    instance = seeded_store.get(AgentRecord, instance_id)
    assert instance.model == "claude-haiku-4"


@pytest.mark.asyncio
async def test_spawn_invalid_role(seeded_store, mock_registry):
    """Test spawning with invalid role."""
    result = await spawn.execute(
        count=1,
        role="nonexistent_role",
        model=None,
        agent_name="steve",
        registry=mock_registry,
    )

    assert result["spawned"] == 0
    assert len(result["agents"]) == 0
    assert "error" in result
    assert "No agent definition found" in result["error"]


@pytest.mark.asyncio
async def test_spawn_zero_count(seeded_store, mock_registry):
    """Test spawning with count=0."""
    result = await spawn.execute(
        count=0,
        role="backend",
        model=None,
        agent_name="steve",
        registry=mock_registry,
    )

    assert result["spawned"] == 0
    assert "error" in result
    assert "count must be at least 1" in result["error"]


@pytest.mark.asyncio
async def test_spawn_without_spawner_agent(seeded_store, mock_registry):
    """Test spawning without spawner agent (system spawn)."""
    result = await spawn.execute(
        count=1,
        role="backend",
        model=None,
        agent_name=None,  # No spawner
        registry=mock_registry,
    )

    assert result["spawned"] == 1
    assert result["spawned_by"] is None
    assert result["spawned_by_instance"] is None

    # Verify lifecycle detail mentions "system"
    instance_id = result["agents"][0]
    events = seeded_store.events(LifecycleEvent, entity_id=instance_id)
    assert len(events) >= 1
    assert "system" in events[0].detail


@pytest.mark.asyncio
async def test_spawn_updates_spawned_by_reference(seeded_store, mock_registry):
    """Test that spawned instances reference the spawner."""
    result = await spawn.execute(
        count=1,
        role="backend",
        model=None,
        agent_name="steve",
        registry=mock_registry,
    )

    # Verify spawned_by is set correctly
    instance_id = result["agents"][0]
    instance = seeded_store.get(AgentRecord, instance_id)
    assert instance.spawned_by == "inst-steve-001"


@pytest.mark.asyncio
async def test_spawn_multiple_roles_sequentially(seeded_store, mock_registry):
    """Test spawning different roles sequentially."""
    # Spawn backend
    result1 = await spawn.execute(
        count=1,
        role="backend",
        model=None,
        agent_name="steve",
        registry=mock_registry,
    )

    # Spawn frontend
    result2 = await spawn.execute(
        count=1,
        role="frontend",
        model=None,
        agent_name="steve",
        registry=mock_registry,
    )

    assert result1["agent_code"] == "mason"
    assert result2["agent_code"] == "fresco"

    # Verify both were created
    mason_instances = seeded_store.list(AgentRecord, agent="mason")
    fresco_instances = seeded_store.list(AgentRecord, agent="fresco")

    assert len(mason_instances) == 1
    assert len(fresco_instances) == 1


@pytest.mark.asyncio
async def test_spawn_with_ticket_creates_worktree(seeded_store, mock_registry):
    """Test spawning with ticket ID creates worktree and assembles context."""
    # Add a ticket to the store
    seeded_store.save(
        TicketRecord(
            id="DBC-126",
            title="Test ticket",
            description="Test description",
            status="backlog",
        )
    )

    mock_repo_root = Path("/fake/repo")
    mock_worktree = Path("/private/tmp/mason-dbc126")

    with patch("herd_mcp.tools.spawn._find_repo_root", return_value=mock_repo_root):
        with patch(
            "herd_mcp.tools.spawn._create_worktree", return_value=mock_worktree
        ):
            with patch("herd_mcp.tools.spawn._read_file_safe") as mock_read:
                # Mock file reads
                mock_read.side_effect = lambda p: {
                    mock_repo_root / ".herd" / "roles" / "mason.md": "# Mason role",
                    mock_repo_root
                    / ".herd"
                    / "craft.md": "## All Agents\n\n## Mason — Backend Craft Standards\nMason craft",
                    mock_repo_root / "CLAUDE.md": "# CLAUDE.md content",
                }.get(p, None)

                with patch.dict(
                    "os.environ", {"HERD_NOTIFY_SLACK_TOKEN": "xoxb-test-token"}
                ):
                    with patch("herd_mcp.linear_client") as mock_linear:
                        mock_linear.is_linear_identifier.return_value = True
                        mock_linear.get_issue.return_value = None

                        result = await spawn.execute(
                            count=1,
                            role="backend",
                            model=None,
                            agent_name="steve",
                            ticket_id="DBC-126",
                            registry=mock_registry,
                        )

    assert result["spawned"] == 1
    assert len(result["agents"]) == 1
    assert result["ticket_id"] == "DBC-126"
    assert result["worktree_path"] == "/private/tmp/mason-dbc126"
    assert result["branch_name"] == "herd/mason/dbc-126-herd-spawn"
    assert "context_payload" in result
    assert "# Mason role" in result["context_payload"]
    assert "Mason craft" in result["context_payload"]
    assert "CLAUDE.md content" in result["context_payload"]
    assert "xoxb-test-token" in result["context_payload"]

    # Verify instance was linked to ticket
    instance_id = result["agents"][0]
    instance = seeded_store.get(AgentRecord, instance_id)
    assert instance.ticket_id == "DBC-126"

    # Verify ticket was transitioned to in_progress
    ticket = seeded_store.get(TicketRecord, "DBC-126")
    assert ticket.status == "in_progress"


@pytest.mark.asyncio
async def test_spawn_with_ticket_auto_registers_from_linear(seeded_store, mock_registry):
    """Test spawning with Linear ticket ID auto-registers ticket."""
    mock_repo_root = Path("/fake/repo")
    mock_worktree = Path("/private/tmp/mason-dbc127")

    mock_linear_issue = {
        "identifier": "DBC-127",
        "id": "linear-uuid-123",
        "title": "Auto-registered ticket",
        "description": "From Linear",
        "project": {"name": "Test Project"},
    }

    with patch("herd_mcp.tools.spawn._find_repo_root", return_value=mock_repo_root):
        with patch(
            "herd_mcp.tools.spawn._create_worktree", return_value=mock_worktree
        ):
            with patch(
                "herd_mcp.tools.spawn._read_file_safe", return_value="content"
            ):
                with patch("herd_mcp.linear_client") as mock_linear:
                    mock_linear.is_linear_identifier.return_value = True
                    mock_linear.get_issue.return_value = mock_linear_issue

                    with patch.dict(
                        "os.environ", {"HERD_NOTIFY_SLACK_TOKEN": "xoxb-test"}
                    ):
                        result = await spawn.execute(
                            count=1,
                            role="backend",
                            model=None,
                            agent_name="steve",
                            ticket_id="DBC-127",
                            registry=mock_registry,
                        )

    assert result["spawned"] == 1
    assert result["ticket_id"] == "DBC-127"

    # Verify ticket was registered in store
    ticket = seeded_store.get(TicketRecord, "DBC-127")
    assert ticket is not None
    assert ticket.id == "DBC-127"
    assert ticket.title == "Auto-registered ticket"


@pytest.mark.asyncio
async def test_spawn_with_ticket_syncs_to_linear(seeded_store, mock_registry):
    """Test spawning syncs ticket status to Linear."""
    seeded_store.save(
        TicketRecord(
            id="DBC-128",
            title="Sync test",
            description="Description",
            status="backlog",
        )
    )

    mock_repo_root = Path("/fake/repo")
    mock_worktree = Path("/private/tmp/mason-dbc128")

    mock_linear_issue = {
        "identifier": "DBC-128",
        "id": "linear-uuid-456",
        "title": "Sync test",
    }

    with patch("herd_mcp.tools.spawn._find_repo_root", return_value=mock_repo_root):
        with patch(
            "herd_mcp.tools.spawn._create_worktree", return_value=mock_worktree
        ):
            with patch(
                "herd_mcp.tools.spawn._read_file_safe", return_value="content"
            ):
                with patch("herd_mcp.linear_client") as mock_linear:
                    mock_linear.is_linear_identifier.return_value = True
                    mock_linear.get_issue.return_value = mock_linear_issue

                    with patch.dict(
                        "os.environ", {"HERD_NOTIFY_SLACK_TOKEN": "xoxb-test"}
                    ):
                        result = await spawn.execute(
                            count=1,
                            role="backend",
                            model=None,
                            agent_name="steve",
                            ticket_id="DBC-128",
                            registry=mock_registry,
                        )

    assert result["linear_synced"] is True

    # Verify Linear API was called with In Progress state UUID
    mock_linear.update_issue_state.assert_called_once_with(
        "linear-uuid-456", "77631f63-b27b-45a5-8b04-f9f82b4facde"
    )


@pytest.mark.asyncio
async def test_spawn_with_ticket_handles_missing_ticket(seeded_store, mock_registry):
    """Test spawning with non-existent ticket returns error."""
    with patch("herd_mcp.tools.spawn._find_repo_root", return_value=Path("/fake")):
        with patch("herd_mcp.linear_client") as mock_linear:
            mock_linear.is_linear_identifier.return_value = True
            mock_linear.get_issue.return_value = None  # Ticket not in Linear either

            result = await spawn.execute(
                count=1,
                role="backend",
                model=None,
                agent_name="steve",
                ticket_id="DBC-999",
                registry=mock_registry,
            )

    assert result["spawned"] == 0
    assert "error" in result
    assert "not found" in result["error"].lower()


@pytest.mark.asyncio
async def test_spawn_with_ticket_handles_worktree_creation_failure(
    seeded_store, mock_registry
):
    """Test spawning handles git worktree creation failure gracefully."""
    seeded_store.save(
        TicketRecord(
            id="DBC-130",
            title="Worktree fail",
            description="Test",
            status="backlog",
        )
    )

    with patch("herd_mcp.tools.spawn._find_repo_root", return_value=Path("/fake")):
        with patch("herd_mcp.tools.spawn._create_worktree") as mock_worktree:
            mock_worktree.side_effect = RuntimeError("Git command failed")

            with patch("herd_mcp.linear_client") as mock_linear:
                mock_linear.is_linear_identifier.return_value = False

                result = await spawn.execute(
                    count=1,
                    role="backend",
                    model=None,
                    agent_name="steve",
                    ticket_id="DBC-130",
                    registry=mock_registry,
                )

    assert result["spawned"] == 0
    assert "error" in result
    assert "worktree" in result["error"].lower()


@pytest.mark.asyncio
async def test_extract_craft_section():
    """Test craft section extraction for different agents."""
    craft_content = """# The Herd — Craft Standards

## All Agents — Shared Standards
Shared content here.

## Mason — Backend Craft Standards
Mason specific content.
More mason content.

## Fresco — Frontend Craft Standards
Fresco content.

## Wardenstein — QA Craft Standards
Wardenstein content.
"""

    # Test Mason extraction
    mason_section = spawn._extract_craft_section(craft_content, "mason")
    assert "## Mason — Backend Craft Standards" in mason_section
    assert "Mason specific content" in mason_section
    assert "More mason content" in mason_section
    assert "Fresco" not in mason_section

    # Test Fresco extraction
    fresco_section = spawn._extract_craft_section(craft_content, "fresco")
    assert "## Fresco — Frontend Craft Standards" in fresco_section
    assert "Fresco content" in fresco_section
    assert "Wardenstein" not in fresco_section

    # Test unknown agent
    unknown_section = spawn._extract_craft_section(craft_content, "unknown")
    assert unknown_section == ""
