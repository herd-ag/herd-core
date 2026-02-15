"""Assume role prompt implementation.

Assembles full agent identity and situational context for zero-ceremony
identity loading. When invoked via `/assume steve` in Claude Code, it
composes everything the agent needs to assume its role.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from ._helpers import (
    extract_craft_section,
    find_repo_root,
    get_handoffs,
    get_herd_content_path,
    get_linear_tickets,
    get_recent_hdrs,
    read_file_safe,
    read_status_md,
)

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry

# Known agent names for validation (current + legacy)
KNOWN_AGENTS: set[str] = {
    "steve",
    "leonardo",
    "mason",
    "fresco",
    "scribe",
    "wardenstein",
    "vigil",
    "rook",
    "gauss",
    # Legacy names
    "grunt",
    "pikasso",
    "mini-mao",
    "shakesquill",
}

# Map legacy names to current display names
DISPLAY_NAMES: dict[str, str] = {
    "steve": "Steve",
    "leonardo": "Leonardo",
    "mason": "Mason",
    "fresco": "Fresco",
    "scribe": "Scribe",
    "wardenstein": "Wardenstein",
    "vigil": "Vigil",
    "rook": "Rook",
    "gauss": "Gauss",
    # Legacy names map to current display names
    "grunt": "Mason",
    "pikasso": "Fresco",
    "mini-mao": "Steve",
    "shakesquill": "Scribe",
}


def _get_recent_git_log(repo_root: Path, limit: int = 10) -> str:
    """Get formatted git log of recent commits.

    Args:
        repo_root: Repository root path.
        limit: Maximum number of commits to retrieve.

    Returns:
        Formatted git log string, or "(no git history available)" on failure.
    """
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                f"-{limit}",
                "--format=%h %ai %s",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=True,
        )
        output = result.stdout.strip()
        return output if output else "(no recent commits)"
    except Exception:
        return "(no git history available)"


def _format_tickets(tickets: list[dict]) -> str:
    """Format Linear tickets for display.

    Args:
        tickets: List of ticket dicts from Linear.

    Returns:
        Formatted ticket list string.
    """
    if not tickets:
        return "(none)"

    lines = []
    for ticket in tickets:
        identifier = ticket.get("identifier", ticket.get("ticket_code", "?"))
        title = ticket.get("title", ticket.get("ticket_title", "Untitled"))
        status = ticket.get("status", ticket.get("ticket_current_status", "unknown"))
        lines.append(f"- {identifier}: {title} [{status}]")
    return "\n".join(lines)


def _format_handoffs(handoffs: list[dict]) -> str:
    """Format handoff files for display.

    Args:
        handoffs: List of handoff dicts.

    Returns:
        Formatted handoff list string.
    """
    if not handoffs:
        return "(none)"

    lines = []
    for handoff in handoffs:
        lines.append(f"- {handoff['filename']} (modified: {handoff['modified']})")
    return "\n".join(lines)


def _format_hdrs(hdrs: list[dict]) -> str:
    """Format HDR records for display.

    Args:
        hdrs: List of HDR dicts.

    Returns:
        Formatted HDR list string.
    """
    if not hdrs:
        return "(none)"

    lines = []
    for hdr in hdrs:
        lines.append(f"- {hdr['filename']}: {hdr['title']}")
    return "\n".join(lines)


async def execute(agent_name: str, registry: AdapterRegistry | None = None) -> str:
    """Assemble full agent identity and situational context.

    Composes a prompt from role file, craft standards, project guidelines,
    current state, git log, Linear tickets, handoffs, and recent HDRs.

    Args:
        agent_name: Agent code (e.g., steve, mason, fresco).
        registry: Optional adapter registry for dependency injection.

    Returns:
        Formatted prompt string with full agent context.
    """
    agent_lower = agent_name.lower().strip()

    if agent_lower not in KNOWN_AGENTS:
        return (
            f"Unknown agent: '{agent_name}'. "
            f"Known agents: {', '.join(sorted(KNOWN_AGENTS - {'grunt', 'pikasso', 'mini-mao', 'shakesquill'}))}"
        )

    display_name = DISPLAY_NAMES.get(agent_lower, agent_lower.title())

    # Find repo root
    try:
        repo_root = find_repo_root()
    except RuntimeError:
        repo_root = Path.cwd()

    # Read role file
    role_path = get_herd_content_path(f"roles/{agent_lower}.md")
    if role_path:
        role_content = read_file_safe(role_path)
    else:
        role_content = None
    if role_content is None:
        role_content = f"(Role file not found for agent: {agent_lower})"

    # Read craft section
    craft_path = get_herd_content_path("craft.md")
    if craft_path:
        craft_full = read_file_safe(craft_path)
    else:
        craft_full = None
    craft_section = ""
    if craft_full:
        craft_section = extract_craft_section(craft_full, agent_lower)
    if not craft_section:
        craft_section = "(Craft section not found for this agent)"

    # Read project guidelines
    claude_md_path = repo_root / "CLAUDE.md"
    claude_md = read_file_safe(claude_md_path)
    if claude_md is None:
        claude_md = "(CLAUDE.md not found)"

    # Read current state
    status_data = read_status_md(repo_root)
    status_content = status_data.get("content") or "(STATUS.md not found)"

    # Get git log (last 10 commits)
    git_log = _get_recent_git_log(repo_root, limit=10)

    # Get Linear tickets
    tickets = await get_linear_tickets(agent_lower, registry)
    tickets_formatted = _format_tickets(tickets)

    # Get handoffs (last 7 days)
    since = datetime.now() - timedelta(days=7)
    handoffs = get_handoffs(repo_root, since)
    handoffs_formatted = _format_handoffs(handoffs)

    # Get recent HDRs (last 7 days)
    hdrs = get_recent_hdrs(repo_root, since)
    hdrs_formatted = _format_hdrs(hdrs)

    # Assemble the prompt
    prompt = f"""You are {display_name}.

## Role
{role_content}

## Craft Standards
{craft_section}

## Project Guidelines
{claude_md}

## Current State
{status_content}

## Recent Activity
### Git (last 10 commits)
{git_log}

### Assigned Tickets
{tickets_formatted}

### Pending Handoffs
{handoffs_formatted}

### Recent Decisions (HDRs)
{hdrs_formatted}

## Session Protocol
You have full context. Post session start to #herd-feed via herd_log. Await Architect direction."""

    return prompt
