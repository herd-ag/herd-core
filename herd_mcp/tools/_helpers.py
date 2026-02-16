"""Shared helper functions for Herd MCP tools.

Extracted from catchup.py and spawn.py to provide reusable utilities
for file reading, craft section parsing, git log retrieval, and
context assembly.
"""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from herd_mcp.linear_client import search_issues

if TYPE_CHECKING:
    from herd_core.adapters.repo import RepoAdapter

    from herd_mcp.adapters import AdapterRegistry

logger = logging.getLogger(__name__)

# Map agent codes to their section headers in craft.md.
# Includes both current (HDR-0024) and legacy names for backwards compatibility.
CRAFT_SECTION_MAP: dict[str, str] = {
    # Current names (HDR-0024)
    "mason": "## Mason — Backend Craft Standards",
    "fresco": "## Fresco — Frontend Craft Standards",
    "scribe": "## Scribe — Documentation Standards",
    "wardenstein": "## Wardenstein — QA Craft Standards",
    "steve": "## Steve — Coordination Craft Standards",
    "leonardo": "## Leonardo — Coordination Craft Standards",
    "vigil": "## Vigil — Automated QA Standards",
    "rook": "## Rook — Mechanical Execution Standards",
    # Legacy names (backwards compatibility during transition)
    "grunt": "## Mason — Backend Craft Standards",
    "pikasso": "## Fresco — Frontend Craft Standards",
    "mini-mao": "## Steve — Coordination Craft Standards",
    "shakesquill": "## Scribe — Documentation Standards",
}


def find_repo_root() -> Path:
    """Find the repository root by looking for .git directory.

    Walks up from the current working directory until a .git directory
    or .git file (worktree) is found.

    Returns:
        Path to repository root.

    Raises:
        RuntimeError: If repository root cannot be found.
    """
    current = Path.cwd()
    while current != current.parent:
        if (current / ".git").exists() or (current / ".git").is_file():
            return current
        current = current.parent
    raise RuntimeError("Could not find repository root (.git directory)")


def get_herd_content_path(subpath: str) -> Path | None:
    """Resolve a .herd/ content path with fallback chain.

    Resolution order:
    1. Project root .herd/ (project-specific overrides)
    2. Package root .herd/ (canonical defaults from herd-core install)

    Args:
        subpath: Path relative to .herd/, e.g. "roles/steve.md" or "craft.md"

    Returns:
        Resolved Path if found, None if not found anywhere.
    """
    # 1. Try project root
    try:
        repo_root = find_repo_root()
        project_path = repo_root / ".herd" / subpath
        if project_path.exists():
            return project_path
    except RuntimeError:
        pass

    # 2. Try package root (works for editable and git installs)
    package_root = (
        Path(__file__).resolve().parent.parent.parent
    )  # herd_mcp/tools/_helpers.py -> repo root
    package_path = package_root / ".herd" / subpath
    if package_path.exists():
        return package_path

    return None


def read_file_safe(path: Path) -> str | None:
    """Read a file safely, returning None on any error.

    Args:
        path: Path to file.

    Returns:
        File contents or None if read fails.
    """
    try:
        return path.read_text()
    except Exception as e:
        logger.warning(f"Failed to read {path}: {e}")
        return None


def extract_craft_section(craft_content: str, agent_code: str) -> str:
    """Extract the agent-specific section from craft.md.

    Supports both current (HDR-0024) and legacy agent names.

    Args:
        craft_content: Full contents of craft.md.
        agent_code: Agent code (e.g., mason, grunt, fresco).

    Returns:
        Agent's section from craft.md or empty string if not found.
    """
    section_header = CRAFT_SECTION_MAP.get(agent_code)
    if not section_header or section_header not in craft_content:
        logger.warning(f"Could not find craft section for {agent_code}")
        return ""

    # Extract from this section header to the next "##" marker
    start_idx = craft_content.index(section_header)
    rest = craft_content[start_idx:]

    # Find next section header (## at start of line with em-dash separator)
    lines = rest.split("\n")
    section_lines = [lines[0]]  # Include the header
    for line in lines[1:]:
        if line.startswith("## ") and "\u2014" in line:
            break
        section_lines.append(line)

    return "\n".join(section_lines)


def read_status_md(repo_root: Path) -> dict[str, Any]:
    """Read and parse STATUS.md file.

    Args:
        repo_root: Repository root path.

    Returns:
        Dict with parsed STATUS.md contents or empty dict if not found.
    """
    status_file = repo_root / ".herd" / "STATUS.md"
    if not status_file.exists():
        return {"exists": False, "content": None}

    try:
        content = status_file.read_text()
        return {"exists": True, "content": content}
    except Exception as e:
        return {"exists": False, "error": str(e)}


def get_git_log(
    repo_root: Path, since: datetime, repo_adapter: RepoAdapter | None = None
) -> list[dict[str, str]]:
    """Get git log since a given timestamp.

    Args:
        repo_root: Repository root path.
        since: Start timestamp for git log.
        repo_adapter: Optional RepoAdapter for git operations.

    Returns:
        List of commit dicts with sha, author, date, and message.
    """
    try:
        # Adapter path
        if repo_adapter:
            commit_infos = repo_adapter.get_log(since=since, limit=50)
            return [
                {
                    "sha": commit.sha,
                    "author": commit.author,
                    "date": commit.timestamp.isoformat(),
                    "message": commit.message,
                }
                for commit in commit_infos
            ]
        else:
            # Existing inline subprocess fallback
            # Format: %H (hash), %an (author name), %ai (ISO date), %s (subject)
            result = subprocess.run(
                [
                    "git",
                    "log",
                    f"--since={since.isoformat()}",
                    "--format=%H|||%an|||%ai|||%s",
                ],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=True,
            )

            commits = []
            for line in result.stdout.strip().split("\n"):
                if not line:
                    continue
                parts = line.split("|||")
                if len(parts) == 4:
                    commits.append(
                        {
                            "sha": parts[0],
                            "author": parts[1],
                            "date": parts[2],
                            "message": parts[3],
                        }
                    )

            return commits
    except Exception:
        return []


async def get_linear_tickets(
    agent_name: str, registry: AdapterRegistry | None = None
) -> list[dict[str, Any]]:
    """Get Linear tickets for the agent.

    Args:
        agent_name: Agent name to search for.
        registry: Optional adapter registry.

    Returns:
        List of Linear ticket dicts.
    """
    try:
        # Search for tickets assigned to this agent or mentioning them
        if registry and registry.tickets:
            ticket_records = registry.tickets.list_tickets(assignee=agent_name)
            return [
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status,
                }
                for t in ticket_records
            ]
        else:
            tickets = search_issues(f"assignee:{agent_name}")
            return tickets
    except Exception:
        # Linear API may not be available
        return []
