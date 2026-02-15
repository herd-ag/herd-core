"""Tests for herd_spawn tool."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from herd_mcp.tools import spawn


@pytest.fixture
def seeded_db(in_memory_db):
    """Provide a database with test data for spawn tool."""
    conn = in_memory_db

    # Insert test agent definitions
    conn.execute("""
        INSERT INTO herd.agent_def
          (agent_code, agent_role, agent_status, default_model_code, created_at)
        VALUES
          ('mason', 'backend', 'active', 'claude-sonnet-4', CURRENT_TIMESTAMP),
          ('fresco', 'frontend', 'active', 'claude-opus-4', CURRENT_TIMESTAMP),
          ('steve', 'coordinator', 'active', 'claude-opus-4', CURRENT_TIMESTAMP)
        """)

    # Insert a current instance for steve (spawner)
    conn.execute("""
        INSERT INTO herd.agent_instance
          (agent_instance_code, agent_code, model_code, agent_instance_started_at)
        VALUES ('inst-steve-001', 'steve', 'claude-opus-4', CURRENT_TIMESTAMP)
        """)

    yield conn


@pytest.mark.asyncio
async def test_spawn_single_agent(seeded_db):
    """Test spawning a single agent."""
    with patch("herd_mcp.tools.spawn.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await spawn.execute(
            count=1,
            role="backend",
            model=None,
            agent_name="steve",
        )

        assert result["spawned"] == 1
        assert len(result["agents"]) == 1
        assert result["agents"][0].startswith("inst-")
        assert result["role"] == "backend"
        assert result["agent_code"] == "mason"
        assert result["model"] == "claude-sonnet-4"  # Default from agent_def
        assert result["spawned_by"] == "steve"
        assert result["spawned_by_instance"] == "inst-steve-001"

    # Verify instance was created
    instance = seeded_db.execute(
        "SELECT agent_code, model_code FROM herd.agent_instance WHERE agent_instance_code = ?",
        [result["agents"][0]],
    ).fetchone()
    assert instance is not None
    assert instance[0] == "mason"
    assert instance[1] == "claude-sonnet-4"

    # Verify lifecycle activity was recorded
    activity = seeded_db.execute(
        """
        SELECT lifecycle_event_type, lifecycle_detail
        FROM herd.agent_instance_lifecycle_activity
        WHERE agent_instance_code = ?
        """,
        [result["agents"][0]],
    ).fetchone()
    assert activity is not None
    assert activity[0] == "spawned"
    assert "steve" in activity[1]


@pytest.mark.asyncio
async def test_spawn_multiple_agents(seeded_db):
    """Test spawning multiple agents."""
    with patch("herd_mcp.tools.spawn.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await spawn.execute(
            count=3,
            role="frontend",
            model=None,
            agent_name="steve",
        )

        assert result["spawned"] == 3
        assert len(result["agents"]) == 3
        assert result["agent_code"] == "fresco"

    # Verify all instances were created
    count = seeded_db.execute(
        "SELECT COUNT(*) FROM herd.agent_instance WHERE agent_code = 'fresco'"
    ).fetchone()[0]
    assert count == 3


@pytest.mark.asyncio
async def test_spawn_with_model_override(seeded_db):
    """Test spawning with model override."""
    with patch("herd_mcp.tools.spawn.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await spawn.execute(
            count=1,
            role="backend",
            model="claude-haiku-4",
            agent_name="steve",
        )

        assert result["model"] == "claude-haiku-4"  # Override applied

    # Verify instance has overridden model
    instance = seeded_db.execute(
        "SELECT model_code FROM herd.agent_instance WHERE agent_instance_code = ?",
        [result["agents"][0]],
    ).fetchone()
    assert instance[0] == "claude-haiku-4"


@pytest.mark.asyncio
async def test_spawn_invalid_role(seeded_db):
    """Test spawning with invalid role."""
    with patch("herd_mcp.tools.spawn.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await spawn.execute(
            count=1,
            role="nonexistent_role",
            model=None,
            agent_name="steve",
        )

        assert result["spawned"] == 0
        assert len(result["agents"]) == 0
        assert "error" in result
        assert "No agent definition found" in result["error"]


@pytest.mark.asyncio
async def test_spawn_zero_count(seeded_db):
    """Test spawning with count=0."""
    with patch("herd_mcp.tools.spawn.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await spawn.execute(
            count=0,
            role="backend",
            model=None,
            agent_name="steve",
        )

        assert result["spawned"] == 0
        assert "error" in result
        assert "count must be at least 1" in result["error"]


@pytest.mark.asyncio
async def test_spawn_without_spawner_agent(seeded_db):
    """Test spawning without spawner agent (system spawn)."""
    with patch("herd_mcp.tools.spawn.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await spawn.execute(
            count=1,
            role="backend",
            model=None,
            agent_name=None,  # No spawner
        )

        assert result["spawned"] == 1
        assert result["spawned_by"] is None
        assert result["spawned_by_instance"] is None

    # Verify lifecycle detail mentions "system"
    activity = seeded_db.execute(
        """
        SELECT lifecycle_detail
        FROM herd.agent_instance_lifecycle_activity
        WHERE agent_instance_code = ?
        """,
        [result["agents"][0]],
    ).fetchone()
    assert "system" in activity[0]


@pytest.mark.asyncio
async def test_spawn_updates_spawned_by_reference(seeded_db):
    """Test that spawned instances reference the spawner."""
    with patch("herd_mcp.tools.spawn.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await spawn.execute(
            count=1,
            role="backend",
            model=None,
            agent_name="steve",
        )

        # Verify spawned_by_agent_instance_code is set correctly
        instance = seeded_db.execute(
            """
            SELECT spawned_by_agent_instance_code
            FROM herd.agent_instance
            WHERE agent_instance_code = ?
            """,
            [result["agents"][0]],
        ).fetchone()
        assert instance[0] == "inst-steve-001"


@pytest.mark.asyncio
async def test_spawn_multiple_roles_sequentially(seeded_db):
    """Test spawning different roles sequentially."""
    with patch("herd_mcp.tools.spawn.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        # Spawn backend
        result1 = await spawn.execute(
            count=1,
            role="backend",
            model=None,
            agent_name="steve",
        )

        # Spawn frontend
        result2 = await spawn.execute(
            count=1,
            role="frontend",
            model=None,
            agent_name="steve",
        )

        assert result1["agent_code"] == "mason"
        assert result2["agent_code"] == "fresco"

    # Verify both were created
    mason_count = seeded_db.execute(
        "SELECT COUNT(*) FROM herd.agent_instance WHERE agent_code = 'mason'"
    ).fetchone()[0]
    fresco_count = seeded_db.execute(
        "SELECT COUNT(*) FROM herd.agent_instance WHERE agent_code = 'fresco'"
    ).fetchone()[0]

    assert mason_count == 1
    assert fresco_count == 1


@pytest.mark.asyncio
async def test_spawn_with_ticket_creates_worktree(seeded_db):
    """Test spawning with ticket ID creates worktree and assembles context."""
    # Add a ticket
    seeded_db.execute("""
        INSERT INTO herd.ticket_def
          (ticket_code, ticket_title, ticket_description, ticket_current_status, created_at, modified_at)
        VALUES ('DBC-126', 'Test ticket', 'Test description', 'backlog', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)

    mock_repo_root = Path("/fake/repo")
    mock_worktree = Path("/private/tmp/mason-dbc126")

    with patch("herd_mcp.tools.spawn.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

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
                        "os.environ", {"HERD_SLACK_TOKEN": "xoxb-test-token"}
                    ):
                        result = await spawn.execute(
                            count=1,
                            role="backend",
                            model=None,
                            agent_name="steve",
                            ticket_id="DBC-126",
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
    instance = seeded_db.execute(
        "SELECT ticket_code FROM herd.agent_instance WHERE agent_instance_code = ?",
        [result["agents"][0]],
    ).fetchone()
    assert instance[0] == "DBC-126"

    # Verify ticket was transitioned to in_progress
    ticket_status = seeded_db.execute(
        "SELECT ticket_current_status FROM herd.ticket_def WHERE ticket_code = ?",
        ["DBC-126"],
    ).fetchone()
    assert ticket_status[0] == "in_progress"


@pytest.mark.asyncio
async def test_spawn_with_ticket_auto_registers_from_linear(seeded_db):
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

    with patch("herd_mcp.tools.spawn.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch("herd_mcp.tools.spawn._find_repo_root", return_value=mock_repo_root):
            with patch(
                "herd_mcp.tools.spawn._create_worktree", return_value=mock_worktree
            ):
                with patch(
                    "herd_mcp.tools.spawn._read_file_safe", return_value="content"
                ):
                    with patch("herd_mcp.tools.spawn.linear_client") as mock_linear:
                        mock_linear.is_linear_identifier.return_value = True
                        mock_linear.get_issue.return_value = mock_linear_issue

                        with patch.dict(
                            "os.environ", {"HERD_SLACK_TOKEN": "xoxb-test"}
                        ):
                            result = await spawn.execute(
                                count=1,
                                role="backend",
                                model=None,
                                agent_name="steve",
                                ticket_id="DBC-127",
                            )

    assert result["spawned"] == 1
    assert result["ticket_id"] == "DBC-127"

    # Verify ticket was registered
    ticket = seeded_db.execute(
        "SELECT ticket_code, ticket_title FROM herd.ticket_def WHERE ticket_code = ?",
        ["DBC-127"],
    ).fetchone()
    assert ticket is not None
    assert ticket[0] == "DBC-127"
    assert ticket[1] == "Auto-registered ticket"


@pytest.mark.asyncio
async def test_spawn_with_ticket_syncs_to_linear(seeded_db):
    """Test spawning syncs ticket status to Linear."""
    seeded_db.execute("""
        INSERT INTO herd.ticket_def
          (ticket_code, ticket_title, ticket_description, ticket_current_status, created_at, modified_at)
        VALUES ('DBC-128', 'Sync test', 'Description', 'backlog', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)

    mock_repo_root = Path("/fake/repo")
    mock_worktree = Path("/private/tmp/mason-dbc128")

    mock_linear_issue = {
        "identifier": "DBC-128",
        "id": "linear-uuid-456",
        "title": "Sync test",
    }

    with patch("herd_mcp.tools.spawn.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch("herd_mcp.tools.spawn._find_repo_root", return_value=mock_repo_root):
            with patch(
                "herd_mcp.tools.spawn._create_worktree", return_value=mock_worktree
            ):
                with patch(
                    "herd_mcp.tools.spawn._read_file_safe", return_value="content"
                ):
                    with patch("herd_mcp.tools.spawn.linear_client") as mock_linear:
                        mock_linear.is_linear_identifier.return_value = True
                        mock_linear.get_issue.return_value = mock_linear_issue

                        with patch.dict(
                            "os.environ", {"HERD_SLACK_TOKEN": "xoxb-test"}
                        ):
                            result = await spawn.execute(
                                count=1,
                                role="backend",
                                model=None,
                                agent_name="steve",
                                ticket_id="DBC-128",
                            )

    assert result["linear_synced"] is True

    # Verify Linear API was called with In Progress state UUID
    mock_linear.update_issue_state.assert_called_once_with(
        "linear-uuid-456", "77631f63-b27b-45a5-8b04-f9f82b4facde"
    )


@pytest.mark.asyncio
async def test_spawn_with_ticket_handles_missing_ticket(seeded_db):
    """Test spawning with non-existent ticket returns error."""
    with patch("herd_mcp.tools.spawn.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch("herd_mcp.tools.spawn._find_repo_root", return_value=Path("/fake")):
            with patch("herd_mcp.tools.spawn.linear_client") as mock_linear:
                mock_linear.is_linear_identifier.return_value = True
                mock_linear.get_issue.return_value = None  # Ticket not in Linear either

                result = await spawn.execute(
                    count=1,
                    role="backend",
                    model=None,
                    agent_name="steve",
                    ticket_id="DBC-999",
                )

    assert result["spawned"] == 0
    assert "error" in result
    assert "not found" in result["error"].lower()


@pytest.mark.asyncio
async def test_spawn_with_ticket_handles_worktree_creation_failure(seeded_db):
    """Test spawning handles git worktree creation failure gracefully."""
    seeded_db.execute("""
        INSERT INTO herd.ticket_def
          (ticket_code, ticket_title, ticket_description, ticket_current_status, created_at, modified_at)
        VALUES ('DBC-130', 'Worktree fail', 'Test', 'backlog', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    """)

    with patch("herd_mcp.tools.spawn.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch("herd_mcp.tools.spawn._find_repo_root", return_value=Path("/fake")):
            with patch("herd_mcp.tools.spawn._create_worktree") as mock_worktree:
                mock_worktree.side_effect = RuntimeError("Git command failed")

                result = await spawn.execute(
                    count=1,
                    role="backend",
                    model=None,
                    agent_name="steve",
                    ticket_id="DBC-130",
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
