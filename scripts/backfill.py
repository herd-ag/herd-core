#!/usr/bin/env python3
"""Backfill HerdDB from Linear and GitHub history.

This script populates the DuckDB operational database with historical data:
- Linear tickets → ticket_def
- Linear projects → project_def
- GitHub PRs → pr_def
- GitHub commits → agent_instance_pr_activity

All backfilled records use agent_instance_code = 'backfill-000' (zero-key pattern).
The script is idempotent and can be safely re-run.

Usage:
    export LINEAR_API_KEY="lin_api_..."
    python backfill.py [--db-path path/to/herddb.duckdb]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path so we can import from herd_mcp
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from herd_mcp import db  # type: ignore[import-untyped]
from herd_mcp.linear_client import _graphql_request  # type: ignore[import-untyped]

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BACKFILL_AGENT_INSTANCE_CODE = "backfill-000"


def fetch_all_linear_tickets() -> list[dict]:
    """Fetch all DBC-* tickets from Linear using pagination.

    Returns:
        List of issue dicts with full details.
    """
    logger.info("Fetching all Linear tickets...")

    query = """
    query Issues($first: Int!, $after: String) {
      issues(first: $first, after: $after, filter: {team: {key: {eq: "DBC"}}}) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          id
          identifier
          title
          description
          createdAt
          updatedAt
          state {
            name
          }
          project {
            id
            name
          }
          estimate
        }
      }
    }
    """

    all_tickets = []
    has_next_page = True
    after_cursor = None

    while has_next_page:
        variables = {"first": 100, "after": after_cursor}
        result = _graphql_request(query, variables)

        data = result.get("data", {}).get("issues", {})
        nodes = data.get("nodes", [])
        all_tickets.extend(nodes)

        page_info = data.get("pageInfo", {})
        has_next_page = page_info.get("hasNextPage", False)
        after_cursor = page_info.get("endCursor")

        logger.info(f"Fetched {len(nodes)} tickets (total: {len(all_tickets)})")

    logger.info(f"Fetched {len(all_tickets)} total Linear tickets")
    return all_tickets


def fetch_all_linear_projects() -> list[dict]:
    """Fetch all Linear projects using pagination.

    Returns:
        List of project dicts with full details.
    """
    logger.info("Fetching all Linear projects...")

    query = """
    query Projects($first: Int!, $after: String) {
      projects(first: $first, after: $after) {
        pageInfo {
          hasNextPage
          endCursor
        }
        nodes {
          id
          name
          description
          state
          createdAt
          updatedAt
        }
      }
    }
    """

    all_projects = []
    has_next_page = True
    after_cursor = None

    while has_next_page:
        variables = {"first": 100, "after": after_cursor}
        result = _graphql_request(query, variables)

        data = result.get("data", {}).get("projects", {})
        nodes = data.get("nodes", [])
        all_projects.extend(nodes)

        page_info = data.get("pageInfo", {})
        has_next_page = page_info.get("hasNextPage", False)
        after_cursor = page_info.get("endCursor")

        logger.info(f"Fetched {len(nodes)} projects (total: {len(all_projects)})")

    logger.info(f"Fetched {len(all_projects)} total Linear projects")
    return all_projects


def fetch_all_github_prs() -> list[dict]:
    """Fetch all merged GitHub PRs.

    Returns:
        List of PR dicts from gh CLI.
    """
    logger.info("Fetching all GitHub PRs...")

    cmd = [
        "gh",
        "pr",
        "list",
        "--repo",
        "dbt-conceptual/dbt-conceptual",
        "--state",
        "merged",
        "--limit",
        "1000",
        "--json",
        "number,title,author,headRefName,body,createdAt,mergedAt,additions,deletions,changedFiles",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    prs: list[dict] = json.loads(result.stdout)

    logger.info(f"Fetched {len(prs)} merged GitHub PRs")
    return prs


def fetch_pr_commits(pr_number: int) -> list[dict]:
    """Fetch all commits for a specific PR.

    Args:
        pr_number: GitHub PR number.

    Returns:
        List of commit dicts.
    """
    cmd = [
        "gh",
        "pr",
        "view",
        str(pr_number),
        "--repo",
        "dbt-conceptual/dbt-conceptual",
        "--json",
        "commits",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data: dict = json.loads(result.stdout)
    commits: list[dict] = data.get("commits", [])
    return commits


def extract_ticket_code_from_pr(pr: dict) -> str | None:
    """Extract ticket code from PR title or branch name.

    Args:
        pr: PR dict from GitHub.

    Returns:
        Ticket code like 'DBC-120' if found, None otherwise.
    """
    # Try title first
    title = pr.get("title", "")
    match = re.search(r"\bDBC-\d+\b", title)
    if match:
        return match.group(0)

    # Try branch name
    branch = pr.get("headRefName", "")
    match = re.search(r"\bDBC-\d+\b", branch, re.IGNORECASE)
    if match:
        return match.group(0).upper()

    # Try body
    body = pr.get("body", "") or ""
    match = re.search(r"\bDBC-\d+\b", body)
    if match:
        return match.group(0)

    return None


def extract_agent_code_from_branch(branch_name: str) -> str | None:
    """Extract agent code from branch name (e.g., 'herd/grunt/dbc-120' → 'grunt').

    Args:
        branch_name: Git branch name.

    Returns:
        Agent code if found, None otherwise.
    """
    match = re.match(r"herd/([^/]+)/", branch_name)
    if match:
        return match.group(1)
    return None


def parse_iso_timestamp(iso_str: str | None) -> datetime | None:
    """Parse ISO 8601 timestamp string to datetime.

    Args:
        iso_str: ISO timestamp string (e.g., '2024-01-15T10:30:00Z').

    Returns:
        datetime object or None if parsing fails.
    """
    if not iso_str:
        return None
    try:
        # Handle both formats: with and without microseconds
        if "." in iso_str:
            return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        else:
            return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return None


def upsert_projects(conn: db.duckdb.DuckDBPyConnection, projects: list[dict]) -> None:  # type: ignore[name-defined]
    """Upsert Linear projects into project_def.

    Args:
        conn: DuckDB connection.
        projects: List of Linear project dicts.
    """
    logger.info(f"Upserting {len(projects)} projects...")

    for project in projects:
        project_code = project.get("id")
        if not project_code:
            continue

        created_at = parse_iso_timestamp(project.get("createdAt"))
        modified_at = parse_iso_timestamp(project.get("updatedAt"))

        # Check if exists
        existing = conn.execute(
            "SELECT project_code FROM herd.project_def WHERE project_code = ?",
            [project_code],
        ).fetchone()

        if existing:
            # Update
            conn.execute(
                """
                UPDATE herd.project_def
                SET project_title = ?,
                    project_description = ?,
                    project_status = ?,
                    modified_at = ?
                WHERE project_code = ?
                """,
                [
                    project.get("name"),
                    project.get("description"),
                    project.get("state"),
                    modified_at,
                    project_code,
                ],
            )
        else:
            # Insert
            conn.execute(
                """
                INSERT INTO herd.project_def (
                    project_code, initiative_code, project_title,
                    project_description, project_status,
                    created_at, modified_at, deleted_at
                )
                VALUES (?, NULL, ?, ?, ?, ?, ?, NULL)
                """,
                [
                    project_code,
                    project.get("name"),
                    project.get("description"),
                    project.get("state"),
                    created_at,
                    modified_at,
                ],
            )

    logger.info(f"Upserted {len(projects)} projects")


def upsert_tickets(conn: db.duckdb.DuckDBPyConnection, tickets: list[dict]) -> None:  # type: ignore[name-defined]
    """Upsert Linear tickets into ticket_def.

    Args:
        conn: DuckDB connection.
        tickets: List of Linear ticket dicts.
    """
    logger.info(f"Upserting {len(tickets)} tickets...")

    for ticket in tickets:
        ticket_code = ticket.get("identifier")
        if not ticket_code:
            continue

        project = ticket.get("project")
        project_code = project.get("id") if project else None

        state = ticket.get("state", {})
        current_status = state.get("name") if state else None

        created_at = parse_iso_timestamp(ticket.get("createdAt"))
        modified_at = parse_iso_timestamp(ticket.get("updatedAt"))

        # Check if exists
        existing = conn.execute(
            "SELECT ticket_code FROM herd.ticket_def WHERE ticket_code = ?",
            [ticket_code],
        ).fetchone()

        if existing:
            # Update
            conn.execute(
                """
                UPDATE herd.ticket_def
                SET project_code = ?,
                    ticket_title = ?,
                    ticket_description = ?,
                    ticket_tshirt_size = ?,
                    ticket_current_status = ?,
                    modified_at = ?
                WHERE ticket_code = ?
                """,
                [
                    project_code,
                    ticket.get("title"),
                    ticket.get("description"),
                    ticket.get("estimate"),
                    current_status,
                    modified_at,
                    ticket_code,
                ],
            )
        else:
            # Insert
            conn.execute(
                """
                INSERT INTO herd.ticket_def (
                    ticket_code, project_code, ticket_title,
                    ticket_description, ticket_tshirt_size, ticket_acceptance_criteria,
                    ticket_current_status, current_sprint_code,
                    created_at, modified_at, deleted_at
                )
                VALUES (?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?, NULL)
                """,
                [
                    ticket_code,
                    project_code,
                    ticket.get("title"),
                    ticket.get("description"),
                    ticket.get("estimate"),
                    current_status,
                    created_at,
                    modified_at,
                ],
            )

    logger.info(f"Upserted {len(tickets)} tickets")


def upsert_prs(conn: db.duckdb.DuckDBPyConnection, prs: list[dict]) -> None:  # type: ignore[name-defined]
    """Upsert GitHub PRs into pr_def.

    Args:
        conn: DuckDB connection.
        prs: List of GitHub PR dicts.
    """
    logger.info(f"Upserting {len(prs)} PRs...")

    for pr in prs:
        pr_number = pr.get("number")
        if not pr_number:
            continue

        pr_code = f"PR-{pr_number}"
        ticket_code = extract_ticket_code_from_pr(pr)
        branch_name = pr.get("headRefName", "")

        created_at = parse_iso_timestamp(pr.get("createdAt"))
        merged_at = parse_iso_timestamp(pr.get("mergedAt"))

        # Check if exists
        existing = conn.execute(
            "SELECT pr_code FROM herd.pr_def WHERE pr_code = ?", [pr_code]
        ).fetchone()

        if existing:
            # Update
            conn.execute(
                """
                UPDATE herd.pr_def
                SET ticket_code = ?,
                    pr_branch_name = ?,
                    pr_title = ?,
                    pr_lines_added = ?,
                    pr_lines_deleted = ?,
                    pr_files_changed = ?,
                    pr_merged_at = ?,
                    modified_at = ?
                WHERE pr_code = ?
                """,
                [
                    ticket_code,
                    branch_name,
                    pr.get("title"),
                    pr.get("additions"),
                    pr.get("deletions"),
                    pr.get("changedFiles"),
                    merged_at,
                    datetime.now(),
                    pr_code,
                ],
            )
        else:
            # Insert
            conn.execute(
                """
                INSERT INTO herd.pr_def (
                    pr_code, ticket_code, creator_agent_instance_code,
                    pr_branch_name, pr_title,
                    pr_lines_added, pr_lines_deleted, pr_files_changed,
                    pr_merged_at, pr_closed_at,
                    created_at, modified_at, deleted_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL)
                """,
                [
                    pr_code,
                    ticket_code,
                    BACKFILL_AGENT_INSTANCE_CODE,
                    branch_name,
                    pr.get("title"),
                    pr.get("additions"),
                    pr.get("deletions"),
                    pr.get("changedFiles"),
                    merged_at,
                    created_at,
                    datetime.now(),
                ],
            )

    logger.info(f"Upserted {len(prs)} PRs")


def insert_pr_commits(conn: db.duckdb.DuckDBPyConnection, pr_number: int, pr_code: str, branch_name: str) -> None:  # type: ignore[name-defined]
    """Insert PR commits into agent_instance_pr_activity.

    Args:
        conn: DuckDB connection.
        pr_number: GitHub PR number.
        pr_code: PR code (e.g., 'PR-120').
        branch_name: Git branch name.
    """
    try:
        commits = fetch_pr_commits(pr_number)

        for commit in commits:
            commit_sha = commit.get("oid")
            if not commit_sha:
                continue

            # Check if commit already exists
            existing = conn.execute(
                """
                SELECT 1 FROM herd.agent_instance_pr_activity
                WHERE pr_code = ? AND pr_commit_hash = ?
                """,
                [pr_code, commit_sha],
            ).fetchone()

            if existing:
                continue

            committed_date = parse_iso_timestamp(commit.get("committedDate"))

            conn.execute(
                """
                INSERT INTO herd.agent_instance_pr_activity (
                    agent_instance_code, pr_code, pr_event_type,
                    pr_commit_hash, pr_push_lines_added, pr_push_lines_deleted,
                    pr_activity_detail, created_at
                )
                VALUES (?, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                [
                    BACKFILL_AGENT_INSTANCE_CODE,
                    pr_code,
                    "commit",
                    commit_sha,
                    commit.get("messageHeadline", ""),
                    committed_date or datetime.now(),
                ],
            )

    except Exception as e:
        logger.warning(f"Failed to fetch commits for PR {pr_number}: {e}")


