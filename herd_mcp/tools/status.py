"""Status query tool implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from herd_mcp.db import connection

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry


def _get_active_agents(conn: Any) -> list[dict]:
    """Get all active agents with their current assignments.

    Args:
        conn: DuckDB connection.

    Returns:
        List of agent dicts with assignment info.
    """
    agents = []
    result = conn.execute("""
        SELECT agent_code, agent_role, agent_status, default_model_code
        FROM herd.agent_def
        WHERE deleted_at IS NULL
        """).fetchall()

    for row in result:
        agent = {
            "agent_code": row[0],
            "agent_role": row[1],
            "agent_status": row[2],
            "default_model": row[3],
            "current_assignment": None,
        }

        # Check for active instance with assignment
        assignment = conn.execute(
            """
            SELECT ai.ticket_code, ai.agent_instance_started_at
            FROM herd.agent_instance ai
            WHERE ai.agent_code = ?
              AND ai.agent_instance_ended_at IS NULL
            ORDER BY ai.agent_instance_started_at DESC
            LIMIT 1
            """,
            [row[0]],
        ).fetchone()

        if assignment:
            agent["current_assignment"] = {
                "ticket_code": assignment[0],
                "started_at": str(assignment[1]) if assignment[1] else None,
            }

        agents.append(agent)

    return agents


def _get_blocked_tickets(conn: Any) -> list[dict]:
    """Get all currently blocked tickets.

    Args:
        conn: DuckDB connection.

    Returns:
        List of blocked ticket dicts.
    """
    blockers = []
    result = conn.execute("""
        WITH blocked_events AS (
            SELECT
                ta.ticket_code,
                ta.blocker_ticket_code,
                ta.blocker_description,
                ta.created_at,
                ROW_NUMBER() OVER (PARTITION BY ta.ticket_code ORDER BY ta.created_at DESC) as rn
            FROM herd.agent_instance_ticket_activity ta
            WHERE ta.ticket_event_type = 'blocked'
        ),
        unblocked_events AS (
            SELECT
                ticket_code,
                MAX(created_at) as unblocked_at
            FROM herd.agent_instance_ticket_activity
            WHERE ticket_event_type = 'unblocked'
            GROUP BY ticket_code
        )
        SELECT
            be.ticket_code,
            be.blocker_ticket_code,
            be.blocker_description,
            be.created_at
        FROM blocked_events be
        LEFT JOIN unblocked_events ue ON be.ticket_code = ue.ticket_code
        WHERE be.rn = 1
          AND (ue.unblocked_at IS NULL OR be.created_at > ue.unblocked_at)
        """).fetchall()

    for row in result:
        blockers.append(
            {
                "ticket_code": row[0],
                "blocker_ticket_code": row[1],
                "blocker_description": row[2],
                "blocked_since": str(row[3]) if row[3] else None,
            }
        )

    return blockers


def _get_current_sprint(conn: Any) -> dict | None:
    """Get current active sprint.

    Args:
        conn: DuckDB connection.

    Returns:
        Sprint dict or None if no active sprint.
    """
    result = conn.execute("""
        SELECT
            sprint_code,
            sprint_title,
            sprint_goal,
            sprint_started_at,
            sprint_planned_end_at
        FROM herd.sprint_def
        WHERE sprint_actual_end_at IS NULL
          AND deleted_at IS NULL
        ORDER BY sprint_started_at DESC
        LIMIT 1
        """).fetchone()

    if not result:
        return None

    sprint = {
        "sprint_code": result[0],
        "sprint_title": result[1],
        "sprint_goal": result[2],
        "started_at": str(result[3]) if result[3] else None,
        "planned_end_at": str(result[4]) if result[4] else None,
        "tickets": [],
    }

    # Get tickets in this sprint
    tickets = conn.execute(
        """
        SELECT ticket_code, ticket_title, ticket_current_status
        FROM herd.ticket_def
        WHERE current_sprint_code = ?
          AND deleted_at IS NULL
        """,
        [result[0]],
    ).fetchall()

    for ticket in tickets:
        sprint["tickets"].append(
            {
                "ticket_code": ticket[0],
                "ticket_title": ticket[1],
                "status": ticket[2],
            }
        )

    return sprint


def _get_agent_status(conn: Any, agent_name: str) -> dict:
    """Get status for a specific agent.

    Args:
        conn: DuckDB connection.
        agent_name: Agent code to query.

    Returns:
        Agent status dict.
    """
    # Get agent info
    agent_info = conn.execute(
        """
        SELECT agent_code, agent_role, agent_status, default_model_code
        FROM herd.agent_def
        WHERE agent_code = ?
          AND deleted_at IS NULL
        """,
        [agent_name],
    ).fetchone()

    if not agent_info:
        return {"error": f"Agent {agent_name} not found"}

    # Get all instances for this agent
    instances = conn.execute(
        """
        SELECT
            agent_instance_code,
            ticket_code,
            agent_instance_started_at,
            agent_instance_ended_at,
            agent_instance_outcome
        FROM herd.agent_instance
        WHERE agent_code = ?
        ORDER BY agent_instance_started_at DESC
        LIMIT 10
        """,
        [agent_name],
    ).fetchall()

    instance_list = []
    for inst in instances:
        instance_list.append(
            {
                "instance_code": inst[0],
                "ticket_code": inst[1],
                "started_at": str(inst[2]) if inst[2] else None,
                "ended_at": str(inst[3]) if inst[3] else None,
                "outcome": inst[4],
            }
        )

    return {
        "agent_code": agent_info[0],
        "agent_role": agent_info[1],
        "agent_status": agent_info[2],
        "default_model": agent_info[3],
        "recent_instances": instance_list,
    }


def _get_ticket_status(conn: Any, ticket_id: str) -> dict:
    """Get full lifecycle for a specific ticket.

    Args:
        conn: DuckDB connection.
        ticket_id: Ticket code to query.

    Returns:
        Ticket status dict with full activity history.
    """
    # Get ticket info
    ticket_info = conn.execute(
        """
        SELECT
            ticket_code,
            ticket_title,
            ticket_description,
            ticket_current_status,
            current_sprint_code
        FROM herd.ticket_def
        WHERE ticket_code = ?
          AND deleted_at IS NULL
        """,
        [ticket_id],
    ).fetchone()

    if not ticket_info:
        return {"error": f"Ticket {ticket_id} not found"}

    # Get activity history
    activities = conn.execute(
        """
        SELECT
            agent_instance_code,
            ticket_event_type,
            ticket_status,
            ticket_activity_comment,
            created_at
        FROM herd.agent_instance_ticket_activity
        WHERE ticket_code = ?
        ORDER BY created_at DESC
        """,
        [ticket_id],
    ).fetchall()

    activity_list = []
    for act in activities:
        activity_list.append(
            {
                "agent_instance": act[0],
                "event_type": act[1],
                "status": act[2],
                "comment": act[3],
                "timestamp": str(act[4]) if act[4] else None,
            }
        )

    return {
        "ticket_code": ticket_info[0],
        "ticket_title": ticket_info[1],
        "ticket_description": ticket_info[2],
        "current_status": ticket_info[3],
        "sprint_code": ticket_info[4],
        "activity_history": activity_list,
    }


def _get_available_agents(conn: Any) -> list[dict]:
    """Get agents with no active instance.

    Args:
        conn: DuckDB connection.

    Returns:
        List of available agent dicts.
    """
    result = conn.execute("""
        SELECT ad.agent_code, ad.agent_role, ad.agent_status
        FROM herd.agent_def ad
        WHERE ad.deleted_at IS NULL
          AND ad.agent_code NOT IN (
              SELECT DISTINCT agent_code
              FROM herd.agent_instance
              WHERE agent_instance_ended_at IS NULL
          )
        """).fetchall()

    available = []
    for row in result:
        available.append(
            {
                "agent_code": row[0],
                "agent_role": row[1],
                "agent_status": row[2],
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
    # NOTE: Complex aggregate queries (JOINs, GROUP BY, subqueries) in status.py
    # are kept as raw SQL. StoreAdapter's generic CRUD interface doesn't cover
    # these analytics queries. Future: ReportingAdapter or store.raw_query().
    with connection() as conn:
        if scope == "all":
            return {
                "scope": scope,
                "agents": _get_active_agents(conn),
                "sprint": _get_current_sprint(conn),
                "blockers": _get_blocked_tickets(conn),
                "requesting_agent": agent_name,
            }
        elif scope == "sprint":
            return {
                "scope": scope,
                "sprint": _get_current_sprint(conn),
                "requesting_agent": agent_name,
            }
        elif scope.startswith("agent:"):
            target_agent = scope.split(":", 1)[1]
            return {
                "scope": scope,
                "agent_status": _get_agent_status(conn, target_agent),
                "requesting_agent": agent_name,
            }
        elif scope.startswith("ticket:"):
            ticket_id = scope.split(":", 1)[1]
            return {
                "scope": scope,
                "ticket_status": _get_ticket_status(conn, ticket_id),
                "requesting_agent": agent_name,
            }
        elif scope == "available":
            return {
                "scope": scope,
                "available_agents": _get_available_agents(conn),
                "requesting_agent": agent_name,
            }
        elif scope == "blocked":
            return {
                "scope": scope,
                "blockers": _get_blocked_tickets(conn),
                "requesting_agent": agent_name,
            }
        else:
            # Default to "all" for unknown scopes
            return {
                "scope": "all",
                "agents": _get_active_agents(conn),
                "sprint": _get_current_sprint(conn),
                "blockers": _get_blocked_tickets(conn),
                "requesting_agent": agent_name,
            }
