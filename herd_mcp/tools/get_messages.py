"""Herd get_messages tool — pure inbox drain for pending bus messages.

Reads and returns all pending messages for the calling agent from the
message bus. No heartbeat, no context pane — just the messages.

Messages are consumed (removed from the bus) on read.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from herd_mcp.bus import MessageBus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier configuration (mirrors checkin.py for consistent filtering)
# ---------------------------------------------------------------------------

LEADER_AGENTS: frozenset[str] = frozenset({"steve", "leonardo"})
SENIOR_AGENTS: frozenset[str] = frozenset({"wardenstein", "scribe", "tufte"})
MECHANICAL_AGENTS: frozenset[str] = frozenset({"rook", "vigil"})

TIER_MESSAGE_TYPES: dict[str, set[str]] = {
    "leader": {"directive", "inform", "flag"},
    "senior": {"directive", "inform", "flag"},
    "execution": {"directive", "inform", "flag"},
    "mechanical": {"directive"},
}


def _get_tier(agent: str) -> str:
    """Determine the agent's tier from its code.

    Args:
        agent: Agent code (e.g. "mason", "steve").

    Returns:
        Tier string: "leader", "senior", "mechanical", or "execution".
    """
    if agent in LEADER_AGENTS:
        return "leader"
    if agent in SENIOR_AGENTS:
        return "senior"
    if agent in MECHANICAL_AGENTS:
        return "mechanical"
    return "execution"


async def execute(
    agent_name: str | None,
    *,
    bus: MessageBus | None = None,
) -> dict[str, str | list[dict[str, str]] | int]:
    """Read and return all pending messages for the calling agent.

    Drains the message bus for the resolved agent identity. Messages are
    consumed on read (removed from the bus for direct and @anyone messages,
    marked as read for @everyone broadcasts).

    Mechanical agents (rook, vigil) only receive directive-type messages.

    Args:
        agent_name: Calling agent identity. Falls back to HERD_AGENT_NAME.
        bus: Message bus instance (injected from server module).

    Returns:
        Dict with agent identity, list of message dicts, and count.
    """
    agent = agent_name or os.getenv("HERD_AGENT_NAME") or "unknown"
    instance = os.getenv("HERD_INSTANCE_ID") or None
    team = os.getenv("HERD_TEAM") or None

    if bus is None:
        logger.warning(
            "herd_get_messages called without bus instance for agent=%s", agent
        )
        return {"agent": agent, "messages": [], "count": 0}

    raw_messages = await bus.read(agent, instance, team)

    # Apply tier-based filtering
    tier = _get_tier(agent)
    allowed_types = TIER_MESSAGE_TYPES[tier]

    messages: list[dict[str, str]] = []
    for msg in raw_messages:
        if msg.type in allowed_types:
            messages.append(
                {
                    "id": msg.id,
                    "from": msg.from_addr,
                    "to": msg.to_addr,
                    "type": msg.type,
                    "priority": msg.priority,
                    "body": msg.body,
                    "sent_at": msg.sent_at.isoformat(),
                }
            )

    return {"agent": agent, "messages": messages, "count": len(messages)}
