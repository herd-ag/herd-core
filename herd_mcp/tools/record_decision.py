"""Decision record tool implementation."""

from __future__ import annotations

import json
import os
import urllib.request
import uuid
from typing import TYPE_CHECKING, Any

from herd_mcp.db import connection

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
    token = os.getenv("HERD_SLACK_TOKEN")
    if not token:
        return {"success": False, "error": "HERD_SLACK_TOKEN not set"}

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
    """Record an agent decision to DuckDB and post to #herd-decisions.

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

    decision_id = str(uuid.uuid4())

    # Adapter path for decision record
    adapter_used = False
    if registry and registry.store:
        try:
            from herd_core.entities import DecisionRecord

            decision_record = DecisionRecord(
                decision_id=decision_id,
                decision_type=decision_type,
                context=context,
                decision=decision,
                rationale=rationale,
                alternatives_considered=alternatives_considered,
                decided_by=agent_name,
                ticket_code=ticket_code,
            )
            registry.store.save(decision_record)
            adapter_used = True
        except Exception:
            # Fall through to SQL fallback
            pass

    # Fallback to raw SQL if adapter not used
    if not adapter_used:
        with connection() as conn:
            conn.execute(
                """
                INSERT INTO herd.decision_record
                  (decision_id, decision_type, context, decision, rationale,
                   alternatives_considered, decided_by, ticket_code, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [
                    decision_id,
                    decision_type,
                    context,
                    decision,
                    rationale,
                    alternatives_considered,
                    agent_name,
                    ticket_code,
                ],
            )

    # Format decision text for Slack
    decision_text = f"**Type**: {decision_type}\n**Decision**: {decision}\n**Rationale**: {rationale}"
    if alternatives_considered:
        decision_text += f"\n**Alternatives**: {alternatives_considered}"

    # Post to Slack - use adapter if available
    if registry and registry.notify:
        try:
            # Format message with ticket link if available
            if ticket_code:
                message = f"{agent_name} decision on <https://linear.app/dbt-conceptual/issue/{ticket_code}|{ticket_code}>:\n{decision_text}"
            else:
                message = f"{agent_name} decision:\n{decision_text}"

            await registry.notify.post(
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
        "posted_to_slack": slack_result.get("success", False),
        "agent": agent_name,
        "ticket_code": ticket_code,
        "slack_response": slack_result if not slack_result.get("success") else None,
    }
