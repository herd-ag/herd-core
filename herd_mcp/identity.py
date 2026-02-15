"""Agent identity resolution for Herd MCP server.

This module provides identity resolution capabilities that map environment
variables (HERD_AGENT_NAME) to agent_code and agent_instance_code in the
Herd database.
"""

from __future__ import annotations

import os
import uuid

from herd_mcp.db import connection


def get_agent_name_from_env() -> str | None:
    """Get the agent name from environment.

    Returns:
        Agent name from HERD_AGENT_NAME environment variable, or None.
    """
    return os.getenv("HERD_AGENT_NAME")


def resolve_agent_code(agent_name: str | None) -> str | None:
    """Resolve agent name to agent_code.

    Args:
        agent_name: Agent name from environment (e.g., "mini-mao", "grunt").

    Returns:
        Agent code from agent_def table, or None if not found.

    Raises:
        Exception: If database connection fails.
    """
    if not agent_name:
        return None

    with connection() as conn:
        result = conn.execute(
            """
            SELECT agent_code
            FROM herd.agent_def
            WHERE agent_code = ?
              AND deleted_at IS NULL
            LIMIT 1
            """,
            [agent_name],
        ).fetchone()

        return result[0] if result else None


def resolve_or_create_agent_instance(
    agent_code: str,
    model_code: str | None = None,
    ticket_code: str | None = None,
    craft_version_code: str | None = None,
    personality_version_code: str | None = None,
) -> str:
    """Get or create an active agent instance.

    This function checks for an existing active instance for the agent.
    If one exists, it returns that instance code. If not, it creates a new one.

    Args:
        agent_code: Agent code from agent_def.
        model_code: Optional model code to use for new instance.
        ticket_code: Optional ticket code the agent is working on.
        craft_version_code: Optional craft version code.
        personality_version_code: Optional personality version code.

    Returns:
        Agent instance code (existing or newly created).
    """
    with connection() as conn:
        # Check for existing active instance
        existing = conn.execute(
            """
            SELECT agent_instance_code
            FROM herd.agent_instance
            WHERE agent_code = ?
              AND agent_instance_ended_at IS NULL
            ORDER BY agent_instance_started_at DESC
            LIMIT 1
            """,
            [agent_code],
        ).fetchone()

        if existing:
            return existing[0]

        # Get default model if not provided
        if not model_code:
            agent_def = conn.execute(
                """
                SELECT default_model_code
                FROM herd.agent_def
                WHERE agent_code = ?
                  AND deleted_at IS NULL
                """,
                [agent_code],
            ).fetchone()

            model_code = (
                agent_def[0] if agent_def and agent_def[0] else "claude-sonnet-4"
            )

        # Create new instance
        instance_code = f"inst-{uuid.uuid4().hex[:8]}"

        conn.execute(
            """
            INSERT INTO herd.agent_instance
              (agent_instance_code, agent_code, model_code, ticket_code,
               craft_version_code, personality_version_code,
               spawned_by_agent_instance_code, agent_instance_started_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL, CURRENT_TIMESTAMP)
            """,
            [
                instance_code,
                agent_code,
                model_code,
                ticket_code,
                craft_version_code,
                personality_version_code,
            ],
        )

        # Record lifecycle activity
        conn.execute(
            """
            INSERT INTO herd.agent_instance_lifecycle_activity
              (agent_instance_code, lifecycle_event_type, lifecycle_detail, created_at)
            VALUES (?, 'spawned', ?, CURRENT_TIMESTAMP)
            """,
            [
                instance_code,
                f"Auto-spawned for {agent_code} on session start with model {model_code}",
            ],
        )

        return instance_code


def resolve_identity() -> dict:
    """Resolve the current agent's full identity.

    This is the main entry point for identity resolution. It reads the
    HERD_AGENT_NAME environment variable, looks up the agent_code in
    agent_def, and resolves or creates an active agent_instance.

    Returns:
        Dict with identity information:
        - agent_name: From environment (or None)
        - agent_code: From agent_def (or None)
        - agent_instance_code: From agent_instance (or None)
        - is_resolved: True if full identity was resolved

    Example:
        >>> identity = resolve_identity()
        >>> if identity["is_resolved"]:
        ...     print(f"Agent: {identity['agent_name']}")
        ...     print(f"Instance: {identity['agent_instance_code']}")
    """
    agent_name = get_agent_name_from_env()

    if not agent_name:
        return {
            "agent_name": None,
            "agent_code": None,
            "agent_instance_code": None,
            "is_resolved": False,
            "error": "HERD_AGENT_NAME not set in environment",
        }

    try:
        agent_code = resolve_agent_code(agent_name)

        if not agent_code:
            return {
                "agent_name": agent_name,
                "agent_code": None,
                "agent_instance_code": None,
                "is_resolved": False,
                "error": f"Agent '{agent_name}' not found in agent_def table",
            }

        # Resolve or create agent instance
        agent_instance_code = resolve_or_create_agent_instance(agent_code)

        return {
            "agent_name": agent_name,
            "agent_code": agent_code,
            "agent_instance_code": agent_instance_code,
            "is_resolved": True,
        }
    except Exception as e:
        return {
            "agent_name": agent_name,
            "agent_code": None,
            "agent_instance_code": None,
            "is_resolved": False,
            "error": f"Database connection failed: {e}",
        }
