"""Catchup summary tool implementation."""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from herd_core.types import (
    AgentRecord,
    DecisionRecord,
    TicketEvent,
)
from herd_mcp.linear_client import search_issues

from ._helpers import get_git_log, read_status_md

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry

# Backward-compatible aliases
_read_status_md = read_status_md
_get_git_log = get_git_log


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
    token = os.getenv("HERD_NOTIFY_SLACK_TOKEN")
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


def _get_decision_records(
    store: Any,
    agent_name: str,
    since: datetime,
) -> list[dict[str, Any]]:
    """Get decision records from store since timestamp.

    Args:
        store: StoreAdapter instance.
        agent_name: Agent name.
        since: Start timestamp.

    Returns:
        List of decision record dicts.
    """
    # Get all decision records since the cutoff
    decisions = store.list(DecisionRecord, active=True)

    # Also find which tickets this agent has worked on
    agent_instances = store.list(AgentRecord, agent=agent_name)
    agent_ticket_ids = {inst.ticket_id for inst in agent_instances if inst.ticket_id}

    # Filter decisions relevant to this agent
    relevant = []
    for d in decisions:
        # Check if created after cutoff
        if d.created_at and d.created_at < since:
            continue

        # Check if this decision is by the agent or about a related ticket
        is_by_agent = d.decision_maker == agent_name
        is_related_ticket = d.scope and d.scope in agent_ticket_ids

        if is_by_agent or is_related_ticket:
            relevant.append(
                {
                    "decision_id": d.id,
                    "decision_type": (
                        d.title.split(":")[0] if ":" in d.title else "general"
                    ),
                    "context": "",
                    "decision": d.title,
                    "rationale": "",
                    "decided_by": d.decision_maker,
                    "ticket_code": d.scope,
                    "created_at": str(d.created_at) if d.created_at else None,
                }
            )

    # Sort by created_at desc and limit
    relevant.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return relevant[:20]


