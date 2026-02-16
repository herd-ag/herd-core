"""Decision record tool implementation."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from herd_core.types import DecisionRecord

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry


def _post_to_slack_decisions(
    decision_text: str, ticket_code: str | None, agent_name: str
) -> dict[str, Any]:
    """Post decision to #herd-decisions Slack channel.

    Args:
        decision_text: Decision summary text.
        ticket_code: Optional ticket code.
        agent_name: Agent name for display.

    Returns:
        Dict with success status and response data.
    """
    token = os.getenv("HERD_NOTIFY_SLACK_TOKEN")
    if not token:
        return {"success": False, "error": "HERD_NOTIFY_SLACK_TOKEN not set"}

    try:
        # Format message with ticket link if available
        if ticket_code:
            message = f"{agent_name} decision on <https://linear.app/dbt-conceptual/issue/{ticket_code}|{ticket_code}>:\n{decision_text}"
        else:
            message = f"{agent_name} decision:\n{decision_text}"

        data = json.dumps(
            {
                "channel": "#herd-decisions",
                "text": message,
                "username": agent_name,
                "icon_emoji": ":brain:",
            }
        ).encode()

        req = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())

        return {"success": result.get("ok", False), "response": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def execute(
    decision_type: str,
    context: str,
    decision: str,
    rationale: str,
    alternatives_considered: str | None,
    ticket_code: str | None,
    agent_name: str | None,
    registry: AdapterRegistry | None = None,
) -> dict:
    """Record an agent decision and post to #herd-decisions.

    Args:
        decision_type: Type of decision (architectural, implementation, pattern, etc).
        context: Context/situation requiring the decision.
        decision: The decision made.
        rationale: Why this decision was made.
        alternatives_considered: Optional alternatives that were considered.
        ticket_code: Optional associated ticket code.
        agent_name: Current agent identity.
        registry: Optional adapter registry for dependency injection.

    Returns:
        Dict with decision_id, posted status, and Slack response.
    """
    if not agent_name:
        return {
            "success": False,
            "error": "No agent identity provided. Cannot record decision.",
        }

    if not registry or not registry.store:
        return {"error": "StoreAdapter not configured"}

    store = registry.store
    decision_id = str(uuid.uuid4())

    # Auto-assign HDR number
    hdr_number = None
    try:
        from herd_mcp.memory import next_hdr_number

        hdr_number = next_hdr_number()
    except Exception:
        logger.warning("Failed to auto-assign HDR number", exc_info=True)
        # Continue without HDR number rather than failing

    # Check for potentially conflicting or related decisions
    related_decisions = []
    try:
        from herd_mcp.memory import recall as semantic_recall

        related_decisions = semantic_recall(
            f"{decision_type}: {decision}",
            limit=3,
            memory_type="decision_context",
        )
    except (ImportError, Exception):
        pass  # Semantic memory unavailable

    # Graph enrichment: decision lineage
    decision_lineage: list[dict] = []
    try:
        from herd_mcp.graph import is_available, query_graph

        if is_available() and ticket_code:
            # Find decisions that share the same ticket scope
            lineage = query_graph(
                "MATCH (t:Ticket {id: $tid})-[:Implements]->(d:Decision) "
                "RETURN d.id AS id, d.title AS title, d.date AS date",
                {"tid": ticket_code},
            )
            decision_lineage = lineage[:10]
    except ImportError:
        pass
    except Exception:
        logger.warning("Failed to enrich decision with graph lineage", exc_info=True)

    # Build the body combining context, decision, rationale, and alternatives
    body_parts = [
        f"**Type**: {decision_type}",
        f"**Context**: {context}",
        f"**Decision**: {decision}",
        f"**Rationale**: {rationale}",
    ]
    if alternatives_considered:
        body_parts.append(f"**Alternatives**: {alternatives_considered}")
    if hdr_number:
        body_parts.insert(0, f"**HDR**: {hdr_number}")
    body = "\n".join(body_parts)

    # Save decision record via store
    decision_record = DecisionRecord(
        id=decision_id,
        title=f"{decision_type}: {decision[:80]}",
        body=body,
        decision_maker=agent_name,
        scope=ticket_code,
        status="accepted",
    )
    async with registry.write_lock:
        store.save(decision_record)

    # Auto-shadow to LanceDB for semantic recall
    try:
        from herd_mcp.memory import store_memory

        summary = f"{decision_type}: {decision}. Rationale: {rationale}"
        metadata = {"ticket_code": ticket_code} if ticket_code else {}
        if hdr_number:
            metadata["hdr_number"] = hdr_number

        store_memory(
            project="herd",
            agent=agent_name,
            memory_type="decision_context",
            content=body,
            summary=summary,
            session_id=f"{agent_name}-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
            metadata=metadata,
        )
    except Exception:
        logger.warning("Failed to auto-shadow decision to LanceDB", exc_info=True)

    # Auto-shadow to KuzuDB graph
    try:
        from herd_mcp.graph import create_edge, merge_node

        merge_node(
            "Decision",
            {
                "id": decision_id,
                "title": f"{decision_type}: {decision[:80]}",
                "date": datetime.now(timezone.utc).isoformat(),
                "status": "accepted",
                "scope": ticket_code or "",
                "principle": "",
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
        create_edge("Decides", "Agent", agent_name, "Decision", decision_id)

        if ticket_code:
            merge_node(
                "Ticket",
                {
                    "id": ticket_code,
                    "title": "",
                    "status": "",
                    "priority": "",
                },
            )
            create_edge("Implements", "Ticket", ticket_code, "Decision", decision_id)
    except ImportError:
        pass  # KuzuDB not installed
    except Exception:
        logger.warning("Failed to auto-shadow decision to graph", exc_info=True)

    # Format decision text for Slack
    decision_text = f"**Type**: {decision_type}\n**Decision**: {decision}\n**Rationale**: {rationale}"
    if hdr_number:
        decision_text = f"**HDR**: {hdr_number}\n{decision_text}"
    if alternatives_considered:
        decision_text += f"\n**Alternatives**: {alternatives_considered}"

    # Post to Slack - use adapter if available
    if registry.notify:
        try:
            # Format message with ticket link if available
            if ticket_code:
                message = f"{agent_name} decision on <https://linear.app/dbt-conceptual/issue/{ticket_code}|{ticket_code}>:\n{decision_text}"
            else:
                message = f"{agent_name} decision:\n{decision_text}"

            registry.notify.post(
                message=message,
                channel="#herd-decisions",
                username=agent_name,
            )
            slack_result = {"success": True}
        except Exception as e:
            slack_result = {"success": False, "error": str(e)}
    else:
        slack_result = _post_to_slack_decisions(decision_text, ticket_code, agent_name)

    return {
        "success": True,
        "decision_id": decision_id,
        "hdr_number": hdr_number,
        "posted_to_slack": slack_result.get("success", False),
        "agent": agent_name,
        "ticket_code": ticket_code,
        "slack_response": slack_result if not slack_result.get("success") else None,
        "related_decisions": (
            [
                {
                    "content": m["content"],
                    "created_at": m.get("created_at"),
                    "agent": m.get("agent"),
                }
                for m in related_decisions
            ]
            if related_decisions
            else []
        ),
        "decision_lineage": decision_lineage,
    }
