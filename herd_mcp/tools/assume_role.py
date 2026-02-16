"""Assume role prompt implementation.

Assembles full agent identity and situational context for zero-ceremony
identity loading. When invoked via `/assume steve` in Claude Code, it
composes everything the agent needs to assume its role.

Per HDR-0036 Loop 4: HDR context is loaded via semantic recall (LanceDB)
and structural graph (KuzuDB) instead of file globbing, so agents receive
*relevant* decisions with summaries rather than just recent filenames.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from ._helpers import (
    extract_craft_section,
    find_repo_root,
    get_herd_content_path,
    get_linear_tickets,
    read_file_safe,
    read_status_md,
)

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry

logger = logging.getLogger(__name__)

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


def _recall_relevant_hdrs(agent_name: str, role_content: str) -> list[dict]:
    """Recall HDRs relevant to this agent's role via LanceDB semantic search.

    Queries semantic memory for decision_context entries that match the
    agent's role description. Falls back gracefully if LanceDB or its
    dependencies are unavailable.

    Args:
        agent_name: Lowercase agent code (e.g., "mason", "steve").
        role_content: The agent's role file content, used to build
            a semantically rich query.

    Returns:
        List of dicts with keys: hdr_number, title, summary. Empty list
        on any failure.
    """
    try:
        from herd_mcp.memory import recall as semantic_recall
    except ImportError:
        logger.debug(
            "LanceDB not available for HDR recall in assume_role "
            "(agent=%s); falling back to empty list",
            agent_name,
        )
        return []

    # Build a query from the agent name and a snippet of their role
    role_snippet = role_content[:200] if role_content else ""
    query = f"decisions and standards relevant to {agent_name} role: {role_snippet}"

    try:
        results = semantic_recall(
            query,
            limit=7,
            memory_type="decision_context",
        )
    except Exception as exc:
        logger.warning(
            "Semantic recall failed during assume_role for agent %s: %s",
            agent_name,
            exc,
        )
        return []

    hdrs: list[dict] = []
    for result in results:
        metadata_raw = result.get("metadata", "{}")
        try:
            metadata = json.loads(metadata_raw) if metadata_raw else {}
        except (json.JSONDecodeError, TypeError):
            metadata = {}

        hdr_number = metadata.get("hdr_number", "")
        summary = result.get("summary") or result.get("content", "")
        # Truncate overly long summaries for prompt brevity
        if len(summary) > 300:
            summary = summary[:297] + "..."

        hdrs.append(
            {
                "hdr_number": hdr_number,
                "summary": summary,
            }
        )

    return hdrs


def _format_semantic_hdrs(hdrs: list[dict]) -> str:
    """Format semantically recalled HDRs for the identity prompt.

    Args:
        hdrs: List of dicts from _recall_relevant_hdrs, each with
            hdr_number and summary keys.

    Returns:
        Formatted string with one HDR per line, or "(none)" if empty.
    """
    if not hdrs:
        return "(none — semantic memory unavailable or empty)"

    lines = []
    for hdr in hdrs:
        number = hdr.get("hdr_number", "")
        summary = hdr.get("summary", "(no summary)")
        if number:
            lines.append(f"- HDR-{number}: {summary}")
        else:
            lines.append(f"- {summary}")
    return "\n".join(lines)


def _query_agent_decision_graph(agent_name: str) -> list[dict]:
    """Query KuzuDB for decisions connected to the agent.

    Traverses the graph for decisions the agent has made (Decides edge)
    and tickets the agent is assigned to that implement decisions
    (AssignedTo + Implements edges).

    Args:
        agent_name: Lowercase agent code (e.g., "mason", "steve").

    Returns:
        List of dicts with keys: id, title, relationship. Empty list
        on any failure or if graph is unavailable.
    """
    try:
        from herd_mcp.graph import is_available, query_graph
    except ImportError:
        logger.debug(
            "KuzuDB not available for graph context in assume_role "
            "(agent=%s); skipping graph enrichment",
            agent_name,
        )
        return []

    if not is_available():
        return []

    decisions: list[dict] = []
    seen_ids: set[str] = set()

    # 1. Direct decisions by this agent
    try:
        direct = query_graph(
            "MATCH (a:Agent {id: $aid})-[:Decides]->(d:Decision) "
            "RETURN d.id AS id, d.title AS title",
            {"aid": agent_name},
        )
        for row in direct:
            did = row.get("id", "")
            if did and did not in seen_ids:
                seen_ids.add(did)
                decisions.append(
                    {
                        "id": did,
                        "title": row.get("title", ""),
                        "relationship": "authored",
                    }
                )
    except RuntimeError as exc:
        logger.warning(
            "Graph query for direct decisions failed (agent=%s): %s",
            agent_name,
            exc,
        )

    # 2. Decisions implemented by tickets assigned to this agent
    try:
        via_tickets = query_graph(
            "MATCH (t:Ticket)-[:AssignedTo]->(a:Agent {id: $aid}), "
            "(t)-[:Implements]->(d:Decision) "
            "RETURN d.id AS id, d.title AS title, t.id AS ticket_id",
            {"aid": agent_name},
        )
        for row in via_tickets:
            did = row.get("id", "")
            if did and did not in seen_ids:
                seen_ids.add(did)
                ticket_id = row.get("ticket_id", "")
                decisions.append(
                    {
                        "id": did,
                        "title": row.get("title", ""),
                        "relationship": f"implementing via {ticket_id}",
                    }
                )
    except RuntimeError as exc:
        logger.warning(
            "Graph query for ticket-linked decisions failed (agent=%s): %s",
            agent_name,
            exc,
        )

    return decisions


def _format_graph_decisions(decisions: list[dict]) -> str:
    """Format graph-sourced decisions for the identity prompt.

    Args:
        decisions: List of dicts from _query_agent_decision_graph, each
            with id, title, and relationship keys.

    Returns:
        Formatted string with one decision per line, or "(none)" if empty.
    """
    if not decisions:
        return "(none — graph store unavailable or no connected decisions)"

    lines = []
    for decision in decisions:
        did = decision.get("id", "?")
        title = decision.get("title", "")
        relationship = decision.get("relationship", "")
        if title:
            lines.append(f"- {did}: {title} ({relationship})")
        else:
            lines.append(f"- {did} ({relationship})")
    return "\n".join(lines)


async def execute(agent_name: str, registry: AdapterRegistry | None = None) -> str:
    """Assemble full agent identity and situational context.

    Composes a prompt from role file, craft standards, project guidelines,
    current state, git log, Linear tickets, handoffs, and relevant HDRs
    (via semantic recall and graph traversal).

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

    # Recall relevant HDRs via LanceDB semantic search (HDR-0036 Loop 4)
    semantic_hdrs = _recall_relevant_hdrs(agent_lower, role_content)
    semantic_hdrs_formatted = _format_semantic_hdrs(semantic_hdrs)

    # Query decision graph for structurally connected decisions (HDR-0035)
    graph_decisions = _query_agent_decision_graph(agent_lower)
    graph_decisions_formatted = _format_graph_decisions(graph_decisions)

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

### Relevant Decisions (HDRs — semantic recall)
{semantic_hdrs_formatted}

### Connected Decisions (graph)
{graph_decisions_formatted}

## Session Protocol
You have full context. Post session start to #herd-feed via herd_log. Await Architect direction."""

    return prompt
