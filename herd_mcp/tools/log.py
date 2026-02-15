"""Slack logging tool implementation."""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from typing import TYPE_CHECKING, Any

from herd_mcp.db import connection

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry


def _classify_event_type(message: str) -> str:
    """Classify the lifecycle event type based on message content.

    Args:
        message: Message content to classify.

    Returns:
        Event type string (pr_submitted, review_complete, blocked, work_started,
        code_pushed, or status_update).
    """
    message_lower = message.lower()

    # Use word boundaries and more specific patterns
    if re.search(r"\bpr\b|pull request|pull-request", message_lower):
        return "pr_submitted"
    elif "review" in message_lower or "qa" in message_lower:
        return "review_complete"
    elif "blocked" in message_lower:
        return "blocked"
    elif "started" in message_lower or "beginning" in message_lower:
        return "work_started"
    elif "commit" in message_lower or "pushed" in message_lower:
        return "code_pushed"
    else:
        return "status_update"


def _get_thread_replies(
    channel_id: str, thread_ts: str, token: str
) -> list[dict[str, Any]]:
    """Get thread replies from Slack using urllib.

    Args:
        channel_id: Slack channel ID.
        thread_ts: Thread timestamp.
        token: Slack API token.

    Returns:
        List of reply messages (excluding parent message).
    """
    try:
        import urllib.parse
        import urllib.request

        params = urllib.parse.urlencode({"channel": channel_id, "ts": thread_ts})
        url = f"https://slack.com/api/conversations.replies?{params}"

        req = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}"},
        )

        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())

        if result.get("ok", False):
            messages = result.get("messages", [])
            # Filter out the parent message (first message)
            return messages[1:] if len(messages) > 1 else []

        return []
    except Exception:
        return []


def _post_to_slack(message: str, channel: str, agent_name: str) -> dict[str, Any]:
    """Post message to Slack using urllib (no external deps).

    Args:
        message: Message to post.
        channel: Slack channel (with # prefix).
        agent_name: Agent name for display.

    Returns:
        Dict with success status and response data.
    """
    token = os.getenv("HERD_SLACK_TOKEN")
    if not token:
        return {"success": False, "error": "HERD_SLACK_TOKEN not set"}

    try:
        import urllib.request

        data = json.dumps(
            {
                "channel": channel,
                "text": message,
                "username": agent_name,
                "icon_emoji": ":hammer:",
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
    message: str,
    channel: str | None,
    await_response: bool,
    agent_name: str | None,
    registry: AdapterRegistry | None = None,
) -> dict:
    """Post a message to Slack and log the activity.

    Args:
        message: Message content to post.
        channel: Optional Slack channel.
        await_response: If True, wait for thread responses.
        agent_name: Current agent identity.
        registry: Optional adapter registry for dependency injection.

    Returns:
        Dict with posted timestamp, event_id, and optional responses.
    """
    # Set defaults
    agent_name = agent_name or "Unknown Agent"
    channel = channel or "#herd-feed"

    # Classify event type
    event_type = _classify_event_type(message)

    # Generate event ID
    event_id = str(uuid.uuid4())

    # Resolve agent identity and get current instance
    agent_instance_code = None

    # Adapter path (for simple CRUD operations)
    if registry and registry.store:
        try:
            from herd_core.entities import AgentRecord, LifecycleEvent

            # List active instances for this agent
            instances = registry.store.list(
                AgentRecord, agent_code=agent_name, ended_at=None
            )

            if instances:
                agent_instance_code = instances[0].instance_code

                # Append lifecycle event
                lifecycle_event = LifecycleEvent(
                    agent_instance_code=agent_instance_code,
                    event_type=event_type,
                    detail=message,
                )
                registry.store.append(lifecycle_event)
        except Exception:
            # Fall through to SQL fallback
            pass

    # Fallback to raw SQL if adapter not available or failed
    if agent_instance_code is None:
        with connection() as conn:
            # Look up current agent instance
            result = conn.execute(
                """
                SELECT ai.agent_instance_code
                FROM herd.agent_instance ai
                WHERE ai.agent_code = ?
                  AND ai.agent_instance_ended_at IS NULL
                ORDER BY ai.agent_instance_started_at DESC
                LIMIT 1
                """,
                [agent_name],
            ).fetchone()

            if result:
                agent_instance_code = result[0]

                # Record to lifecycle activity
                conn.execute(
                    """
                    INSERT INTO herd.agent_instance_lifecycle_activity
                      (agent_instance_code, lifecycle_event_type, lifecycle_detail, created_at)
                    VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    [agent_instance_code, event_type, message],
                )

    # Post to Slack - use adapter if available, otherwise fall back to inline
    if registry and registry.notify:
        # Use adapter protocol
        try:
            post_result = registry.notify.post(
                message=message,
                channel=channel,
                username=agent_name,
            )
            posted = True
            slack_result = {"success": True, "response": post_result}
        except Exception as e:
            posted = False
            slack_result = {"success": False, "error": str(e)}
    else:
        # Fall back to inline implementation
        slack_result = _post_to_slack(message, channel, agent_name)
        posted = slack_result.get("success", False)

    responses = []
    if posted and await_response:
        # Extract thread info from Slack response
        slack_response = slack_result.get("response", {})
        thread_ts = slack_response.get("ts")
        channel_id = slack_response.get("channel")
        token = os.getenv("HERD_SLACK_TOKEN")

        if thread_ts and channel_id and token:
            # Poll for replies (24 iterations * 5 seconds = 120 seconds)
            for _ in range(24):
                await asyncio.sleep(5)

                # Use adapter if available
                if registry and registry.notify:
                    try:
                        replies = registry.notify.get_thread_replies(
                            channel=channel_id,
                            thread_ts=thread_ts,
                        )
                    except Exception:
                        replies = []
                else:
                    replies = _get_thread_replies(channel_id, thread_ts, token)

                if replies:
                    responses = [
                        {
                            "user": reply.get("user", "unknown"),
                            "text": reply.get("text", ""),
                            "ts": reply.get("ts", ""),
                        }
                        for reply in replies
                    ]
                    break

    return {
        "posted": posted,
        "event_id": event_id if posted else None,
        "responses": responses,
        "agent": agent_name,
        "event_type": event_type,
        "slack_response": slack_result if not posted else None,
    }
