"""Slack logging tool implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from typing import TYPE_CHECKING, Any, cast

from herd_core.types import AgentRecord, AgentState, LifecycleEvent

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry

logger = logging.getLogger(__name__)


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
    token = os.getenv("HERD_NOTIFY_SLACK_TOKEN")
    if not token:
        return {"success": False, "error": "HERD_NOTIFY_SLACK_TOKEN not set"}

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

    if not registry or not registry.store:
        return {"error": "StoreAdapter not configured"}

    store = registry.store

    # Find active instance for this agent
    instances = store.list(AgentRecord, agent=agent_name, active=True)
    for inst in instances:
        if inst.state in (AgentState.RUNNING, AgentState.SPAWNING):
            agent_instance_code = inst.id
            break

    # Append lifecycle event
    if agent_instance_code:
        async with registry.write_lock:
            store.append(
                LifecycleEvent(
                    entity_id=agent_instance_code,
                    event_type=event_type,
                    instance_id=agent_instance_code,
                    detail=message,
                )
            )

    # Auto-shadow to KuzuDB graph (only for pr_submitted events)
    if event_type == "pr_submitted":
        try:
            from herd_mcp.graph import merge_node

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
        except ImportError:
            pass  # KuzuDB not installed
        except Exception:
            logger.warning("Failed to auto-shadow log to graph", exc_info=True)

    # Post to Slack - use adapter if available, otherwise fall back to inline
    if registry.notify:
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
        posted = bool(slack_result.get("success", False))

    responses: list[dict[str, Any]] = []
    if posted and await_response:
        # Extract thread info from Slack response
        slack_response = cast(dict[str, Any], slack_result.get("response", {}))
        thread_ts = cast(str | None, slack_response.get("ts"))
        channel_id = cast(str | None, slack_response.get("channel"))
        token = os.getenv("HERD_NOTIFY_SLACK_TOKEN")

        if thread_ts and channel_id and token:
            # Poll for replies (24 iterations * 5 seconds = 120 seconds)
            for _ in range(24):
                await asyncio.sleep(5)

                # Use adapter if available
                if registry.notify:
                    try:
                        thread_messages = registry.notify.get_thread_replies(
                            channel=channel_id,
                            thread_id=thread_ts,
                        )
                        responses = [
                            {
                                "user": msg.author,
                                "text": msg.text,
                                "ts": msg.timestamp,
                            }
                            for msg in thread_messages
                        ]
                        if responses:
                            break
                    except Exception:
                        responses = []
                else:
                    replies = _get_thread_replies(channel_id, thread_ts, token)
                    responses = [
                        {
                            "user": cast(str, reply.get("user", "unknown")),
                            "text": cast(str, reply.get("text", "")),
                            "ts": cast(str, reply.get("ts", "")),
                        }
                        for reply in replies
                    ]
                    if replies:
                        break

    return {
        "posted": posted,
        "event_id": event_id if posted else None,
        "responses": responses,
        "agent": agent_name,
        "event_type": event_type,
        "slack_response": slack_result if not posted else None,
    }
