"""Tests for shared helper functions in _helpers.py."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from herd_mcp.tools._helpers import (
    CRAFT_SECTION_MAP,
    extract_craft_section,
    find_repo_root,
    get_handoffs,
    get_recent_hdrs,
    read_file_safe,
    read_status_md,
)

# ---- read_file_safe ----


def test_read_file_safe_existing_file():
    """Test reading an existing file returns its content."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("hello world")
        f.flush()
        result = read_file_safe(Path(f.name))
    assert result == "hello world"


def test_read_file_safe_missing_file():
    """Test reading a missing file returns None."""
    result = read_file_safe(Path("/nonexistent/path/to/file.md"))
    assert result is None


def test_read_file_safe_empty_file():
    """Test reading an empty file returns empty string."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("")
        f.flush()
        result = read_file_safe(Path(f.name))
    assert result == ""


# ---- extract_craft_section ----

SAMPLE_CRAFT = """# The Herd — Craft Standards

## All Agents — Shared Standards
Shared content here.

## Mason — Backend Craft Standards
Mason specific content.
More mason content.

## Fresco — Frontend Craft Standards
Fresco content.

## Scribe — Documentation Standards
Scribe content.

## Wardenstein — QA Craft Standards
Wardenstein content.

## Steve — Coordination Craft Standards
Steve content.

## Leonardo — Coordination Craft Standards
Leonardo content.
"""


def test_extract_craft_section_mason():
    """Test extracting Mason section from craft.md."""
    section = extract_craft_section(SAMPLE_CRAFT, "mason")
    assert "## Mason — Backend Craft Standards" in section
    assert "Mason specific content" in section
    assert "More mason content" in section
    assert "Fresco" not in section


def test_extract_craft_section_fresco():
    """Test extracting Fresco section from craft.md."""
    section = extract_craft_section(SAMPLE_CRAFT, "fresco")
    assert "## Fresco — Frontend Craft Standards" in section
    assert "Fresco content" in section
    assert "Scribe" not in section


def test_extract_craft_section_steve():
    """Test extracting Steve section from craft.md."""
    section = extract_craft_section(SAMPLE_CRAFT, "steve")
    assert "## Steve — Coordination Craft Standards" in section
    assert "Steve content" in section


def test_extract_craft_section_unknown_agent():
    """Test extracting section for unknown agent returns empty string."""
    section = extract_craft_section(SAMPLE_CRAFT, "nonexistent")
    assert section == ""


def test_extract_craft_section_legacy_grunt():
    """Test that legacy 'grunt' maps to Mason section."""
    section = extract_craft_section(SAMPLE_CRAFT, "grunt")
    assert "## Mason — Backend Craft Standards" in section
    assert "Mason specific content" in section


def test_extract_craft_section_legacy_pikasso():
    """Test that legacy 'pikasso' maps to Fresco section."""
    section = extract_craft_section(SAMPLE_CRAFT, "pikasso")
    assert "## Fresco — Frontend Craft Standards" in section
    assert "Fresco content" in section


def test_extract_craft_section_legacy_mini_mao():
    """Test that legacy 'mini-mao' maps to Steve section."""
    section = extract_craft_section(SAMPLE_CRAFT, "mini-mao")
    assert "## Steve — Coordination Craft Standards" in section
    assert "Steve content" in section


def test_extract_craft_section_legacy_shakesquill():
    """Test that legacy 'shakesquill' maps to Scribe section."""
    section = extract_craft_section(SAMPLE_CRAFT, "shakesquill")
    assert "## Scribe — Documentation Standards" in section
    assert "Scribe content" in section


def test_extract_craft_section_empty_content():
    """Test extracting from empty content returns empty string."""
    section = extract_craft_section("", "mason")
    assert section == ""


# ---- read_status_md ----


def test_read_status_md_file_exists():
    """Test reading STATUS.md when it exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        herd_dir = Path(tmpdir) / ".herd"
        herd_dir.mkdir()
        status_file = herd_dir / "STATUS.md"
        status_file.write_text("# Status\nAll good.")
        result = read_status_md(Path(tmpdir))
        assert result["exists"] is True
        assert result["content"] == "# Status\nAll good."


