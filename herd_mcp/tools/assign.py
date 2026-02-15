"""Ticket assignment tool implementation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from herd_mcp import linear_client
from herd_mcp.db import connection

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

    # Adapter path for ticket lookup
    ticket = None
    if registry and registry.store:
        try:
            from herd_core.entities import TicketRecord

            ticket_record = registry.store.get(TicketRecord, ticket_id)
            if ticket_record:
                ticket = (
                    ticket_record.ticket_code,
                    ticket_record.title,
                    ticket_record.description,
                    ticket_record.current_status,
                )
        except Exception:
            pass

    # Fallback to raw SQL
    if ticket is None:
        with connection() as conn:
            # Verify ticket exists
            ticket = conn.execute(
                """
                SELECT ticket_code, ticket_title, ticket_description, ticket_current_status
                FROM herd.ticket_def
                WHERE ticket_code = ?
                  AND deleted_at IS NULL
                """,
                [ticket_id],
            ).fetchone()

    # Continue with existing logic
    with connection() as conn:

        # Auto-register from Linear if not found and looks like Linear ID
        if not ticket and linear_client.is_linear_identifier(ticket_id):
            logger.info(f"Ticket {ticket_id} not found in DB, attempting Linear fetch")
            from herd_core.types import TicketRecord

            tr: TicketRecord | None = None
            if registry and registry.tickets:
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
                conn.execute(
                    """
                    INSERT INTO herd.ticket_def
                      (ticket_code, ticket_title, ticket_description, ticket_current_status,
                       project_code, created_at, modified_at)
                    VALUES (?, ?, ?, 'backlog', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    [tr.id, tr.title or "", tr.description or "", tr.project],
                )
                logger.info(f"Auto-registered ticket {ticket_id} from Linear")

                # Re-fetch the ticket
                ticket = conn.execute(
                    """
                    SELECT ticket_code, ticket_title, ticket_description, ticket_current_status
                    FROM herd.ticket_def
                    WHERE ticket_code = ?
                    """,
                    [ticket_id],
                ).fetchone()

        if not ticket:
            return {
                "assigned": False,
                "error": f"Ticket {ticket_id} not found in DB or Linear",
                "agent": agent_name,
                "ticket": ticket_id,
                "priority": priority,
            }

        # Verify agent exists and is active
        agent = conn.execute(
            """
            SELECT agent_code, agent_role, agent_status
            FROM herd.agent_def
            WHERE agent_code = ?
              AND deleted_at IS NULL
            """,
            [agent_name],
        ).fetchone()

        if not agent:
            return {
                "assigned": False,
                "error": f"Agent {agent_name} not found",
                "agent": agent_name,
                "ticket": {
                    "id": ticket[0],
                    "title": ticket[1],
                },
                "priority": priority,
            }

        if agent[2] != "active":
            return {
                "assigned": False,
                "error": f"Agent {agent_name} is not active (status: {agent[2]})",
                "agent": agent_name,
                "ticket": {
                    "id": ticket[0],
                    "title": ticket[1],
                },
                "priority": priority,
            }

        # Get or note agent's current active instance
        instance = conn.execute(
            """
            SELECT agent_instance_code
            FROM herd.agent_instance
            WHERE agent_code = ?
              AND agent_instance_ended_at IS NULL
            ORDER BY agent_instance_started_at DESC
            LIMIT 1
            """,
            [agent_name],
        ).fetchone()

        agent_instance_code = instance[0] if instance else None

        if not agent_instance_code:
            # Note: in production, we'd probably create an instance here
            # For now, we'll just note that no instance exists
            pass

        # Record assignment in ticket_activity (always, even with NULL agent_instance_code)
        conn.execute(
            """
            INSERT INTO herd.agent_instance_ticket_activity
              (agent_instance_code, ticket_code, ticket_event_type, ticket_status,
               ticket_activity_comment, created_at)
            VALUES (?, ?, 'assigned', 'assigned', ?, CURRENT_TIMESTAMP)
            """,
            [agent_instance_code, ticket_id, f"Assigned with priority: {priority}"],
        )

        # Update ticket_def convenience denorm
        conn.execute(
            """
            UPDATE herd.ticket_def
            SET ticket_current_status = 'assigned', modified_at = CURRENT_TIMESTAMP
            WHERE ticket_code = ?
            """,
            [ticket_id],
        )

        result = {
            "assigned": True,
            "agent": agent_name,
            "ticket": {
                "id": ticket[0],
                "title": ticket[1],
                "description": ticket[2],
                "previous_status": ticket[3],
            },
            "priority": priority,
            "agent_instance_code": agent_instance_code,
            "note": None if agent_instance_code else "No active agent instance found",
            "linear_synced": False,
        }

    # Sync to Linear if ticket looks like a Linear identifier - use adapter if available
    if linear_client.is_linear_identifier(ticket_id):
        try:
            if registry and registry.tickets:
                registry.tickets.transition(ticket_id, "assigned")
                result["linear_synced"] = True
                logger.info(
                    f"Synced ticket {ticket_id} assignment to Linear (via adapter)"
                )
            else:
                linear_issue = linear_client.get_issue(ticket_id)
                if linear_issue:
                    # Update to "Assigned" state in Linear
                    # State UUID for "Assigned": 408b4cda-4d6e-403a-8030-78e8b0a6ffee
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
