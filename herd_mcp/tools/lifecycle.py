"""Agent lifecycle tool implementations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from herd_mcp.db import connection
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
    # Adapter path (for simple CRUD operations)
    if registry and registry.store:
        try:
            from herd_core.entities import AgentRecord, LifecycleEvent

            # Get agent record
            agent_record = registry.store.get(AgentRecord, agent_name)

            if not agent_record:
                return {
                    "success": False,
                    "error": f"Agent {agent_name} not found",
                    "target_agent": agent_name,
                    "requested_by": current_agent,
                }

            previous_status = agent_record.status

            # Update agent status
            agent_record.status = "decommissioned"
            registry.store.save(agent_record)

            # End active instances via store (list + save)
            instances = registry.store.list(
                AgentRecord, agent_code=agent_name, ended_at=None
            )
            ended_count = len(instances)

            for instance in instances:
                # Append lifecycle event
                lifecycle_event = LifecycleEvent(
                    agent_instance_code=instance.instance_code,
                    event_type="decommissioned",
                    detail=f"Decommissioned by {current_agent or 'system'}",
                )
                registry.store.append(lifecycle_event)

            result = {
                "success": True,
                "target_agent": agent_name,
                "previous_status": previous_status,
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
        except Exception as e:
            logger.warning(f"StoreAdapter failed for decommission, falling back to SQL: {e}")
            # Fall through to SQL fallback

    # Fallback to raw SQL
    with connection() as conn:
        # Find agent_def
        agent_def = conn.execute(
            """
            SELECT agent_code, agent_status
            FROM herd.agent_def
            WHERE agent_code = ?
              AND deleted_at IS NULL
            """,
            [agent_name],
        ).fetchone()

        if not agent_def:
            return {
                "success": False,
                "error": f"Agent {agent_name} not found",
                "target_agent": agent_name,
                "requested_by": current_agent,
            }

        # Update agent_def to decommissioned status
        conn.execute(
            """
            UPDATE herd.agent_def
            SET agent_status = 'decommissioned',
                modified_at = CURRENT_TIMESTAMP
            WHERE agent_code = ?
            """,
            [agent_name],
        )

        # End any active instances
        ended_count = 0
        active_instances = conn.execute(
            """
            SELECT agent_instance_code
            FROM herd.agent_instance
            WHERE agent_code = ?
              AND agent_instance_ended_at IS NULL
            """,
            [agent_name],
        ).fetchall()

        for row in active_instances:
            instance_code = row[0]

            # End the instance
            conn.execute(
                """
                UPDATE herd.agent_instance
                SET agent_instance_ended_at = CURRENT_TIMESTAMP,
                    agent_instance_outcome = 'decommissioned'
                WHERE agent_instance_code = ?
                """,
                [instance_code],
            )

            # Record lifecycle activity
            conn.execute(
                """
                INSERT INTO herd.agent_instance_lifecycle_activity
                  (agent_instance_code, lifecycle_event_type, lifecycle_detail, created_at)
                VALUES (?, 'decommissioned', ?, CURRENT_TIMESTAMP)
                """,
                [
                    instance_code,
                    f"Decommissioned by {current_agent or 'system'}",
                ],
            )

            ended_count += 1

        result = {
            "success": True,
            "target_agent": agent_name,
            "previous_status": agent_def[1],
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
    # Adapter path (for simple CRUD operations)
    if registry and registry.store:
        try:
            from herd_core.entities import AgentRecord, LifecycleEvent

            # Get agent record
            agent_record = registry.store.get(AgentRecord, agent_name)

            if not agent_record:
                return {
                    "success": False,
                    "error": f"Agent {agent_name} not found",
                    "target_agent": agent_name,
                    "requested_by": current_agent,
                }

            previous_status = agent_record.status

            # Update agent status
            agent_record.status = "standby"
            registry.store.save(agent_record)

            # End active instances via store (list + append events)
            instances = registry.store.list(
                AgentRecord, agent_code=agent_name, ended_at=None
            )
            ended_count = len(instances)

            for instance in instances:
                # Append lifecycle event
                lifecycle_event = LifecycleEvent(
                    agent_instance_code=instance.instance_code,
                    event_type="standdown",
                    detail=f"Stood down by {current_agent or 'system'}",
                )
                registry.store.append(lifecycle_event)

            return {
                "success": True,
                "target_agent": agent_name,
                "previous_status": previous_status,
                "new_status": "standby",
                "instances_ended": ended_count,
                "requested_by": current_agent,
            }
        except Exception as e:
            logger.warning(f"StoreAdapter failed for standdown, falling back to SQL: {e}")
            # Fall through to SQL fallback

    # Fallback to raw SQL
    with connection() as conn:
        # Find agent_def
        agent_def = conn.execute(
            """
            SELECT agent_code, agent_status
            FROM herd.agent_def
            WHERE agent_code = ?
              AND deleted_at IS NULL
            """,
            [agent_name],
        ).fetchone()

        if not agent_def:
            return {
                "success": False,
                "error": f"Agent {agent_name} not found",
                "target_agent": agent_name,
                "requested_by": current_agent,
            }

        # Update agent_def to standby status
        conn.execute(
            """
            UPDATE herd.agent_def
            SET agent_status = 'standby',
                modified_at = CURRENT_TIMESTAMP
            WHERE agent_code = ?
            """,
            [agent_name],
        )

        # End any active instances with standdown outcome
        ended_count = 0
        active_instances = conn.execute(
            """
            SELECT agent_instance_code
            FROM herd.agent_instance
            WHERE agent_code = ?
              AND agent_instance_ended_at IS NULL
            """,
            [agent_name],
        ).fetchall()

        for row in active_instances:
            instance_code = row[0]

            # End the instance
            conn.execute(
                """
                UPDATE herd.agent_instance
                SET agent_instance_ended_at = CURRENT_TIMESTAMP,
                    agent_instance_outcome = 'standdown'
                WHERE agent_instance_code = ?
                """,
                [instance_code],
            )

            # Record lifecycle activity
            conn.execute(
                """
                INSERT INTO herd.agent_instance_lifecycle_activity
                  (agent_instance_code, lifecycle_event_type, lifecycle_detail, created_at)
                VALUES (?, 'standdown', ?, CURRENT_TIMESTAMP)
                """,
                [
                    instance_code,
                    f"Stood down by {current_agent or 'system'}",
                ],
            )

            ended_count += 1

        return {
            "success": True,
            "target_agent": agent_name,
            "previous_status": agent_def[1],
            "new_status": "standby",
            "instances_ended": ended_count,
            "requested_by": current_agent,
        }