async def execute(
    agent_name: str | None, registry: AdapterRegistry | None = None
) -> dict:
    """Get a summary of what happened since agent was last active.

    Aggregates:
    - STATUS.md contents (parsed)
    - Recent git log (since last session)
    - Linear ticket states (active, blocked, pending review)
    - Store activity (events, assignments, transitions)
    - Semantic memory recall (session summaries, decision context)
    - #herd-decisions threads (relevant to agent)
    - Agent decision records from store
    - Graph context (structural neighbors)

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

    if not registry or not registry.store:
        return {"error": "StoreAdapter not configured"}

    store = registry.store

    # Find repository root
    repo_root = Path.cwd()
    while repo_root != repo_root.parent:
        if (repo_root / ".git").exists():
            break
        repo_root = repo_root.parent
    else:
        repo_root = Path.cwd()

    # Find the most recent ENDED instance for this agent
    all_instances = store.list(AgentRecord, agent=agent_name)

    # Filter to ended instances (state is COMPLETED, FAILED, or STOPPED) and sort by ended_at
    ended_instances = [inst for inst in all_instances if inst.ended_at is not None]
    ended_instances.sort(
        key=lambda x: x.ended_at or datetime.min,
        reverse=True,
    )

    if not ended_instances:
        # First session - provide minimal context
        status_md = _read_status_md(repo_root)
        linear_tickets = await _get_linear_tickets(agent_name, registry)

        # Enrich with semantic memory context (first session)
        semantic_context = []
        try:
            from herd_mcp.memory import recall as semantic_recall

            recent_memories = semantic_recall(
                f"recent work and decisions relevant to {agent_name}",
                limit=5,
                memory_type="session_summary",
            )
            decision_memories = semantic_recall(
                f"decisions and patterns relevant to {agent_name}",
                limit=5,
                memory_type="decision_context",
            )
            semantic_context = recent_memories + decision_memories
        except ImportError:
            pass  # LanceDB not available
        except Exception:
            logger.warning(
                "Failed to fetch semantic context for catchup", exc_info=True
            )

        # Graph enrichment: structural neighbors for this agent
        graph_context: list[dict] = []
        try:
            from herd_mcp.graph import is_available, query_graph

            if is_available():
                agent_graph = query_graph(
                    "MATCH (a:Agent {id: $aid})-[r]->(n) "
                    "RETURN type(r) AS rel, labels(n)[0] AS node_type, n.id AS id",
                    {"aid": agent_name},
                )
                graph_context = agent_graph[:20]
        except ImportError:
            pass
        except Exception:
            logger.warning("Failed to enrich catchup with graph context", exc_info=True)

        return {
            "since": None,
            "summary": "No previous session found. You're starting fresh.",
            "agent": agent_name,
            "status_md": status_md,
            "linear_tickets": linear_tickets,
            "git_log": [],
            "ticket_updates": [],
            "handoffs": [],  # Deprecated: context now via semantic recall
            "hdrs": [],
            "slack_threads": [],
            "decision_records": [],
            "semantic_context": semantic_context,
            "graph_context": graph_context,
        }

    previous_instance = ended_instances[0]
    instance_code = previous_instance.id
    ended_at = previous_instance.ended_at

    # Cap at 7 days of history
    seven_days_ago = datetime.now() - timedelta(days=7)
    cutoff = max(ended_at, seven_days_ago) if ended_at else seven_days_ago

    # Get ticket updates since the last session via store events
    # First, find which tickets this agent has worked on
    agent_ticket_ids = {inst.ticket_id for inst in all_instances if inst.ticket_id}

    ticket_updates = []
    for ticket_id in agent_ticket_ids:
        events = store.events(TicketEvent, entity_id=ticket_id, since=cutoff)
        for event in events:
            # Look up which agent this instance belongs to
            agent_record = (
                store.get(AgentRecord, event.instance_id) if event.instance_id else None
            )
            by_agent = agent_record.agent if agent_record else "unknown"

            ticket_updates.append(
                {
                    "ticket": ticket_id,
                    "event_type": event.event_type,
                    "status": event.new_status,
                    "comment": event.note,
                    "timestamp": str(event.created_at) if event.created_at else None,
                    "by_agent": by_agent,
                }
            )

    # Sort ticket updates by timestamp
    ticket_updates.sort(key=lambda x: x.get("timestamp") or "")

    # Gather all data sources
    status_md = _read_status_md(repo_root)
    repo_adapter = registry.repo if registry else None
    git_log = _get_git_log(repo_root, cutoff, repo_adapter)
    linear_tickets = await _get_linear_tickets(agent_name, registry)
    slack_threads = _get_slack_decisions_threads(agent_name, cutoff)
    decision_records = _get_decision_records(store, agent_name, cutoff)

    # Enrich with semantic memory context using agent's actual work context
    semantic_context = []
    try:
        from herd_mcp.memory import recall as semantic_recall

        # Build targeted query from agent's actual ticket context
        ticket_context = (
            ", ".join(list(agent_ticket_ids)[:5]) if agent_ticket_ids else ""
        )
        session_query = (
            f"work on {ticket_context}"
            if ticket_context
            else f"recent work by {agent_name}"
        )
        decision_query = (
            f"decisions about {ticket_context}"
            if ticket_context
            else f"decisions relevant to {agent_name}"
        )

        # Get recent session summaries (cross-agent awareness)
        recent_memories = semantic_recall(
            session_query,
            limit=5,
            memory_type="session_summary",
        )
        # Get decision context that might be relevant
        decision_memories = semantic_recall(
            decision_query,
            limit=5,
            memory_type="decision_context",
        )
        semantic_context = recent_memories + decision_memories
    except ImportError:
        pass  # LanceDB not available
    except Exception:
        logger.warning("Failed to fetch semantic context for catchup", exc_info=True)

    # Graph enrichment: structural neighbors of recently changed items
    graph_context = []
    try:
        from herd_mcp.graph import is_available, query_graph

        if is_available():
            # Find decisions and tickets connected to this agent
            agent_graph = query_graph(
                "MATCH (a:Agent {id: $aid})-[r]->(n) "
                "RETURN type(r) AS rel, labels(n)[0] AS node_type, n.id AS id",
                {"aid": agent_name},
            )
            graph_context = agent_graph[:20]
    except ImportError:
        pass
    except Exception:
        logger.warning("Failed to enrich catchup with graph context", exc_info=True)

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

    if slack_threads:
        summary_parts.append(
            f"- {len(slack_threads)} #herd-decisions thread{'s' if len(slack_threads) != 1 else ''}"
        )

    if decision_records:
        summary_parts.append(
            f"- {len(decision_records)} agent decision{'s' if len(decision_records) != 1 else ''}"
        )

    if semantic_context:
        summary_parts.append(f"- {len(semantic_context)} relevant semantic memories")

    if graph_context:
        summary_parts.append(
            f"- {len(graph_context)} graph relationship{'s' if len(graph_context) != 1 else ''}"
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
        "handoffs": [],  # Deprecated: context now via semantic recall
        "hdrs": [],  # Deprecated: HDR discovery via semantic recall instead
        "slack_threads": slack_threads,
        "decision_records": decision_records,
        "semantic_context": semantic_context,
        "graph_context": graph_context,
    }
