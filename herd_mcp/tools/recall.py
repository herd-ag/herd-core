"""Semantic memory recall and remember tools for agent cross-session context.

Provides two MCP tool entry points:
  - execute()  — search semantic memory (herd_recall)
  - store()    — store a new memory (herd_remember)
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


async def execute(
    query: str,
    limit: int = 5,
    project: str | None = None,
    agent: str | None = None,
    memory_type: str | None = None,
    repo: str | None = None,
    org: str | None = None,
    team: str | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    """Search semantic memory for relevant context.

    Formulate queries as conceptual descriptions, not keywords.
    "How we handle configuration across repos" retrieves better than "config".

    Args:
        query: Natural language query string describing what you need.
        limit: Maximum number of results (default 5).
        project: Filter by project (e.g., "herd", "dbt-conceptual").
        agent: Filter by agent name (e.g., "steve", "mason").
        memory_type: Filter by type (session_summary, decision_context,
                     pattern, preference, thread).
        repo: Filter by repository name.
        org: Filter by organization scope.
        team: Filter by team scope.
        host: Filter by host/machine scope.

    Returns:
        Dict with success status and list of matching memories.
    """
    try:
        from herd_mcp.memory import recall
    except ImportError as e:
        return {
            "success": False,
            "error": (
                "Semantic memory is unavailable. Required packages not installed. "
                f"Details: {e}"
            ),
            "memories": [],
        }

    try:
        # Build filters from provided params
        filters: dict[str, Any] = {}
        if project is not None:
            filters["project"] = project
        if agent is not None:
            filters["agent"] = agent
        if memory_type is not None:
            filters["memory_type"] = memory_type
        if repo is not None:
            filters["repo"] = repo
        if org is not None:
            filters["org"] = org
        if team is not None:
            filters["team"] = team
        if host is not None:
            filters["host"] = host

        memories = recall(query, limit=limit, **filters)

        return {
            "success": True,
            "query": query,
            "count": len(memories),
            "memories": memories,
        }
    except Exception as e:
        logger.exception("Error during semantic recall")
        return {
            "success": False,
            "error": f"Recall failed: {e}",
            "memories": [],
        }


async def store(
    content: str,
    memory_type: str,
    project: str = "herd",
    agent_name: str | None = None,
    repo: str | None = None,
    org: str | None = None,
    team: str | None = None,
    host: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Store a memory in the semantic memory system.

    Use this to persist learnings, patterns, preferences, session summaries,
    and decision context across sessions.

    Args:
        content: The text content to store. Should be descriptive and
                 self-contained — this is what gets embedded and searched.
        memory_type: One of: session_summary, decision_context, pattern,
                     preference, thread.
        project: Project identifier (default "herd").
        agent_name: Agent storing the memory (uses HERD_AGENT_NAME if None).
        repo: Optional repository name (null for cross-repo memories).
        org: Optional organization scope (e.g., "herd-ag").
        team: Optional team scope (e.g., "backend").
        host: Optional host/machine scope (e.g., "ci-runner-1").
        session_id: Optional session identifier. Auto-generated from
                    agent name and date if not provided.
        metadata: Optional dict of flexible metadata (hdr_number, ticket_id,
                  principle, etc.).

    Returns:
        Dict with success status and the stored memory ID.
    """
    try:
        from herd_mcp.memory import store_memory
    except ImportError as e:
        return {
            "success": False,
            "error": (
                "Semantic memory is unavailable. Required packages not installed. "
                f"Details: {e}"
            ),
        }

    # Resolve agent name
    agent: str = (
        agent_name if agent_name else (os.getenv("HERD_AGENT_NAME") or "unknown")
    )

    # Auto-generate session_id if not provided
    if not session_id:
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        session_id = f"{agent}-{today}"

    try:
        memory_id = store_memory(
            project=project,
            agent=agent,
            memory_type=memory_type,
            content=content,
            session_id=session_id,
            repo=repo,
            org=org,
            team=team,
            host=host,
            metadata=metadata,
        )

        return {
            "success": True,
            "memory_id": memory_id,
            "agent": agent,
            "memory_type": memory_type,
            "session_id": session_id,
        }
    except ValueError as e:
        return {
            "success": False,
            "error": str(e),
        }
    except Exception as e:
        logger.exception("Error storing memory")
        return {
            "success": False,
            "error": f"Store failed: {e}",
        }
