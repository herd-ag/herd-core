"""Status query tool implementation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from herd_core.queries import OperationalQueries
from herd_core.types import (
    AgentRecord,
    AgentState,
    SprintRecord,
    TicketEvent,
    TicketRecord,
)

if TYPE_CHECKING:
    from herd_core.adapters.store import StoreAdapter
    from herd_mcp.adapters import AdapterRegistry

logger = logging.getLogger(__name__)


def _get_active_agents(store: StoreAdapter) -> list[dict]:
    """Get all active agents with their current assignments.

    Args:
        store: StoreAdapter instance.

    Returns:
        List of agent dicts with assignment info.
    """
    agents_list = []
    # Get all active agent records
    records = store.list(AgentRecord, active=True)

    # Group by agent name to show unique agents
    seen_agents: dict[str, dict] = {}
    for record in records:
        agent_name = record.agent
        if agent_name not in seen_agents:
            seen_agents[agent_name] = {
                "agent_code": agent_name,
                "agent_role": agent_name,
                "agent_status": record.state.value if record.state else "unknown",
                "default_model": record.model,
                "current_assignment": None,
            }

        # If this is a running instance with a ticket, set as current assignment
        if (
            record.state in (AgentState.RUNNING, AgentState.SPAWNING)
            and record.ticket_id
        ):
            seen_agents[agent_name]["current_assignment"] = {
                "ticket_code": record.ticket_id,
                "started_at": str(record.started_at) if record.started_at else None,
            }

    agents_list = list(seen_agents.values())
    return agents_list


def _get_blocked_tickets(
    store: StoreAdapter, queries: OperationalQueries
) -> list[dict]:
    """Get all currently blocked tickets.

    Args:
        store: StoreAdapter instance.
        queries: OperationalQueries instance.

    Returns:
        List of blocked ticket dicts.
    """
    blocked = queries.blocked_tickets()
    blockers = []
    for ticket in blocked:
        # Get the most recent blocked event for this ticket
        events = store.events(TicketEvent, entity_id=ticket.id)
        blocked_events = [e for e in events if e.event_type == "blocked"]

        blocker_ticket = None
        blocker_desc = None
        blocked_since = None

        if blocked_events:
            latest = blocked_events[-1]  # events ordered ascending
            blocker_ticket = latest.blocked_by[0] if latest.blocked_by else None
            blocker_desc = latest.note
            blocked_since = str(latest.created_at) if latest.created_at else None

        blockers.append(
            {
                "ticket_code": ticket.id,
                "blocker_ticket_code": blocker_ticket,
                "blocker_description": blocker_desc,
                "blocked_since": blocked_since,
            }
        )

    return blockers


def _get_current_sprint(store: StoreAdapter) -> dict | None:
    """Get current active sprint.

    Args:
        store: StoreAdapter instance.

    Returns:
        Sprint dict or None if no active sprint.
    """
    sprints = store.list(SprintRecord, active=True, status="active")
    if not sprints:
        # Try without status filter
        sprints = store.list(SprintRecord, active=True)

    if not sprints:
        return None

    # Take the most recent sprint
    sprint = sprints[0]

    sprint_dict: dict[str, Any] = {
        "sprint_code": sprint.id,
        "sprint_title": sprint.name,
        "sprint_goal": sprint.goal,
        "started_at": str(sprint.started_at) if sprint.started_at else None,
        "planned_end_at": str(sprint.ended_at) if sprint.ended_at else None,
        "tickets": [],
    }

    # Get tickets - we can list all active tickets as sprint assignment
    # isn't tracked on TicketRecord in the new types
    tickets = store.list(TicketRecord, active=True)
    for ticket in tickets:
        sprint_dict["tickets"].append(
            {
                "ticket_code": ticket.id,
                "ticket_title": ticket.title,
                "status": ticket.status,
            }
        )

    return sprint_dict


def _get_agent_status(store: StoreAdapter, agent_name: str) -> dict:
    """Get status for a specific agent.

    Args:
        store: StoreAdapter instance.
        agent_name: Agent code to query.

    Returns:
        Agent status dict.
    """
    # Get all instances for this agent (active and ended)
    all_instances = store.list(AgentRecord, agent=agent_name)

    if not all_instances:
        return {"error": f"Agent {agent_name} not found"}

    # Use the first instance for agent-level info
    first = all_instances[0]

    instance_list = []
    for inst in all_instances[:10]:  # Limit to 10 most recent
        instance_list.append(
            {
                "instance_code": inst.id,
                "ticket_code": inst.ticket_id,
                "started_at": str(inst.started_at) if inst.started_at else None,
                "ended_at": str(inst.ended_at) if inst.ended_at else None,
                "outcome": inst.state.value if inst.state else None,
            }
        )

    return {
        "agent_code": agent_name,
        "agent_role": agent_name,
        "agent_status": first.state.value if first.state else "unknown",
        "default_model": first.model,
        "recent_instances": instance_list,
    }


def _get_ticket_status(store: StoreAdapter, ticket_id: str) -> dict:
    """Get full lifecycle for a specific ticket.

    Args:
        store: StoreAdapter instance.
        ticket_id: Ticket code to query.

    Returns:
        Ticket status dict with full activity history.
    """
    ticket = store.get(TicketRecord, ticket_id)

    if not ticket:
        return {"error": f"Ticket {ticket_id} not found"}

    # Get activity history from ticket events
    events = store.events(TicketEvent, entity_id=ticket_id)

    activity_list = []
    for event in reversed(events):  # Most recent first
        activity_list.append(
            {
                "agent_instance": event.instance_id,
                "event_type": event.event_type,
                "status": event.new_status,
                "comment": event.note,
                "timestamp": str(event.created_at) if event.created_at else None,
            }
        )

    return {
        "ticket_code": ticket.id,
        "ticket_title": ticket.title,
        "ticket_description": ticket.description,
        "current_status": ticket.status,
        "sprint_code": None,  # Sprint code not on TicketRecord in new types
        "activity_history": activity_list,
    }


def _get_available_agents(store: StoreAdapter) -> list[dict]:
    """Get agents with no active instance.

    Args:
        store: StoreAdapter instance.

    Returns:
        List of available agent dicts.
    """
    # Get all active agent instances
    active_instances = store.list(AgentRecord, active=True)

    # Collect agent names that have running instances
    busy_agents = set()
    all_agent_names = set()
    for inst in active_instances:
        all_agent_names.add(inst.agent)
        if inst.state in (AgentState.RUNNING, AgentState.SPAWNING):
            busy_agents.add(inst.agent)

    # Also get all agents (including ended) to know the full roster
    all_instances = store.list(AgentRecord)
    for inst in all_instances:
        all_agent_names.add(inst.agent)

    available = []
    for agent_name in all_agent_names:
        if agent_name not in busy_agents:
            available.append(
                {
                    "agent_code": agent_name,
                    "agent_role": agent_name,
                    "agent_status": "available",
                }
            )

    return available


async def execute(
    scope: str, agent_name: str | None, registry: AdapterRegistry | None = None
) -> dict:
    """Get current status of Herd agents, sprint, and blockers.

    Args:
        scope: Status scope - "all", "sprint", "agent:<name>", "ticket:<id>",
               "available", or "blocked".
        agent_name: Current agent identity.
        registry: Optional adapter registry for dependency injection.

    Returns:
        Dict with agents status, sprint info, and blocker list based on scope.
    """
    if not registry or not registry.store:
        return {"error": "StoreAdapter not configured"}

    store = registry.store
    queries = OperationalQueries(store)

    if scope == "all":
        # Graph enrichment: topology summary
        topology: dict = {}
        try:
            from herd_mcp.graph import is_available, query_graph

            if is_available():
                # Count nodes by type
                node_counts = query_graph(
                    "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt"
                )
                # Orphan decisions (not linked to any ticket via Implements)
                orphan_decisions = query_graph(
                    "MATCH (d:Decision) WHERE NOT EXISTS { "
                    "MATCH (t:Ticket)-[:Implements]->(d) } "
                    "RETURN d.id AS id, d.title AS title"
                )
                topology = {
                    "node_counts": {r["label"]: r["cnt"] for r in node_counts},
                    "orphan_decisions": orphan_decisions[:10],
                }
        except ImportError:
            pass
        except Exception:
            logger.warning("Failed to enrich status with graph topology", exc_info=True)

        return {
            "scope": scope,
            "agents": _get_active_agents(store),
            "sprint": _get_current_sprint(store),
            "blockers": _get_blocked_tickets(store, queries),
            "graph_topology": topology,
            "requesting_agent": agent_name,
        }
    elif scope == "sprint":
        return {
            "scope": scope,
            "sprint": _get_current_sprint(store),
            "requesting_agent": agent_name,
        }
    elif scope.startswith("agent:"):
        target_agent = scope.split(":", 1)[1]
        return {
            "scope": scope,
            "agent_status": _get_agent_status(store, target_agent),
            "requesting_agent": agent_name,
        }
    elif scope.startswith("ticket:"):
        ticket_id = scope.split(":", 1)[1]
        return {
            "scope": scope,
            "ticket_status": _get_ticket_status(store, ticket_id),
            "requesting_agent": agent_name,
        }
    elif scope == "available":
        return {
            "scope": scope,
            "available_agents": _get_available_agents(store),
            "requesting_agent": agent_name,
        }
    elif scope == "blocked":
        return {
            "scope": scope,
            "blockers": _get_blocked_tickets(store, queries),
            "requesting_agent": agent_name,
        }
    else:
        # Default to "all" for unknown scopes — graph topology included
        default_topology: dict = {}
        try:
            from herd_mcp.graph import is_available, query_graph

            if is_available():
                node_counts = query_graph(
                    "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS cnt"
                )
                orphan_decisions = query_graph(
                    "MATCH (d:Decision) WHERE NOT EXISTS { "
                    "MATCH (t:Ticket)-[:Implements]->(d) } "
                    "RETURN d.id AS id, d.title AS title"
                )
                default_topology = {
                    "node_counts": {r["label"]: r["cnt"] for r in node_counts},
                    "orphan_decisions": orphan_decisions[:10],
                }
        except ImportError:
            pass
        except Exception:
            logger.warning("Failed to enrich status with graph topology", exc_info=True)

        return {
            "scope": "all",
            "agents": _get_active_agents(store),
            "sprint": _get_current_sprint(store),
            "blockers": _get_blocked_tickets(store, queries),
            "graph_topology": default_topology,
            "requesting_agent": agent_name,
        }
