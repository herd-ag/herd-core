"""Herd checkin tool — unified pull-based message delivery and context pane.

Replaces piggyback message delivery with a single pull-based tool that agents
call at natural transition points. Returns pending messages, a context pane
showing relevant Herd activity, and acknowledges the heartbeat.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from herd_mcp.bus import CheckinRegistry

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry
    from herd_mcp.bus import Message, MessageBus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tier configuration
# ---------------------------------------------------------------------------

LEADER_AGENTS: frozenset[str] = frozenset({"steve", "leonardo"})
SENIOR_AGENTS: frozenset[str] = frozenset({"wardenstein", "scribe", "tufte"})
MECHANICAL_AGENTS: frozenset[str] = frozenset({"rook", "vigil"})
# Execution agents = everything else (mason, fresco, gauss, etc.)

TIER_CONFIG: dict[str, dict] = {
    "leader": {"context_budget": 500, "message_types": {"directive", "inform", "flag"}},
    "senior": {"context_budget": 300, "message_types": {"directive", "inform", "flag"}},
    "execution": {
        "context_budget": 200,
        "message_types": {"directive", "inform", "flag"},
    },
    "mechanical": {"context_budget": 0, "message_types": {"directive"}},
}


def _get_tier(agent: str) -> str:
    """Determine the agent's tier.

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


def _build_context_pane(
    agent: str,
    team: str | None,
    ticket: str | None,
    budget: int,
    checkin_registry: CheckinRegistry,
) -> str | None:
    """Build compressed context pane for this agent.

    Shows what other agents on the same team (or structurally connected
    via KuzuDB) are doing. Budget is in approximate tokens.

    Args:
        agent: The calling agent's code.
        team: The calling agent's team.
        ticket: The calling agent's current ticket.
        budget: Maximum token budget for the pane.
        checkin_registry: Registry of active agent checkins.

    Returns:
        Context pane string, or None if nothing to show.
    """
    if budget <= 0:
        return None

    # Get active agents on the same team
    active = checkin_registry.get_active(team=team)
    if not active:
        return None

    # Try KuzuDB for structural filtering (graceful fallback)
    connected_agents: set[str] | None = None
    try:
        from herd_mcp.graph import is_available, query_graph

        if is_available() and ticket:
            # Find agents connected via ticket dependencies
            results = query_graph(
                "MATCH (a:Agent)-[:AssignedTo]->(t:Ticket) "
                "WHERE t.id = $ticket "
                "RETURN a.code",
                {"ticket": ticket},
            )
            connected_agents = {r["a.code"] for r in results}
    except Exception:
        pass  # Graph not available, use team-based filtering

    # Build pane text
    lines: list[str] = []
    for addr, entry in active.items():
        # Skip self
        if entry.agent == agent:
            continue
        # If we have graph data, filter to connected agents only
        if connected_agents is not None and entry.agent not in connected_agents:
            continue
        staleness = checkin_registry.staleness(addr)
        stale_tag = f" ({staleness})" if staleness else ""
        line = f"{addr}{stale_tag}: {entry.status}"
        lines.append(line)

    if not lines:
        return None

    pane = ". ".join(lines) + f". {len(active)} agents active."
    # Rough budget enforcement (4 chars ~ 1 token)
    max_chars = budget * 4
    if len(pane) > max_chars:
        pane = pane[: max_chars - 3] + "..."
    return pane


def _filter_messages_by_tier(
    messages: list[Message],
    tier: str,
) -> list[dict]:
    """Filter and format messages based on agent tier.

    Mechanical agents only receive directive messages. All other tiers
    receive all message types.

    Args:
        messages: Raw messages from the bus.
        tier: Agent tier string.

    Returns:
        List of message dicts suitable for the response.
    """
    allowed_types = TIER_CONFIG[tier]["message_types"]
    result: list[dict] = []
    for m in messages:
        if m.type in allowed_types:
            result.append(
                {
                    "from": m.from_addr,
                    "type": m.type,
                    "body": m.body,
                    "priority": m.priority,
                }
            )
    return result


async def execute(
    status_text: str,
    agent_name: str | None,
    registry: AdapterRegistry | None = None,
    *,
    bus: MessageBus | None = None,
    checkin_registry: CheckinRegistry | None = None,
) -> dict:
    """Execute the herd_checkin tool.

    Records a heartbeat, drains pending messages, and builds a context pane
    for the calling agent.

    Args:
        status_text: Brief status update from the agent.
        agent_name: Calling agent identity.
        registry: Adapter registry (unused directly, but passed for consistency).
        bus: Message bus instance (injected from server module).
        checkin_registry: Checkin registry instance (injected from server module).

    Returns:
        Dict with messages (list), context (str or null), and heartbeat_ack.
    """
    # Resolve identity
    agent = agent_name or os.getenv("HERD_AGENT_NAME") or "unknown"
    instance = os.getenv("HERD_INSTANCE_ID", "")
    team = os.getenv("HERD_TEAM", "")

    # Build agent address
    addr_parts = agent
    if instance:
        addr_parts = f"{agent}.{instance}"
    if team:
        addr_parts = f"{addr_parts}@{team}"

    # Determine tier
    tier = _get_tier(agent)
    config = TIER_CONFIG[tier]
    context_budget: int = config["context_budget"]

    # Record heartbeat
    if checkin_registry is not None:
        # Resolve current ticket from environment or store
        ticket = os.getenv("HERD_TICKET_ID")
        await checkin_registry.record(
            address=addr_parts,
            status=status_text,
            agent=agent,
            team=team,
            ticket=ticket,
        )

    # Drain pending messages
    messages: list[dict] = []
    if bus is not None:
        raw_messages = await bus.read(agent, instance or None, team or None)
        messages = _filter_messages_by_tier(raw_messages, tier)

    # Build context pane
    context: str | None = None
    if checkin_registry is not None and context_budget > 0:
        ticket = os.getenv("HERD_TICKET_ID")
        context = _build_context_pane(
            agent=agent,
            team=team or None,
            ticket=ticket,
            budget=context_budget,
            checkin_registry=checkin_registry,
        )

    return {
        "messages": messages,
        "context": context,
        "heartbeat_ack": True,
    }
