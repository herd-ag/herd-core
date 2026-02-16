"""Ticket creation tool implementation."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from herd_core.types import TicketEvent, TicketRecord

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry

logger = logging.getLogger(__name__)

# Map human-readable priority strings to Linear priority integers.
# Linear uses: 0=None, 1=Urgent, 2=High, 3=Normal, 4=Low.
PRIORITY_MAP: dict[str, int] = {
    "none": 0,
    "urgent": 1,
    "high": 2,
    "normal": 3,
    "low": 4,
}


async def execute(
    title: str,
    description: str | None,
    priority: str | None,
    labels: list[str] | None,
    agent_name: str | None,
    registry: AdapterRegistry | None = None,
) -> dict:
    """Create a new ticket via the TicketAdapter.

    Args:
        title: Ticket title (required).
        description: Optional ticket description.
        priority: Optional priority string (none, urgent, high, normal, low).
        labels: Optional list of label IDs.
        agent_name: Calling agent identity.
        registry: Optional adapter registry for dependency injection.

    Returns:
        Dict with created ticket identifier and details.
    """
    if not title or not title.strip():
        return {"created": False, "error": "title is required and must not be empty"}

    if not registry or not registry.tickets:
        return {"created": False, "error": "TicketAdapter not configured"}

    # Resolve priority string to integer
    priority_int: int | None = None
    if priority:
        priority_lower = priority.lower()
        if priority_lower not in PRIORITY_MAP:
            return {
                "created": False,
                "error": (
                    f"Invalid priority '{priority}'. "
                    f"Expected one of: {', '.join(PRIORITY_MAP.keys())}"
                ),
            }
        priority_int = PRIORITY_MAP[priority_lower]

    # Resolve team ID from environment (HDR-0032 pattern)
    team_id = os.getenv("HERD_TICKET_LINEAR_TEAM_ID", "")

    # Create ticket via adapter
    try:
        ticket_id = registry.tickets.create(
            title,
            description=description,
            team_id=team_id or None,
            priority=priority_int,
            labels=labels,
        )
    except Exception as e:
        logger.warning("Failed to create ticket via adapter: %s", e)
        return {"created": False, "error": f"Adapter error: {e}"}

    # Save to local store if available
    if registry.store:
        ticket_record = TicketRecord(
            id=ticket_id,
            title=title,
            description=description,
            status="backlog",
            labels=labels or [],
        )
        try:
            async with registry.write_lock:
                registry.store.save(ticket_record)
                registry.store.append(
                    TicketEvent(
                        entity_id=ticket_id,
                        event_type="created",
                        instance_id="",
                        previous_status="",
                        new_status="backlog",
                        note=f"Created by {agent_name or 'unknown'}",
                    )
                )
        except Exception as e:
            logger.warning(
                "Created ticket %s in Linear but failed to save locally: %s",
                ticket_id,
                e,
            )

    # Auto-shadow to KuzuDB graph
    try:
        from herd_mcp.graph import merge_node

        merge_node(
            "Ticket",
            {
                "id": ticket_id,
                "title": title,
                "status": "backlog",
                "priority": priority or "",
            },
        )
    except ImportError:
        pass  # KuzuDB not installed
    except Exception:
        logger.warning("Failed to auto-shadow ticket creation to graph", exc_info=True)

    return {
        "created": True,
        "ticket_id": ticket_id,
        "title": title,
        "description": description,
        "priority": priority,
        "labels": labels,
        "agent": agent_name,
    }