def ensure_backfill_agent_instance(conn: db.duckdb.DuckDBPyConnection) -> None:  # type: ignore[name-defined]
    """Ensure backfill-000 agent instance exists.

    Args:
        conn: DuckDB connection.
    """
    existing = conn.execute(
        "SELECT agent_instance_code FROM herd.agent_instance WHERE agent_instance_code = ?",
        [BACKFILL_AGENT_INSTANCE_CODE],
    ).fetchone()

    if not existing:
        logger.info(f"Creating agent instance: {BACKFILL_AGENT_INSTANCE_CODE}")
        conn.execute(
            """
            INSERT INTO herd.agent_instance (
                agent_instance_code, agent_code, model_code,
                craft_version_code, personality_version_code, ticket_code,
                spawned_by_agent_instance_code,
                agent_instance_started_at, agent_instance_ended_at,
                agent_instance_outcome
            )
            VALUES (?, NULL, NULL, NULL, NULL, NULL, NULL, ?, NULL, 'backfill')
            """,
            [BACKFILL_AGENT_INSTANCE_CODE, datetime.now()],
        )


def main() -> None:
    """Main backfill script entry point."""
    parser = argparse.ArgumentParser(
        description="Backfill HerdDB from Linear and GitHub history"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to DuckDB database file (defaults to HERD_DB_PATH env var or .herd/herddb.duckdb)",
    )
    args = parser.parse_args()

    logger.info("Starting historical backfill...")

    # Get database connection
    conn = db.get_connection(args.db_path)

    try:
        # Ensure backfill agent instance exists
        ensure_backfill_agent_instance(conn)

        # Fetch data from Linear
        projects = fetch_all_linear_projects()
        tickets = fetch_all_linear_tickets()

        # Fetch data from GitHub
        prs = fetch_all_github_prs()

        # Upsert into database
        upsert_projects(conn, projects)
        upsert_tickets(conn, tickets)
        upsert_prs(conn, prs)

        # Insert commit activity for each PR
        logger.info("Fetching commit history for all PRs...")
        for pr in prs:
            pr_number = pr.get("number")
            if pr_number is None:
                continue
            pr_code = f"PR-{pr_number}"
            branch_name = pr.get("headRefName", "")

            insert_pr_commits(conn, pr_number, pr_code, branch_name)

        logger.info("Backfill complete!")

        # Print summary
        project_count = conn.execute(
            "SELECT COUNT(*) FROM herd.project_def"
        ).fetchone()[0]
        ticket_count = conn.execute("SELECT COUNT(*) FROM herd.ticket_def").fetchone()[
            0
        ]
        pr_count = conn.execute("SELECT COUNT(*) FROM herd.pr_def").fetchone()[0]
        commit_count = conn.execute(
            "SELECT COUNT(*) FROM herd.agent_instance_pr_activity WHERE agent_instance_code = ?",
            [BACKFILL_AGENT_INSTANCE_CODE],
        ).fetchone()[0]

        logger.info("Database summary:")
        logger.info(f"  Projects: {project_count}")
        logger.info(f"  Tickets: {ticket_count}")
        logger.info(f"  PRs: {pr_count}")
        logger.info(f"  Commits: {commit_count}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
