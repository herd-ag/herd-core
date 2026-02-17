#!/usr/bin/env python3
"""Backfill HerdDB from Linear, GitHub history, and local git logs.

This script populates the DuckDB operational database with historical data:
- Linear tickets -> ticket_def
- Linear projects -> project_def
- GitHub PRs -> pr_def (across all herd-ag repos)
- GitHub commits -> agent_instance_pr_activity
- Local git log -> stg_git_commit (staging table for commit history)

All backfilled records use agent_instance_code = 'backfill-000' (zero-key pattern).
The script is idempotent and can be safely re-run.

Usage:
    export HERD_TICKET_LINEAR_API_KEY="lin_api_..."
    python scripts/backfill.py [--db-path path/to/herddb.duckdb]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

import duckdb

from herd_mcp.db import get_connection
from herd_mcp.linear_client import _graphql_request  # type: ignore[import-untyped]

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BACKFILL_AGENT_INSTANCE_CODE = "backfill-000"

# All herd-ag repos to backfill from GitHub and local git logs
HERD_REPOS = [
    "herd-ag/herd-core",
    "herd-ag/herd-store-duckdb",
    "herd-ag/herd-ticket-linear",
    "herd-ag/herd-repo-github",
    "herd-ag/herd-agent-claude",
    "herd-ag/herd-notify-slack",
]

# Known herd agent codes for git log extraction
KNOWN_AGENTS = {
    "steve",
    "leonardo",
    "mason",
    "fresco",
    "wardenstein",
    "scribe",
    "vigil",
    "rook",
    "tufte",
}


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

    all_tickets: list[dict] = []
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

    all_projects: list[dict] = []
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


def fetch_all_github_prs(repo: str) -> list[dict]:
    """Fetch all merged GitHub PRs for a specific repo.

    Args:
        repo: GitHub repo in 'owner/name' format (e.g., 'herd-ag/herd-core').

    Returns:
        List of PR dicts from gh CLI.
    """
    logger.info(f"Fetching merged PRs from {repo}...")

    cmd = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "merged",
        "--limit",
        "1000",
        "--json",
        "number,title,author,headRefName,body,createdAt,mergedAt,"
        "additions,deletions,changedFiles",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    prs: list[dict] = json.loads(result.stdout)

    logger.info(f"Fetched {len(prs)} merged PRs from {repo}")
    return prs


def fetch_pr_commits(repo: str, pr_number: int) -> list[dict]:
    """Fetch all commits for a specific PR.

    Args:
        repo: GitHub repo in 'owner/name' format.
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
        repo,
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
    """Extract agent code from branch name (e.g., 'herd/mason/dbc-120' -> 'mason').

    Args:
        branch_name: Git branch name.

    Returns:
        Agent code if found, None otherwise.
    """
    match = re.match(r"herd/([^/]+)/", branch_name)
    if match:
        return match.group(1)
    return None


def extract_agent_code_from_commit_prefix(subject: str) -> str | None:
    """Extract agent code from commit subject prefix convention.

    Matches patterns like '[mason]', '[steve]', '[wardenstein]' at the start.

    Args:
        subject: Commit subject line.

    Returns:
        Agent code if found and recognized, None otherwise.
    """
    match = re.match(r"^\[([a-z]+)\]", subject)
    if match:
        agent = match.group(1)
        if agent in KNOWN_AGENTS:
            return agent
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
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def repo_short_name(repo: str) -> str:
    """Extract short repo name from 'owner/name' format.

    Args:
        repo: GitHub repo in 'owner/name' format.

    Returns:
        Short name (e.g., 'herd-core' from 'herd-ag/herd-core').
    """
    return repo.split("/")[-1]


def upsert_projects(conn: duckdb.DuckDBPyConnection, projects: list[dict]) -> None:
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


