"""Graph query tool for the KuzuDB structural graph store.

Provides an MCP tool entry point for executing Cypher queries against
the KuzuDB graph database. Wraps herd_mcp.graph.query_graph with
error handling and structured response formatting.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def execute(
    query: str,
    params: dict | None = None,
    registry=None,
) -> dict:
    """Execute a Cypher query against the KuzuDB graph.

    Args:
        query: Cypher query string (e.g., "MATCH (a:Agent) RETURN a.id, a.role").
        params: Optional dict of query parameters (referenced as $name
                in the Cypher query).
        registry: Adapter registry (unused, accepted for interface consistency).

    Returns:
        Dict with 'results' (list of row dicts) and 'count' on success,
        or 'error' (str) on failure.
    """
    try:
        from herd_mcp.graph import query_graph
    except ImportError as exc:
        return {
            "error": (
                "Structural graph store is unavailable. kuzu is not installed. "
                f"Install with: pip install 'kuzu>=0.11'. Details: {exc}"
            ),
        }

    try:
        results = query_graph(query, params)
        return {
            "results": results,
            "count": len(results),
        }
    except RuntimeError as exc:
        logger.warning("Graph query failed: %s", exc)
        return {"error": str(exc)}
    except Exception as exc:
        logger.exception("Unexpected error during graph query")
        return {"error": f"Graph query failed unexpectedly: {exc}"}
