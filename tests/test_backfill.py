"""Tests for backfill.py script."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import backfill
from herd_mcp import db


@pytest.fixture
def mock_linear_tickets():
    """Mock Linear ticket data."""
    return [
        {
            "id": "ticket-1",
            "identifier": "DBC-1",
            "title": "Test Ticket 1",
            "description": "Description 1",
            "createdAt": "2024-01-01T10:00:00Z",
            "updatedAt": "2024-01-02T10:00:00Z",
            "state": {"name": "Done"},
            "project": {"id": "proj-1", "name": "Test Project"},
            "estimate": 3,
        },
        {
            "id": "ticket-2",
            "identifier": "DBC-2",
            "title": "Test Ticket 2",
            "description": "Description 2",
            "createdAt": "2024-01-03T10:00:00Z",
            "updatedAt": "2024-01-04T10:00:00Z",
            "state": {"name": "In Progress"},
            "project": None,
            "estimate": 5,
        },
    ]


@pytest.fixture
def mock_linear_projects():
    """Mock Linear project data."""
    return [
        {
            "id": "proj-1",
            "name": "Test Project",
            "description": "A test project",
            "state": "Active",
            "createdAt": "2024-01-01T09:00:00Z",
            "updatedAt": "2024-01-02T09:00:00Z",
        },
        {
            "id": "proj-2",
            "name": "Another Project",
            "description": "Another test project",
            "state": "Completed",
            "createdAt": "2024-01-05T09:00:00Z",
            "updatedAt": "2024-01-06T09:00:00Z",
        },
    ]


@pytest.fixture
def mock_github_prs():
    """Mock GitHub PR data."""
    return [
        {
            "number": 100,
            "title": "feat: implement DBC-1",
            "headRefName": "herd/mason/dbc-1-feature",
            "body": "Implements DBC-1",
            "createdAt": "2024-01-10T10:00:00Z",
            "mergedAt": "2024-01-11T10:00:00Z",
            "additions": 100,
            "deletions": 20,
            "changedFiles": 5,
            "author": {"login": "mason"},
        },
        {
            "number": 101,
            "title": "[mason] fix: update something",
            "headRefName": "herd/fresco/feature-branch",
            "body": "No ticket reference",
            "createdAt": "2024-01-12T10:00:00Z",
            "mergedAt": "2024-01-13T10:00:00Z",
            "additions": 50,
            "deletions": 10,
            "changedFiles": 2,
            "author": {"login": "fresco"},
        },
    ]


@pytest.fixture
def mock_commits():
    """Mock GitHub commit data."""
    return [
        {
            "oid": "abc123",
            "messageHeadline": "feat: first commit",
            "committedDate": "2024-01-10T11:00:00Z",
        },
        {
            "oid": "def456",
            "messageHeadline": "fix: second commit",
            "committedDate": "2024-01-10T12:00:00Z",
        },
    ]


def test_extract_ticket_code_from_pr():
    """Test ticket code extraction from PR title and branch."""
    # From title
    pr = {"title": "feat: implement DBC-123", "headRefName": "feature-branch"}
    assert backfill.extract_ticket_code_from_pr(pr) == "DBC-123"

    # From branch name
    pr = {"title": "feat: something", "headRefName": "herd/mason/dbc-456-feature"}
    assert backfill.extract_ticket_code_from_pr(pr) == "DBC-456"

    # From body
    pr = {
        "title": "feat: something",
        "headRefName": "feature",
        "body": "Fixes DBC-789",
    }
    assert backfill.extract_ticket_code_from_pr(pr) == "DBC-789"

    # No ticket
    pr = {"title": "feat: something", "headRefName": "feature", "body": None}
    assert backfill.extract_ticket_code_from_pr(pr) is None


def test_extract_agent_code_from_branch():
    """Test agent code extraction from branch name."""
    assert backfill.extract_agent_code_from_branch("herd/mason/dbc-123") == "mason"
    assert (
        backfill.extract_agent_code_from_branch("herd/fresco/feature-branch")
        == "fresco"
    )
    assert backfill.extract_agent_code_from_branch("feature-branch") is None
    assert backfill.extract_agent_code_from_branch("main") is None


def test_extract_agent_code_from_commit_prefix():
    """Test agent code extraction from commit subject prefix."""
    assert (
        backfill.extract_agent_code_from_commit_prefix("[mason] fix: something")
        == "mason"
    )
    assert (
        backfill.extract_agent_code_from_commit_prefix("[steve] feat: something")
        == "steve"
    )
    assert (
        backfill.extract_agent_code_from_commit_prefix("[wardenstein] review: qa pass")
        == "wardenstein"
    )
    # Unknown agent
    assert (
        backfill.extract_agent_code_from_commit_prefix("[unknown] fix: something")
        is None
    )
    # No prefix
    assert (
        backfill.extract_agent_code_from_commit_prefix("Merge pull request #5") is None
    )


def test_repo_short_name():
    """Test repo short name extraction."""
    assert backfill.repo_short_name("herd-ag/herd-core") == "herd-core"
    assert backfill.repo_short_name("herd-ag/herd-store-duckdb") == "herd-store-duckdb"


def test_parse_iso_timestamp():
    """Test ISO timestamp parsing."""
    dt = backfill.parse_iso_timestamp("2024-01-15T10:30:00Z")
    assert dt is not None
    assert dt.year == 2024
    assert dt.month == 1
    assert dt.day == 15
    assert dt.hour == 10
    assert dt.minute == 30

    # With microseconds
    dt = backfill.parse_iso_timestamp("2024-01-15T10:30:00.123456Z")
    assert dt is not None

    # None input
    assert backfill.parse_iso_timestamp(None) is None

    # Invalid format (should not crash)
    result = backfill.parse_iso_timestamp("invalid")
    assert result is None


def test_upsert_projects(mock_linear_projects):
    """Test project upsert logic."""
    conn = db.get_connection(":memory:")

    # First upsert (inserts)
    backfill.upsert_projects(conn, mock_linear_projects)

    result = conn.execute("SELECT COUNT(*) FROM herd.project_def").fetchone()
    assert result[0] == 2

    # Verify data
    project = conn.execute(
        "SELECT * FROM herd.project_def WHERE project_code = ?", ["proj-1"]
    ).fetchone()
    assert project is not None
    # project_code, initiative_code, project_title, ...
    assert project[2] == "Test Project"
    assert project[3] == "A test project"
    assert project[4] == "Active"

    # Second upsert (updates)
    modified_projects = mock_linear_projects.copy()
    modified_projects[0]["description"] = "Updated description"
    backfill.upsert_projects(conn, modified_projects)

    # Still 2 projects
    result = conn.execute("SELECT COUNT(*) FROM herd.project_def").fetchone()
    assert result[0] == 2

    # Verify update
    project = conn.execute(
        "SELECT project_description FROM herd.project_def WHERE project_code = ?",
        ["proj-1"],
    ).fetchone()
    assert project[0] == "Updated description"

    conn.close()


def test_upsert_tickets(mock_linear_tickets):
    """Test ticket upsert logic."""
    conn = db.get_connection(":memory:")

    # First upsert (inserts)
    backfill.upsert_tickets(conn, mock_linear_tickets)

    result = conn.execute("SELECT COUNT(*) FROM herd.ticket_def").fetchone()
    assert result[0] == 2

    # Verify data
    ticket = conn.execute(
        "SELECT * FROM herd.ticket_def WHERE ticket_code = ?", ["DBC-1"]
    ).fetchone()
    assert ticket is not None
    # ticket_code, project_code, ticket_title, ...
    assert ticket[2] == "Test Ticket 1"
    assert ticket[1] == "proj-1"
    assert ticket[6] == "Done"

    # Second upsert (updates)
    modified_tickets = mock_linear_tickets.copy()
    modified_tickets[0]["title"] = "Updated Title"
    backfill.upsert_tickets(conn, modified_tickets)

    # Still 2 tickets
    result = conn.execute("SELECT COUNT(*) FROM herd.ticket_def").fetchone()
    assert result[0] == 2

    # Verify update
    ticket = conn.execute(
        "SELECT ticket_title FROM herd.ticket_def WHERE ticket_code = ?", ["DBC-1"]
    ).fetchone()
    assert ticket[0] == "Updated Title"

    conn.close()


def test_upsert_prs(mock_github_prs):
    """Test PR upsert logic with repo-prefixed PR codes."""
    conn = db.get_connection(":memory:")
    repo = "herd-ag/herd-core"

    # First upsert (inserts)
    backfill.upsert_prs(conn, repo, mock_github_prs)

    result = conn.execute("SELECT COUNT(*) FROM herd.pr_def").fetchone()
    assert result[0] == 2

    # Verify data (PR codes are now repo-prefixed)
    pr = conn.execute(
        "SELECT * FROM herd.pr_def WHERE pr_code = ?", ["herd-core/PR-100"]
    ).fetchone()
    assert pr is not None
    # pr_code, ticket_code, creator_agent_instance_code, pr_branch_name, pr_title, ...
    assert pr[1] == "DBC-1"
    assert pr[2] == backfill.BACKFILL_AGENT_INSTANCE_CODE
    assert pr[3] == "herd/mason/dbc-1-feature"
    assert pr[4] == "feat: implement DBC-1"
    assert pr[5] == 100  # lines_added
    assert pr[6] == 20  # lines_deleted

    # Second upsert (updates)
    modified_prs = mock_github_prs.copy()
    modified_prs[0]["title"] = "Updated PR title"
    backfill.upsert_prs(conn, repo, modified_prs)

    # Still 2 PRs
    result = conn.execute("SELECT COUNT(*) FROM herd.pr_def").fetchone()
    assert result[0] == 2

    # Verify update
    pr = conn.execute(
        "SELECT pr_title FROM herd.pr_def WHERE pr_code = ?", ["herd-core/PR-100"]
    ).fetchone()
    assert pr[0] == "Updated PR title"

    conn.close()


def test_insert_pr_commits(mock_commits):
    """Test PR commit insertion with repo parameter."""
    conn = db.get_connection(":memory:")
    repo = "herd-ag/herd-core"
    pr_code = "herd-core/PR-100"

    with patch("backfill.fetch_pr_commits", return_value=mock_commits):
        backfill.insert_pr_commits(conn, repo, 100, pr_code)

    result = conn.execute(
        "SELECT COUNT(*) FROM herd.agent_instance_pr_activity"
    ).fetchone()
    assert result[0] == 2

    # Verify commit data
    commit = conn.execute(
        "SELECT * FROM herd.agent_instance_pr_activity WHERE pr_commit_hash = ?",
        ["abc123"],
    ).fetchone()
    assert commit is not None
    # agent_instance_code, pr_code, pr_event_type, pr_commit_hash, ...
    assert commit[0] == backfill.BACKFILL_AGENT_INSTANCE_CODE
    assert commit[1] == pr_code
    assert commit[2] == "commit"
    assert commit[3] == "abc123"

    # Test idempotency - re-insert same commits
    with patch("backfill.fetch_pr_commits", return_value=mock_commits):
        backfill.insert_pr_commits(conn, repo, 100, pr_code)

    # Still only 2 commits
    result = conn.execute(
        "SELECT COUNT(*) FROM herd.agent_instance_pr_activity"
    ).fetchone()
    assert result[0] == 2

    conn.close()


def test_ensure_stg_git_commit_table():
    """Test stg_git_commit table creation."""
    conn = db.get_connection(":memory:")

    # Table should not exist yet
    tables = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'herd' AND table_name = 'stg_git_commit'"
    ).fetchall()
    assert len(tables) == 0

    # Create table
    backfill.ensure_stg_git_commit_table(conn)

    # Table should exist now
    tables = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'herd' AND table_name = 'stg_git_commit'"
    ).fetchall()
    assert len(tables) == 1

    # Calling again is idempotent (CREATE IF NOT EXISTS)
    backfill.ensure_stg_git_commit_table(conn)

    conn.close()


def test_backfill_git_log_missing_repos():
    """Test git log backfill when repos are missing."""
    conn = db.get_connection(":memory:")

    # Patch HERD_REPOS to use non-existent paths
    with patch.object(backfill, "HERD_REPOS", ["herd-ag/nonexistent-repo"]):
        inserted = backfill.backfill_git_log(conn)

    # No commits inserted (repo doesn't exist)
    assert inserted == 0

    # Table was still created
    tables = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'herd' AND table_name = 'stg_git_commit'"
    ).fetchall()
    assert len(tables) == 1

    conn.close()


def test_ensure_backfill_agent_instance():
    """Test backfill agent instance creation."""
    conn = db.get_connection(":memory:")

    # First call creates instance
    backfill.ensure_backfill_agent_instance(conn)

    result = conn.execute(
        "SELECT COUNT(*) FROM herd.agent_instance WHERE agent_instance_code = ?",
        [backfill.BACKFILL_AGENT_INSTANCE_CODE],
    ).fetchone()
    assert result[0] == 1

    # Second call is idempotent
    backfill.ensure_backfill_agent_instance(conn)

    result = conn.execute(
        "SELECT COUNT(*) FROM herd.agent_instance WHERE agent_instance_code = ?",
        [backfill.BACKFILL_AGENT_INSTANCE_CODE],
    ).fetchone()
    assert result[0] == 1

    # Verify instance data
    instance = conn.execute(
        "SELECT * FROM herd.agent_instance WHERE agent_instance_code = ?",
        [backfill.BACKFILL_AGENT_INSTANCE_CODE],
    ).fetchone()
    assert instance is not None
    assert instance[9] == "backfill"  # agent_instance_outcome

    conn.close()


@patch("backfill.fetch_all_linear_projects")
@patch("backfill.fetch_all_linear_tickets")
@patch("backfill.fetch_all_github_prs")
@patch("backfill.insert_pr_commits")
def test_main_integration(
    mock_insert_commits,
    mock_fetch_prs,
    mock_fetch_tickets,
    mock_fetch_projects,
    mock_linear_projects,
    mock_linear_tickets,
    mock_github_prs,
):
    """Test full backfill integration."""
    mock_fetch_projects.return_value = mock_linear_projects
    mock_fetch_tickets.return_value = mock_linear_tickets
    mock_fetch_prs.return_value = mock_github_prs

    conn = db.get_connection(":memory:")
    repo = "herd-ag/herd-core"

    # Manually run the main logic (avoiding argparse and sys.exit)
    backfill.ensure_backfill_agent_instance(conn)
    projects = mock_fetch_projects()
    tickets = mock_fetch_tickets()
    prs = mock_fetch_prs()

    backfill.upsert_projects(conn, projects)
    backfill.upsert_tickets(conn, tickets)
    backfill.upsert_prs(conn, repo, prs)

    # Verify all data loaded
    project_count = conn.execute("SELECT COUNT(*) FROM herd.project_def").fetchone()[0]
    ticket_count = conn.execute("SELECT COUNT(*) FROM herd.ticket_def").fetchone()[0]
    pr_count = conn.execute("SELECT COUNT(*) FROM herd.pr_def").fetchone()[0]

    assert project_count == 2
    assert ticket_count == 2
    assert pr_count == 2

    conn.close()
