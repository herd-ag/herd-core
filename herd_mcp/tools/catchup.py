"""Catchup summary tool implementation."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from herd_mcp.db import connection
from herd_mcp.linear_client import search_issues

from ._helpers import get_git_log, get_handoffs, get_recent_hdrs, read_status_md

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry

# Backward-compatible aliases
_read_status_md = read_status_md
_get_git_log = get_git_log
_get_handoffs = get_handoffs
_get_recent_hdrs = get_recent_hdrs


async def _get_linear_tickets(
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
            records = registry.tickets.list_tickets(assignee=agent_name)
            tickets = [
                {"id": r.id, "title": r.title, "status": r.status} for r in records
            ]
        else:
            tickets = search_issues(f"assignee:{agent_name}")
        return tickets
    except Exception:
        # Linear API may not be available
        return []


def _get_slack_decisions_threads(
    agent_name: str, since: datetime
) -> list[dict[str, Any]]:
    """Get Slack #herd-decisions threads relevant to the agent.

    Args:
        agent_name: Agent name to search for.
        since: Start timestamp for filtering threads.

    Returns:
        List of thread summary dicts.
    """
    token = os.getenv("HERD_SLACK_TOKEN")
    if not token:
        return []

    try:
        import urllib.parse
        import urllib.request

        # First, get the channel ID for #herd-decisions
        channel_name = "herd-decisions"

        # Search for messages in #herd-decisions since cutoff
        params = urllib.parse.urlencode(
            {
                "query": f"in:#{channel_name} after:{int(since.timestamp())}",
                "count": 50,
            }
        )
        url = f"https://slack.com/api/search.messages?{params}"

        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}"},
        )

        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())

        if not result.get("ok", False):
            return []

        messages = result.get("messages", {}).get("matches", [])

        # Filter for threads mentioning this agent or relevant tickets
        agent_pattern = re.compile(rf"\b{re.escape(agent_name)}\b", re.IGNORECASE)
        ticket_pattern = re.compile(r"\bDBC-\d+\b")

        relevant_threads = []
        for msg in messages:
            text = msg.get("text", "")
            if agent_pattern.search(text) or ticket_pattern.search(text):
                relevant_threads.append(
                    {
                        "text": text[:200],  # First 200 chars
                        "user": msg.get("username", "unknown"),
                        "timestamp": msg.get("ts", ""),
                        "permalink": msg.get("permalink", ""),
                    }
                )

        return relevant_threads[:10]  # Limit to 10 most relevant
    except Exception:
        return []


def _get_decision_records(agent_name: str, since: datetime) -> list[dict[str, Any]]:
    """Get decision records from DuckDB since timestamp.

    Args:
        agent_name: Agent name.
        since: Start timestamp.

    Returns:
        List of decision record dicts.
    """
    with connection() as conn:
        # NOTE: Complex aggregate query — StoreAdapter CRUD doesn't cover this.
        # Kept as raw SQL. Future: ReportingAdapter or store.raw_query().
        decisions = conn.execute(
            """
            SELECT
                decision_id,
                decision_type,
                context,
                decision,
                rationale,
                decided_by,
                ticket_code,
                created_at
            FROM herd.decision_record
            WHERE created_at >= ?
              AND deleted_at IS NULL
              AND (decided_by = ? OR ticket_code IN (
                SELECT DISTINCT ticket_code
                FROM herd.agent_instance
                WHERE agent_code = ?
                  AND ticket_code IS NOT NULL
              ))
            ORDER BY created_at DESC
            LIMIT 20
            """,
            [str(since), agent_name, agent_name],
        ).fetchall()

        return [
            {
                "decision_id": row[0],
                "decision_type": row[1],
                "context": row[2],
                "decision": row[3],
                "rationale": row[4],
                "decided_by": row[5],
                "ticket_code": row[6],
                "created_at": str(row[7]),
            }
            for row in decisions
        ]


async def execute(
    agent_name: str | None, registry: AdapterRegistry | None = None
) -> dict:
    """Get a summary of what happened since agent was last active.

    Aggregates:
    - STATUS.md contents (parsed)
    - Recent git log (since last session)
    - Linear ticket states (active, blocked, pending review)
    - DuckDB activity (events, assignments, transitions)
    - Pending handoffs
    - Recent HDRs
    - #herd-decisions threads (relevant to agent)
    - Agent decision records from DuckDB

    Args:
        agent_name: Current agent identity.
        registry: Optional adapter registry for dependency injection.

    Returns:
        Dict with comprehensive catchup summary.
    """
    if not agent_name:
        return {
            "since": None,
            "summary": "No agent identity provided. Cannot retrieve catchup.",
        }

    # Find repository root
    repo_root = Path.cwd()
    while repo_root != repo_root.parent:
        if (repo_root / ".git").exists():
            break
        repo_root = repo_root.parent
    else:
        repo_root = Path.cwd()

    with connection() as conn:
        # NOTE: Complex aggregate query — StoreAdapter CRUD doesn't cover this.
        # Kept as raw SQL. Future: ReportingAdapter or store.raw_query().

        # Find the most recent ENDED instance for this agent
        previous_instance = conn.execute(
            """
            SELECT agent_instance_code, agent_instance_ended_at
            FROM herd.agent_instance
            WHERE agent_code = ?
              AND agent_instance_ended_at IS NOT NULL
            ORDER BY agent_instance_ended_at DESC
            LIMIT 1
            """,
            [agent_name],
        ).fetchone()

        if not previous_instance:
            # First session - provide minimal context
            status_md = _read_status_md(repo_root)
            linear_tickets = await _get_linear_tickets(agent_name, registry)

            return {
                "since": None,
                "summary": "No previous session found. You're starting fresh.",
                "agent": agent_name,
                "status_md": status_md,
                "linear_tickets": linear_tickets,
                "git_log": [],
                "ticket_updates": [],
                "handoffs": [],
                "hdrs": [],
                "slack_threads": [],
                "decision_records": [],
            }

        instance_code = previous_instance[0]
        ended_at = previous_instance[1]

        # Cap at 7 days of history
        seven_days_ago = datetime.now() - timedelta(days=7)
        cutoff = max(ended_at, seven_days_ago) if ended_at else seven_days_ago

        # Get ticket updates since the last session (existing logic)
        ticket_activity = conn.execute(
            """
            SELECT
                ta.ticket_code,
                ta.ticket_event_type,
                ta.ticket_status,
                ta.ticket_activity_comment,
                ta.created_at,
                ai.agent_code
            FROM herd.agent_instance_ticket_activity ta
            JOIN herd.agent_instance ai
              ON ta.agent_instance_code = ai.agent_instance_code
            WHERE ta.created_at >= ?
              AND ta.ticket_code IN (
                SELECT DISTINCT ticket_code
                FROM herd.agent_instance
                WHERE agent_code = ?
                  AND ticket_code IS NOT NULL
              )
            ORDER BY ta.created_at ASC
            LIMIT 100
            """,
            [str(cutoff), agent_name],
        ).fetchall()

        ticket_updates = []
        for row in ticket_activity:
            ticket_updates.append(
                {
                    "ticket": row[0],
                    "event_type": row[1],
                    "status": row[2],
                    "comment": row[3],
                    "timestamp": str(row[4]),
                    "by_agent": row[5],
                }
            )

    # Gather all data sources
    status_md = _read_status_md(repo_root)
    repo_adapter = registry.repo if registry else None
    git_log = _get_git_log(repo_root, cutoff, repo_adapter)
    linear_tickets = await _get_linear_tickets(agent_name, registry)
    handoffs = _get_handoffs(repo_root, cutoff)
    hdrs = _get_recent_hdrs(repo_root, cutoff)
    slack_threads = _get_slack_decisions_threads(agent_name, cutoff)
    decision_records = _get_decision_records(agent_name, cutoff)

    # Build comprehensive summary
    summary_parts = []
    summary_parts.append(f"Since {ended_at}:")

    if ticket_updates:
        ticket_count = len({u["ticket"] for u in ticket_updates})
        event_count = len(ticket_updates)
        summary_parts.append(
            f"- {event_count} ticket update{'s' if event_count != 1 else ''} "
            f"across {ticket_count} ticket{'s' if ticket_count != 1 else ''}"
        )

    if git_log:
        summary_parts.append(
            f"- {len(git_log)} commit{'s' if len(git_log) != 1 else ''}"
        )

    if linear_tickets:
        summary_parts.append(
            f"- {len(linear_tickets)} Linear ticket{'s' if len(linear_tickets) != 1 else ''} assigned"
        )

    if handoffs:
        summary_parts.append(
            f"- {len(handoffs)} new handoff{'s' if len(handoffs) != 1 else ''}"
        )

    if hdrs:
        summary_parts.append(f"- {len(hdrs)} new HDR{'s' if len(hdrs) != 1 else ''}")

    if slack_threads:
        summary_parts.append(
            f"- {len(slack_threads)} #herd-decisions thread{'s' if len(slack_threads) != 1 else ''}"
        )

    if decision_records:
        summary_parts.append(
            f"- {len(decision_records)} agent decision{'s' if len(decision_records) != 1 else ''}"
        )

    if len(summary_parts) == 1:
        summary_parts.append("- No significant activity")

    summary = "\n".join(summary_parts)

    return {
        "since": str(ended_at),
        "previous_instance": instance_code,
        "agent": agent_name,
        "summary": summary,
        "status_md": status_md,
        "git_log": git_log[:20],  # Last 20 commits
        "linear_tickets": linear_tickets,
        "ticket_updates": ticket_updates,
        "handoffs": handoffs,
        "hdrs": hdrs,
        "slack_threads": slack_threads,
        "decision_records": decision_records,
    }
