"""Ticket assignment tool implementation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from herd_core.types import (
    AgentRecord,
    AgentState,
    TicketEvent,
    TicketRecord,
)

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry

logger = logging.getLogger(__name__)


async def execute(
    ticket_id: str,
    agent_name: str | None,
    priority: str,
    registry: AdapterRegistry | None = None,
) -> dict:
    """Assign a ticket to an agent.

    Args:
        ticket_id: Linear ticket ID.
        agent_name: Agent to assign to.
        priority: Assignment priority.
        registry: Optional adapter registry for dependency injection.

    Returns:
        Dict with assignment confirmation, agent, and ticket details.
    """
    if not agent_name:
        return {
            "assigned": False,
            "error": "agent_name is required",
            "ticket": ticket_id,
            "priority": priority,
        }

    if not registry or not registry.store:
        return {"error": "StoreAdapter not configured"}

    store = registry.store

    # Look up ticket
    ticket_record = store.get(TicketRecord, ticket_id)

    # Auto-register from Linear if not found and looks like Linear ID
    if not ticket_record:
        from herd_mcp import linear_client

        if linear_client.is_linear_identifier(ticket_id):
            logger.info(
                f"Ticket {ticket_id} not found in store, attempting Linear fetch"
            )

            tr: TicketRecord | None = None
            if registry.tickets:
                try:
                    tr = registry.tickets.get(ticket_id)
                except Exception:
                    pass

            if tr is None:
                d = linear_client.get_issue(ticket_id)
                if d:
                    tr = TicketRecord(
                        id=d.get("identifier", d.get("id", "")),
                        title=d.get("title", ""),
                        description=d.get("description"),
                        status=(d.get("state") or {}).get("name", ""),
                        project=(d.get("project") or {}).get("name"),
                    )

            if tr:
                async with registry.write_lock:
                    store.save(tr)
                logger.info(f"Auto-registered ticket {ticket_id} from Linear")
                ticket_record = store.get(TicketRecord, ticket_id)

    if not ticket_record:
        return {
            "assigned": False,
            "error": f"Ticket {ticket_id} not found in store or Linear",
            "agent": agent_name,
            "ticket": ticket_id,
            "priority": priority,
        }

    # Look up agent -- AgentRecord represents running instances.
    # Find an active (running) instance for this agent.
    active_agents = store.list(AgentRecord, agent=agent_name, active=True)
    # Find the running instance (if any)
    running_instance = None
    for a in active_agents:
        if a.state in (AgentState.RUNNING, AgentState.SPAWNING):
            running_instance = a
            break

    agent_instance_code = running_instance.id if running_instance else None

    # Record assignment as a ticket event
    async with registry.write_lock:
        store.append(
            TicketEvent(
                entity_id=ticket_id,
                event_type="assigned",
                instance_id=agent_instance_code or "",
                previous_status=ticket_record.status,
                new_status="assigned",
                note=f"Assigned with priority: {priority}",
            )
        )

        # Update ticket status to assigned
        ticket_record.status = "assigned"
        store.save(ticket_record)

    # Auto-shadow to KuzuDB graph
    try:
        from herd_mcp.graph import create_edge, merge_node

        merge_node(
            "Ticket",
            {
                "id": ticket_id,
                "title": ticket_record.title,
                "status": "assigned",
                "priority": priority,
            },
        )
        merge_node(
            "Agent",
            {
                "id": agent_name,
                "code": agent_name,
                "role": agent_name,
                "status": "active",
                "team": "",
                "host": "",
            },
        )
        create_edge("AssignedTo", "Ticket", ticket_id, "Agent", agent_name)
    except ImportError:
        pass  # KuzuDB not installed
    except Exception:
        logger.warning("Failed to auto-shadow assignment to graph", exc_info=True)

    result = {
        "assigned": True,
        "agent": agent_name,
        "ticket": {
            "id": ticket_record.id,
            "title": ticket_record.title,
            "description": ticket_record.description,
            "previous_status": ticket_record.status,
        },
        "priority": priority,
        "agent_instance_code": agent_instance_code,
        "note": None if agent_instance_code else "No active agent instance found",
        "linear_synced": False,
    }

    # Sync to Linear if ticket looks like a Linear identifier
    from herd_mcp import linear_client

    if linear_client.is_linear_identifier(ticket_id):
        try:
            if registry.tickets:
                registry.tickets.transition(ticket_id, "assigned")
                result["linear_synced"] = True
                logger.info(
                    f"Synced ticket {ticket_id} assignment to Linear (via adapter)"
                )
            else:
                linear_issue = linear_client.get_issue(ticket_id)
                if linear_issue:
                    linear_client.update_issue_state(
                        linear_issue["id"], "408b4cda-4d6e-403a-8030-78e8b0a6ffee"
                    )
                    result["linear_synced"] = True
                    logger.info(f"Synced ticket {ticket_id} assignment to Linear")
                else:
                    logger.warning(f"Could not find Linear issue {ticket_id} for sync")
        except Exception as e:
            logger.warning(f"Failed to sync ticket {ticket_id} to Linear: {e}")
            result["linear_sync_error"] = str(e)

    return result