def test_read_status_md_file_missing():
    """Test reading STATUS.md when it does not exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = read_status_md(Path(tmpdir))
        assert result["exists"] is False
        assert result["content"] is None


# ---- find_repo_root ----


def test_find_repo_root_from_repo_dir():
    """Test finding repo root when cwd is in a git repo."""
    import subprocess

    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
        from unittest.mock import patch

        with patch("herd_mcp.tools._helpers.Path.cwd", return_value=Path(tmpdir)):
            root = find_repo_root()
            assert root == Path(tmpdir)


def test_find_repo_root_from_subdir():
    """Test finding repo root from a subdirectory."""
    import subprocess

    with tempfile.TemporaryDirectory() as tmpdir:
        subprocess.run(["git", "init"], cwd=tmpdir, check=True, capture_output=True)
        sub = Path(tmpdir) / "a" / "b" / "c"
        sub.mkdir(parents=True)
        from unittest.mock import patch

        with patch("herd_mcp.tools._helpers.Path.cwd", return_value=sub):
            root = find_repo_root()
            assert root == Path(tmpdir)


def test_find_repo_root_raises_when_not_in_repo():
    """Test that find_repo_root raises RuntimeError outside a git repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        from unittest.mock import patch

        with patch("herd_mcp.tools._helpers.Path.cwd", return_value=Path(tmpdir)):
            with pytest.raises(RuntimeError, match="Could not find repository root"):
                find_repo_root()


# ---- get_handoffs ----


def test_get_handoffs_no_directory():
    """Test get_handoffs when handoffs directory does not exist."""
    from datetime import datetime, timedelta

    with tempfile.TemporaryDirectory() as tmpdir:
        result = get_handoffs(Path(tmpdir), datetime.now() - timedelta(days=7))
        assert result == []


def test_get_handoffs_with_files():
    """Test get_handoffs returns recent handoff files."""
    from datetime import datetime, timedelta

    with tempfile.TemporaryDirectory() as tmpdir:
        handoffs_dir = Path(tmpdir) / ".herd" / "handoffs"
        handoffs_dir.mkdir(parents=True)
        (handoffs_dir / "DBC-100.md").write_text("handoff content")
        result = get_handoffs(Path(tmpdir), datetime.now() - timedelta(days=7))
        assert len(result) == 1
        assert result[0]["filename"] == "DBC-100.md"
        assert result[0]["ticket"] == "DBC-100"


# ---- get_recent_hdrs ----


def test_get_recent_hdrs_no_directory():
    """Test get_recent_hdrs when decisions directory does not exist."""
    from datetime import datetime, timedelta

    with tempfile.TemporaryDirectory() as tmpdir:
        result = get_recent_hdrs(Path(tmpdir), datetime.now() - timedelta(days=7))
        assert result == []


def test_get_recent_hdrs_with_files():
    """Test get_recent_hdrs returns recent HDR files."""
    from datetime import datetime, timedelta

    with tempfile.TemporaryDirectory() as tmpdir:
        decisions_dir = Path(tmpdir) / ".herd" / "decisions"
        decisions_dir.mkdir(parents=True)
        (decisions_dir / "0024-team-naming.md").write_text("HDR content")
        result = get_recent_hdrs(Path(tmpdir), datetime.now() - timedelta(days=7))
        assert len(result) == 1
        assert result[0]["filename"] == "0024-team-naming.md"
        assert "Team Naming" in result[0]["title"]


# ---- CRAFT_SECTION_MAP ----


def test_craft_section_map_has_all_current_agents():
    """Test that section map includes all current HDR-0024 agent names."""
    current_agents = [
        "mason",
        "fresco",
        "scribe",
        "wardenstein",
        "steve",
        "leonardo",
        "vigil",
        "rook",
    ]
    for agent in current_agents:
        assert agent in CRAFT_SECTION_MAP, f"Missing current agent: {agent}"


def test_craft_section_map_has_legacy_aliases():
    """Test that section map includes legacy name aliases."""
    legacy_map = {
        "grunt": "## Mason — Backend Craft Standards",
        "pikasso": "## Fresco — Frontend Craft Standards",
        "mini-mao": "## Steve — Coordination Craft Standards",
        "shakesquill": "## Scribe — Documentation Standards",
    }
    for legacy_name, expected_header in legacy_map.items():
        assert CRAFT_SECTION_MAP[legacy_name] == expected_header
