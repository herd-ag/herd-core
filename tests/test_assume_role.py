"""Tests for assume_role prompt implementation."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from herd_mcp.tools import assume_role


@pytest.fixture
def mock_repo(tmp_path):
    """Create a minimal mock repo with role and craft files."""
    # Create .git marker
    (tmp_path / ".git").mkdir()

    # Create role files
    roles_dir = tmp_path / ".herd" / "roles"
    roles_dir.mkdir(parents=True)
    (roles_dir / "steve.md").write_text("# Steve\nThe orchestrator.")
    (roles_dir / "mason.md").write_text("# Mason\nThe builder.")

    # Create craft.md
    craft_file = tmp_path / ".herd" / "craft.md"
    craft_file.write_text(
        "# The Herd — Craft Standards\n\n"
        "## All Agents — Shared Standards\nShared content.\n\n"
        "## Mason — Backend Craft Standards\nMason craft rules.\n\n"
        "## Steve — Coordination Craft Standards\nSteve craft rules.\n\n"
    )

    # Create CLAUDE.md
    (tmp_path / "CLAUDE.md").write_text("# CLAUDE.md\nProject guidelines here.")

    # Create STATUS.md
    herd_dir = tmp_path / ".herd"
    (herd_dir / "STATUS.md").write_text("# Status\nAll systems operational.")

    return tmp_path


def _patch_repo_root(repo_path: Path):
    """Return a patch for find_repo_root to use the given path.

    Patches in both locations:
    - assume_role.find_repo_root (for direct call in assume_role.execute)
    - _helpers.find_repo_root (for call inside get_herd_content_path)
    """
    from unittest.mock import patch as _patch

    # Create a stack of patches
    class MultiPatch:
        def __enter__(self):
            self.patches = [
                _patch("herd_mcp.tools.assume_role.find_repo_root", return_value=repo_path),
                _patch("herd_mcp.tools._helpers.find_repo_root", return_value=repo_path),
            ]
            for p in self.patches:
                p.__enter__()
            return self

        def __exit__(self, *args):
            for p in reversed(self.patches):
                p.__exit__(*args)

    return MultiPatch()


def _patch_linear_tickets(tickets=None):
    """Return a patch for get_linear_tickets."""
    if tickets is None:
        tickets = []
    return patch(
        "herd_mcp.tools.assume_role.get_linear_tickets",
        new_callable=AsyncMock,
        return_value=tickets,
    )


def _patch_git_log(output="abc1234 2026-02-15 10:00:00 +0100 feat: something"):
    """Return a patch for subprocess.run used by git log."""
    from unittest.mock import MagicMock

    mock_result = MagicMock()
    mock_result.stdout = output
    mock_result.returncode = 0
    return patch(
        "herd_mcp.tools.assume_role.subprocess.run",
        return_value=mock_result,
    )


@pytest.mark.asyncio
async def test_assume_happy_path(mock_repo):
    """Test happy path: valid agent returns prompt with all sections."""
    with _patch_repo_root(mock_repo), _patch_linear_tickets(), _patch_git_log():
        result = await assume_role.execute("mason")

    assert "You are Mason." in result
    assert "## Role" in result
    assert "# Mason" in result
    assert "The builder." in result
    assert "## Craft Standards" in result
    assert "Mason craft rules." in result
    assert "## Project Guidelines" in result
    assert "Project guidelines here." in result
    assert "## Current State" in result
    assert "All systems operational." in result
    assert "## Recent Activity" in result
    assert "### Git (last 10 commits)" in result
    assert "### Assigned Tickets" in result
    assert "### Relevant Decisions (HDRs" in result
    assert "### Connected Decisions (graph)" in result
    assert "## Session Protocol" in result
    assert "Post session start to #herd-feed" in result


@pytest.mark.asyncio
async def test_assume_steve(mock_repo):
    """Test assuming Steve identity."""
    with _patch_repo_root(mock_repo), _patch_linear_tickets(), _patch_git_log():
        result = await assume_role.execute("steve")

    assert "You are Steve." in result
    assert "# Steve" in result
    assert "The orchestrator." in result
    assert "Steve craft rules." in result


@pytest.mark.asyncio
async def test_assume_unknown_agent():
    """Test that unknown agent returns clear error message."""
    result = await assume_role.execute("nonexistent_agent")

    assert "Unknown agent: 'nonexistent_agent'" in result
    assert "Known agents:" in result
    # Should list current agents but not legacy ones
    assert "mason" in result
    assert "grunt" not in result


@pytest.mark.asyncio
async def test_assume_case_insensitive(mock_repo):
    """Test that agent name matching is case-insensitive."""
    with _patch_repo_root(mock_repo), _patch_linear_tickets(), _patch_git_log():
        result = await assume_role.execute("MASON")

    assert "You are Mason." in result


@pytest.mark.asyncio
async def test_assume_missing_role_file(mock_repo):
    """Test fallback to package defaults when role file is missing from project.

    When fresco.md is not in the project .herd/roles/, it should fall back
    to the package-provided default role file.
    """
    with _patch_repo_root(mock_repo), _patch_linear_tickets(), _patch_git_log():
        result = await assume_role.execute("fresco")

    assert "You are Fresco." in result
    # Should find the package default role file, not error
    assert "## Role" in result
    assert "# Fresco" in result
    # Should not crash even though craft section is missing for fresco
    assert "## Craft Standards" in result


@pytest.mark.asyncio
async def test_assume_missing_craft_md(tmp_path):
    """Test graceful fallback when craft.md is missing from project.

    When craft.md is not in the project .herd/ directory, the code falls back
    to the package-provided craft.md. If both are missing, it shows a fallback
    message.
    """
    # Create minimal repo without craft.md
    (tmp_path / ".git").mkdir()
    roles_dir = tmp_path / ".herd" / "roles"
    roles_dir.mkdir(parents=True)
    (roles_dir / "mason.md").write_text("# Mason\nBuilder.")

    with _patch_repo_root(tmp_path), _patch_linear_tickets(), _patch_git_log():
        result = await assume_role.execute("mason")

    assert "You are Mason." in result
    # Either the package default craft.md is found (with Mason section),
    # or the fallback message is shown
    assert "## Craft Standards" in result
    # If package default is found, Mason craft section will be present;
    # if not, the fallback message is shown
    assert ("Mason" in result) or ("Craft section not found" in result)


@pytest.mark.asyncio
async def test_assume_missing_status_md(tmp_path):
    """Test graceful fallback when STATUS.md is missing."""
    (tmp_path / ".git").mkdir()
    roles_dir = tmp_path / ".herd" / "roles"
    roles_dir.mkdir(parents=True)
    (roles_dir / "mason.md").write_text("# Mason\nBuilder.")

    with _patch_repo_root(tmp_path), _patch_linear_tickets(), _patch_git_log():
        result = await assume_role.execute("mason")

    assert "You are Mason." in result
    assert "STATUS.md not found" in result


@pytest.mark.asyncio
async def test_assume_missing_claude_md(tmp_path):
    """Test graceful fallback when CLAUDE.md is missing."""
    (tmp_path / ".git").mkdir()
    roles_dir = tmp_path / ".herd" / "roles"
    roles_dir.mkdir(parents=True)
    (roles_dir / "mason.md").write_text("# Mason\nBuilder.")

    with _patch_repo_root(tmp_path), _patch_linear_tickets(), _patch_git_log():
        result = await assume_role.execute("mason")

    assert "You are Mason." in result
    assert "CLAUDE.md not found" in result


@pytest.mark.asyncio
async def test_assume_with_tickets(mock_repo):
    """Test that Linear tickets are included in prompt."""
    tickets = [
        {"identifier": "DBC-100", "title": "Fix bug", "status": "In Progress"},
        {"identifier": "DBC-101", "title": "Add feature", "status": "Backlog"},
    ]
    with (
        _patch_repo_root(mock_repo),
        _patch_linear_tickets(tickets),
        _patch_git_log(),
    ):
        result = await assume_role.execute("mason")

    assert "DBC-100: Fix bug [In Progress]" in result
    assert "DBC-101: Add feature [Backlog]" in result


@pytest.mark.asyncio
async def test_assume_semantic_hdrs_section(mock_repo):
    """Test that semantic HDR recall section is present in prompt."""
    with _patch_repo_root(mock_repo), _patch_linear_tickets(), _patch_git_log():
        result = await assume_role.execute("mason")

    # The prompt should have the semantic HDRs section
    assert "### Relevant Decisions (HDRs" in result


@pytest.mark.asyncio
async def test_assume_graph_decisions_section(mock_repo):
    """Test that graph decisions section is present in prompt."""
    with _patch_repo_root(mock_repo), _patch_linear_tickets(), _patch_git_log():
        result = await assume_role.execute("mason")

    # The prompt should have the graph decisions section
    assert "### Connected Decisions (graph)" in result


@pytest.mark.asyncio
async def test_assume_legacy_grunt_maps_to_mason(mock_repo):
    """Test that legacy 'grunt' maps to Mason identity."""
    with _patch_repo_root(mock_repo), _patch_linear_tickets(), _patch_git_log():
        result = await assume_role.execute("grunt")

    # Legacy name should display as the new name
    assert "You are Mason." in result


@pytest.mark.asyncio
async def test_assume_prompt_contains_all_section_headers(mock_repo):
    """Verify prompt contains all expected section headers."""
    with _patch_repo_root(mock_repo), _patch_linear_tickets(), _patch_git_log():
        result = await assume_role.execute("mason")

    expected_headers = [
        "## Role",
        "## Craft Standards",
        "## Project Guidelines",
        "## Current State",
        "## Recent Activity",
        "### Git (last 10 commits)",
        "### Assigned Tickets",
        "### Relevant Decisions (HDRs",
        "### Connected Decisions (graph)",
        "## Session Protocol",
    ]
    for header in expected_headers:
        assert header in result, f"Missing section header: {header}"


@pytest.mark.asyncio
async def test_assume_whitespace_agent_name(mock_repo):
    """Test that whitespace in agent name is handled."""
    with _patch_repo_root(mock_repo), _patch_linear_tickets(), _patch_git_log():
        result = await assume_role.execute("  mason  ")

    assert "You are Mason." in result


@pytest.mark.asyncio
async def test_assume_no_tickets():
    """Test prompt when no tickets are assigned."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        (tmp_path / ".git").mkdir()
        roles_dir = tmp_path / ".herd" / "roles"
        roles_dir.mkdir(parents=True)
        (roles_dir / "mason.md").write_text("# Mason")

        with (
            _patch_repo_root(tmp_path),
            _patch_linear_tickets([]),
            _patch_git_log(),
        ):
            result = await assume_role.execute("mason")

    assert "(none)" in result
