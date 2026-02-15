"""Ticket transition tool implementation."""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from herd_mcp import linear_client
from herd_mcp.db import connection
from herd_mcp.vault_refresh import get_manager

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry

logger = logging.getLogger(__name__)


async def execute(
    ticket_id: str,
    to_status: str,
    blocked_by: str | None,
    note: str | None,
    agent_name: str | None,
    registry: AdapterRegistry | None = None,
) -> dict:
    """Transition a ticket to a new status.

    Args:
        ticket_id: Linear ticket ID.
        to_status: Target status.
        blocked_by: Optional blocker ticket ID.
        note: Optional note about the transition.
        agent_name: Current agent identity.
        registry: Optional adapter registry for dependency injection.

    Returns:
        Dict with transition_id and elapsed time in previous status.
    """
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
                    ticket_record.current_status,
                )
        except Exception:
            pass

    # Use single connection context for all SQL operations
    with connection() as conn:
        # Fallback to raw SQL for ticket lookup if adapter didn't work
        if ticket is None:
            # Get current ticket status
            ticket = conn.execute(
                """
                SELECT ticket_code, ticket_title, ticket_current_status
                FROM herd.ticket_def
                WHERE ticket_code = ?
                  AND deleted_at IS NULL
                """,
                [ticket_id],
            ).fetchone()

        # Auto-register from Linear if not found and looks like Linear ID
        if not ticket and linear_client.is_linear_identifier(ticket_id):
            logger.info(f"Ticket {ticket_id} not found in DB, attempting Linear fetch")
            if registry and registry.tickets:
                linear_issue = await registry.tickets.get(ticket_id)
            else:
                linear_issue = linear_client.get_issue(ticket_id)

            if linear_issue:
                # Extract project code from Linear if available
                project_code = None
                if linear_issue.get("project"):
                    project_code = linear_issue["project"].get("name")

                # Insert into ticket_def
                conn.execute(
                    """
                    INSERT INTO herd.ticket_def
                      (ticket_code, ticket_title, ticket_description, ticket_current_status,
                       project_code, created_at, modified_at)
                    VALUES (?, ?, ?, 'backlog', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """,
                    [
                        linear_issue["identifier"],
                        linear_issue.get("title", ""),
                        linear_issue.get("description", ""),
                        project_code,
                    ],
                )
                logger.info(f"Auto-registered ticket {ticket_id} from Linear")

                # Re-fetch the ticket
                ticket = conn.execute(
                    """
                    SELECT ticket_code, ticket_title, ticket_current_status
                    FROM herd.ticket_def
                    WHERE ticket_code = ?
                    """,
                    [ticket_id],
                ).fetchone()

        if not ticket:
            return {
                "transition_id": None,
                "ticket": ticket_id,
                "to_status": to_status,
                "error": f"Ticket {ticket_id} not found in DB or Linear",
            }

        current_status = ticket[2]
        # Get agent's current instance
        agent_instance_code = None
        if agent_name:
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

            if instance:
                agent_instance_code = instance[0]

        # Calculate elapsed time in previous status
        elapsed_minutes = None
        last_activity = conn.execute(
            """
            SELECT created_at
            FROM herd.agent_instance_ticket_activity
            WHERE ticket_code = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            [ticket_id],
        ).fetchone()

        if last_activity and last_activity[0]:
            # Calculate time difference in minutes
            time_diff = conn.execute(
                """
                SELECT EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - ?::TIMESTAMP)) / 60.0
                """,
                [str(last_activity[0])],
            ).fetchone()

            if time_diff:
                elapsed_minutes = float(time_diff[0])

        # Determine event type based on transition
        event_type = "status_changed"
        if to_status == "blocked" or blocked_by:
            event_type = "blocked"
        elif current_status == "blocked" and to_status != "blocked":
            event_type = "unblocked"

        # Generate transition ID
        transition_id = str(uuid.uuid4())

        # Record transition (always, even with NULL agent_instance_code)
        conn.execute(
            """
            INSERT INTO herd.agent_instance_ticket_activity
              (agent_instance_code, ticket_code, ticket_event_type, ticket_status,
               blocker_ticket_code, blocker_description, ticket_activity_comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            [
                agent_instance_code,
                ticket_id,
                event_type,
                to_status,
                blocked_by,
                note if blocked_by else None,
                note,
            ],
        )

        # Update ticket_def convenience denorm
        conn.execute(
            """
            UPDATE herd.ticket_def
            SET ticket_current_status = ?,
                modified_at = CURRENT_TIMESTAMP
            WHERE ticket_code = ?
            """,
            [to_status, ticket_id],
        )

        result = {
            "transition_id": transition_id,
            "ticket": {
                "id": ticket[0],
                "title": ticket[1],
                "previous_status": current_status,
                "new_status": to_status,
            },
            "elapsed_in_previous_minutes": elapsed_minutes,
            "event_type": event_type,
            "blocked_by": blocked_by,
            "agent": agent_name,
            "agent_instance_code": agent_instance_code,
            "note": (
                "No active agent instance found" if not agent_instance_code else None
            ),
            "linear_synced": False,
        }

    # Sync to Linear if ticket looks like a Linear identifier - use adapter if available
    if linear_client.is_linear_identifier(ticket_id):
        if registry and registry.tickets:
            # Use adapter (it handles status mapping internally)
            try:
                await registry.tickets.transition(ticket_id, to_status)
                result["linear_synced"] = True
                logger.info(
                    f"Synced ticket {ticket_id} transition to {to_status} in Linear (via adapter)"
                )
            except Exception as e:
                logger.warning(f"Failed to sync ticket {ticket_id} to Linear: {e}")
                result["linear_sync_error"] = str(e)
        else:
            # Fall back to inline implementation
            # Map internal status to Linear state UUID
            status_to_state_map = {
                "backlog": "f98ff170-87bd-4a1c-badc-4b67cd37edec",
                "assigned": "408b4cda-4d6e-403a-8030-78e8b0a6ffee",
                "in_progress": "77631f63-b27b-45a5-8b04-f9f82b4facde",
                "pr_submitted": "20590520-1bfc-4861-9cb8-e9f2a374d65b",
                "review": "20590520-1bfc-4861-9cb8-e9f2a374d65b",
                "qa_review": "dcbf4d63-b06e-4c1d-ba23-764d95b74193",
                "architect_review": "7a749bd4-bdbc-4924-aee7-9f9f6f8cdd8c",
                "done": "42bad6cf-cfb7-4dd2-9dc4-c0c3014bfc5f",
                "cancelled": "5034b57d-4204-4917-8f18-85e367f0d867",
            }

            linear_state_id = status_to_state_map.get(to_status)

            if linear_state_id:
                try:
                    linear_issue = linear_client.get_issue(ticket_id)
                    if linear_issue:
                        linear_client.update_issue_state(
                            linear_issue["id"], linear_state_id
                        )
                        result["linear_synced"] = True
                        logger.info(
                            f"Synced ticket {ticket_id} transition to {to_status} in Linear"
                        )
                    else:
                        logger.warning(f"Could not find Linear issue {ticket_id} for sync")
                except Exception as e:
                    logger.warning(f"Failed to sync ticket {ticket_id} to Linear: {e}")
                    result["linear_sync_error"] = str(e)
            else:
                # Status like "blocked" has no Linear mapping - just log
                logger.info(f"Status {to_status} has no Linear mapping, skipping sync")

    # Trigger vault refresh if ticket transitioned to done
    if to_status == "done":
        refresh_manager = get_manager()
        refresh_result = await refresh_manager.trigger_refresh(
            "ticket_done",
            {
                "ticket_id": ticket_id,
                "ticket_title": ticket[1],
                "agent": agent_name,
                "previous_status": current_status,
            },
        )
        logger.info(
            f"Vault refresh triggered after ticket done: {refresh_result.get('status')}",
            extra={"refresh_result": refresh_result},
        )

    return result
