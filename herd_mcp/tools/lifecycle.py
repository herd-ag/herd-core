"""Agent lifecycle tool implementations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from herd_core.types import AgentRecord, AgentState, LifecycleEvent
from herd_mcp.vault_refresh import get_manager

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry

logger = logging.getLogger(__name__)


async def decommission(
    agent_name: str, current_agent: str | None, registry: AdapterRegistry | None = None
) -> dict:
    """Permanently decommission an agent instance.

    Args:
        agent_name: Agent to decommission.
        current_agent: Current agent identity (requesting decommission).
        registry: Optional adapter registry for dependency injection.

    Returns:
        Dict with success status and message.
    """
    if not registry or not registry.store:
        return {"error": "StoreAdapter not configured"}

    store = registry.store

    # Find active agent instances for this agent
    instances = store.list(AgentRecord, agent=agent_name, active=True)

    if not instances:
        return {
            "success": False,
            "error": f"Agent {agent_name} not found",
            "target_agent": agent_name,
            "requested_by": current_agent,
        }

    # Capture previous state from first instance
    previous_state = instances[0].state.value if instances[0].state else "unknown"

    # End all active instances
    ended_count = 0
    async with registry.write_lock:
        for instance in instances:
            # Update state to stopped
            instance.state = AgentState.STOPPED
            from datetime import datetime, timezone

            instance.ended_at = datetime.now(timezone.utc)
            store.save(instance)

            # Append lifecycle event
            store.append(
                LifecycleEvent(
                    entity_id=instance.id,
                    event_type="decommissioned",
                    instance_id=instance.id,
                    detail=f"Decommissioned by {current_agent or 'system'}",
                )
            )
            ended_count += 1

    result = {
        "success": True,
        "target_agent": agent_name,
        "previous_status": previous_state,
        "new_status": "decommissioned",
        "instances_ended": ended_count,
        "requested_by": current_agent,
    }

    # Trigger vault refresh after agent decommission
    refresh_manager = get_manager()
    refresh_result = await refresh_manager.trigger_refresh(
        "agent_decommissioned",
        {
            "agent_name": agent_name,
            "instances_ended": ended_count,
            "requested_by": current_agent,
        },
    )
    logger.info(
        f"Vault refresh triggered after decommission: {refresh_result.get('status')}",
        extra={"refresh_result": refresh_result},
    )

    return result


async def standdown(
    agent_name: str, current_agent: str | None, registry: AdapterRegistry | None = None
) -> dict:
    """Temporarily stand down an agent instance.

    Args:
        agent_name: Agent to stand down.
        current_agent: Current agent identity (requesting standdown).
        registry: Optional adapter registry for dependency injection.

    Returns:
        Dict with success status and message.
    """
    if not registry or not registry.store:
        return {"error": "StoreAdapter not configured"}

    store = registry.store

    # Find active agent instances for this agent
    instances = store.list(AgentRecord, agent=agent_name, active=True)

    if not instances:
        return {
            "success": False,
            "error": f"Agent {agent_name} not found",
            "target_agent": agent_name,
            "requested_by": current_agent,
        }

    # Capture previous state from first instance
    previous_state = instances[0].state.value if instances[0].state else "unknown"

    # End all active instances with standdown
    ended_count = 0
    async with registry.write_lock:
        for instance in instances:
            # Update state to stopped
            instance.state = AgentState.STOPPED
            from datetime import datetime, timezone

            instance.ended_at = datetime.now(timezone.utc)
            store.save(instance)

            # Append lifecycle event
            store.append(
                LifecycleEvent(
                    entity_id=instance.id,
                    event_type="standdown",
                    instance_id=instance.id,
                    detail=f"Stood down by {current_agent or 'system'}",
                )
            )
            ended_count += 1

    return {
        "success": True,
        "target_agent": agent_name,
        "previous_status": previous_state,
        "new_status": "standby",
        "instances_ended": ended_count,
        "requested_by": current_agent,
    }