def upsert_tickets(conn: duckdb.DuckDBPyConnection, tickets: list[dict]) -> None:
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

        existing = conn.execute(
            "SELECT ticket_code FROM herd.ticket_def WHERE ticket_code = ?",
            [ticket_code],
        ).fetchone()

        if existing:
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
            conn.execute(
                """
                INSERT INTO herd.ticket_def (
                    ticket_code, project_code, ticket_title,
                    ticket_description, ticket_tshirt_size,
                    ticket_acceptance_criteria,
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


def upsert_prs(conn: duckdb.DuckDBPyConnection, repo: str, prs: list[dict]) -> None:
    """Upsert GitHub PRs into pr_def.

    PR codes are prefixed with the repo short name to avoid collisions
    across repos (e.g., 'herd-core/PR-5').

    Args:
        conn: DuckDB connection.
        repo: GitHub repo in 'owner/name' format.
        prs: List of GitHub PR dicts.
    """
    short = repo_short_name(repo)
    logger.info(f"Upserting {len(prs)} PRs from {repo}...")

    for pr in prs:
        pr_number = pr.get("number")
        if not pr_number:
            continue

        pr_code = f"{short}/PR-{pr_number}"
        ticket_code = extract_ticket_code_from_pr(pr)
        branch_name = pr.get("headRefName", "")

        created_at = parse_iso_timestamp(pr.get("createdAt"))
        merged_at = parse_iso_timestamp(pr.get("mergedAt"))

        existing = conn.execute(
            "SELECT pr_code FROM herd.pr_def WHERE pr_code = ?", [pr_code]
        ).fetchone()

        if existing:
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

    logger.info(f"Upserted {len(prs)} PRs from {repo}")


def insert_pr_commits(
    conn: duckdb.DuckDBPyConnection,
    repo: str,
    pr_number: int,
    pr_code: str,
) -> None:
    """Insert PR commits into agent_instance_pr_activity.

    Args:
        conn: DuckDB connection.
        repo: GitHub repo in 'owner/name' format.
        pr_number: GitHub PR number.
        pr_code: PR code (e.g., 'herd-core/PR-5').
    """
    try:
        commits = fetch_pr_commits(repo, pr_number)

        for commit in commits:
            commit_sha = commit.get("oid")
            if not commit_sha:
                continue

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
                    pr_commit_hash, pr_push_lines_added,
                    pr_push_lines_deleted,
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
        logger.warning(f"Failed to fetch commits for {repo} PR {pr_number}: {e}")


def ensure_stg_git_commit_table(conn: duckdb.DuckDBPyConnection) -> None:
    """Create the stg_git_commit staging table if it does not exist.

    This table stores raw git log data from all herd-ag repos for
    downstream analytics and agent attribution.

    Args:
        conn: DuckDB connection.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS herd.stg_git_commit (
            commit_hash TEXT PRIMARY KEY,
            repo_name TEXT NOT NULL,
            author_name TEXT,
            author_email TEXT,
            committed_at TIMESTAMP,
            subject TEXT,
            agent_code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)


def backfill_git_log(conn: duckdb.DuckDBPyConnection) -> int:
    """Backfill git commit history from all herd-ag repos.

    Iterates over local clones at ~/repos/, parses git log output,
    extracts agent code from the commit subject prefix convention
    (e.g., '[mason] fix: ...'), and inserts into stg_git_commit.

    Idempotent: skips commits that already exist by commit_hash.

    Args:
        conn: DuckDB connection.

    Returns:
        Number of new commits inserted.
    """
    ensure_stg_git_commit_table(conn)

    repos_dir = Path.home() / "repos"
    total_inserted = 0

    for repo_slug in HERD_REPOS:
        short = repo_short_name(repo_slug)
        repo_path = repos_dir / short

        if not (repo_path / ".git").exists():
            logger.warning(f"Repo {short} not found at {repo_path}, skipping git log")
            continue

        logger.info(f"Parsing git log for {short}...")

        cmd = [
            "git",
            "-C",
            str(repo_path),
            "log",
            "--format=%H|%an|%ae|%ai|%s",
            "--all",
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        inserted = 0
        for line in result.stdout.strip().splitlines():
            if not line:
                continue

            parts = line.split("|", 4)
            if len(parts) < 5:
                continue

            commit_hash, author_name, author_email, date_str, subject = parts

            # Check idempotency
            existing = conn.execute(
                "SELECT 1 FROM herd.stg_git_commit WHERE commit_hash = ?",
                [commit_hash],
            ).fetchone()

            if existing:
                continue

            # Parse commit date
            committed_at = None
            try:
                committed_at = datetime.fromisoformat(date_str.strip())
            except (ValueError, TypeError):
                pass

            # Extract agent code from commit prefix
            agent_code = extract_agent_code_from_commit_prefix(subject)

            conn.execute(
                """
                INSERT INTO herd.stg_git_commit (
                    commit_hash, repo_name, author_name, author_email,
                    committed_at, subject, agent_code, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    commit_hash,
                    short,
                    author_name,
                    author_email,
                    committed_at,
                    subject,
                    agent_code,
                ],
            )
            inserted += 1

        logger.info(f"Inserted {inserted} new commits from {short}")
        total_inserted += inserted

    return total_inserted


def ensure_backfill_agent_instance(conn: duckdb.DuckDBPyConnection) -> None:
    """Ensure backfill-000 agent instance exists.

    Args:
        conn: DuckDB connection.
    """
    existing = conn.execute(
        "SELECT agent_instance_code FROM herd.agent_instance "
        "WHERE agent_instance_code = ?",
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
        description="Backfill HerdDB from Linear, GitHub, and git log history"
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to DuckDB database file "
        "(defaults to HERD_STORE_DUCKDB_PATH or ~/herd/data/herddb.duckdb)",
    )
    parser.add_argument(
        "--skip-linear",
        action="store_true",
        help="Skip Linear ticket/project backfill",
    )
    parser.add_argument(
        "--skip-github",
        action="store_true",
        help="Skip GitHub PR backfill",
    )
    parser.add_argument(
        "--skip-git-log",
        action="store_true",
        help="Skip local git log backfill",
    )
    args = parser.parse_args()

    logger.info("Starting historical backfill...")

    # Get database connection
    db_path = args.db_path or os.getenv(
        "HERD_STORE_DUCKDB_PATH",
        os.path.expanduser("~/herd/data/herddb.duckdb"),
    )
    conn = get_connection(db_path)

    try:
        # Ensure backfill agent instance exists
        ensure_backfill_agent_instance(conn)

        # --- Linear backfill ---
        if not args.skip_linear:
            projects = fetch_all_linear_projects()
            tickets = fetch_all_linear_tickets()
            upsert_projects(conn, projects)
            upsert_tickets(conn, tickets)
        else:
            logger.info("Skipping Linear backfill (--skip-linear)")

        # --- GitHub PR backfill (all herd-ag repos) ---
        all_prs: dict[str, list[dict]] = {}
        if not args.skip_github:
            for repo in HERD_REPOS:
                try:
                    prs = fetch_all_github_prs(repo)
                    all_prs[repo] = prs
                    upsert_prs(conn, repo, prs)
                except subprocess.CalledProcessError as e:
                    logger.warning(f"Failed to fetch PRs from {repo}: {e.stderr}")

            # Insert commit activity for each PR
            logger.info("Fetching commit history for all PRs...")
            for repo, prs in all_prs.items():
                short = repo_short_name(repo)
                for pr in prs:
                    pr_number = pr.get("number")
                    if pr_number is None:
                        continue
                    pr_code = f"{short}/PR-{pr_number}"
                    insert_pr_commits(conn, repo, pr_number, pr_code)
        else:
            logger.info("Skipping GitHub backfill (--skip-github)")

        # --- Git log backfill (local clones) ---
        if not args.skip_git_log:
            git_commits = backfill_git_log(conn)
            logger.info(f"Git log backfill: {git_commits} new commits")
        else:
            logger.info("Skipping git log backfill (--skip-git-log)")

        logger.info("Backfill complete!")

        # Print summary
        project_count = conn.execute("SELECT COUNT(*) FROM herd.project_def").fetchone()
        ticket_count = conn.execute("SELECT COUNT(*) FROM herd.ticket_def").fetchone()
        pr_count = conn.execute("SELECT COUNT(*) FROM herd.pr_def").fetchone()
        commit_count = conn.execute(
            "SELECT COUNT(*) FROM herd.agent_instance_pr_activity "
            "WHERE agent_instance_code = ?",
            [BACKFILL_AGENT_INSTANCE_CODE],
        ).fetchone()

        # stg_git_commit may not exist if --skip-git-log
        try:
            git_count_row = conn.execute(
                "SELECT COUNT(*) FROM herd.stg_git_commit"
            ).fetchone()
            git_count = git_count_row[0] if git_count_row else 0
        except duckdb.CatalogException:
            git_count = 0

        logger.info("Database summary:")
        logger.info(f"  Projects: {project_count[0] if project_count else 0}")
        logger.info(f"  Tickets: {ticket_count[0] if ticket_count else 0}")
        logger.info(f"  PRs: {pr_count[0] if pr_count else 0}")
        logger.info(f"  PR Commits: {commit_count[0] if commit_count else 0}")
        logger.info(f"  Git Log Commits: {git_count}")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
