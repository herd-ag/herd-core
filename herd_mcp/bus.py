"""In-memory message bus for agent-to-agent communication.

Provides addressed message routing with support for direct, broadcast,
and competing-consumer delivery patterns. Lives inside the MCP server
process — cross-host delivery happens transparently via HTTP transport.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

logger = logging.getLogger(__name__)

# Agents that cannot consume @anyone messages (mechanical workers).
MECHANICAL_AGENTS: frozenset[str] = frozenset({"rook", "vigil"})

# Agents with leader visibility (see all @team traffic for their team).
LEADER_AGENTS: frozenset[str] = frozenset({"steve", "leonardo"})

# Maximum message age before automatic pruning.
MAX_MESSAGE_AGE = timedelta(hours=1)


@dataclass
class Message:
    """A single message on the bus.

    Attributes:
        id: Unique message identifier (UUID).
        from_addr: Sender address (e.g. mason.inst-a3f7@avalon).
        to_addr: Recipient address (e.g. mason@avalon, @anyone, @everyone).
        body: Free-text message body.
        type: Message type — "directive", "inform", or "flag".
        priority: Message priority — "normal" or "urgent".
        sent_at: UTC timestamp when the message was sent.
        read_by: Set of instance IDs that have consumed this message.
    """

    id: str
    from_addr: str
    to_addr: str
    body: str
    type: str = "inform"
    priority: str = "normal"
    sent_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    read_by: set[str] = field(default_factory=set)


class ParsedAddress(NamedTuple):
    """Parsed components of a message address.

    Attributes:
        agent: Agent code (e.g. "mason") or broadcast token ("@anyone", "@everyone").
        instance: Instance ID if specified, otherwise None.
        team: Team scope if specified, otherwise None.
    """

    agent: str
    instance: str | None
    team: str | None


def parse_address(addr: str) -> ParsedAddress:
    """Parse an address string into its agent, instance, and team components.

    Supported formats:
        mason                    -> agent=mason, instance=None, team=None
        mason@avalon             -> agent=mason, instance=None, team=avalon
        mason.inst-abc@avalon    -> agent=mason, instance=inst-abc, team=avalon
        @anyone                  -> agent=@anyone, instance=None, team=None
        @anyone@avalon           -> agent=@anyone, instance=None, team=avalon
        @everyone                -> agent=@everyone, instance=None, team=None
        @everyone@avalon         -> agent=@everyone, instance=None, team=avalon

    Args:
        addr: Address string to parse.

    Returns:
        ParsedAddress with agent, instance, and team fields.
    """
    team: str | None = None
    instance: str | None = None

    # Handle broadcast addresses that start with @
    if addr.startswith("@"):
        # Could be @anyone, @anyone@avalon, @everyone, @everyone@avalon
        # Split on @ — first element is empty string, second is keyword,
        # optional third is team.
        parts = addr.split("@")
        # parts[0] is always "" (before first @)
        # parts[1] is the keyword (anyone/everyone)
        # parts[2] if present is the team
        agent = f"@{parts[1]}"
        if len(parts) >= 3 and parts[2]:
            team = parts[2]
        return ParsedAddress(agent=agent, instance=instance, team=team)

    # Non-broadcast: split on @ for team
    if "@" in addr:
        local_part, team = addr.split("@", 1)
    else:
        local_part = addr

    # Split local part on . for instance
    if "." in local_part:
        agent, instance = local_part.split(".", 1)
    else:
        agent = local_part

    return ParsedAddress(agent=agent, instance=instance, team=team)


class MessageBus:
    """In-memory message bus. Lives inside the MCP server process.

    Thread-safe via asyncio.Lock. Supports direct, broadcast (@everyone),
    and competing-consumer (@anyone) delivery patterns with team scoping
    and leader visibility.
    """

    def __init__(self) -> None:
        self._messages: list[Message] = []
        self._lock: asyncio.Lock = asyncio.Lock()

    async def send(
        self,
        from_addr: str,
        to_addr: str,
        body: str,
        msg_type: str = "inform",
        priority: str = "normal",
    ) -> Message:
        """Send a message to an address.

        Args:
            from_addr: Sender address string.
            to_addr: Recipient address string.
            body: Message body text.
            msg_type: Message type — "directive", "inform", or "flag".
            priority: "normal" or "urgent".

        Returns:
            The created Message object.
        """
        msg = Message(
            id=uuid.uuid4().hex,
            from_addr=from_addr,
            to_addr=to_addr,
            body=body,
            type=msg_type,
            priority=priority,
        )
        async with self._lock:
            self._messages.append(msg)
        logger.info(
            "Message %s sent from %s to %s (priority=%s)",
            msg.id, from_addr, to_addr, priority,
        )
        return msg

    async def read(
        self,
        agent: str,
        instance: str | None = None,
        team: str | None = None,
    ) -> list[Message]:
        """Read and consume messages matching the caller's identity.

        For @anyone messages, the first qualifying agent to read consumes it.
        For @everyone messages, the message is tracked via read_by and only
        removed when all active agents have read it (or it expires).

        Args:
            agent: Agent code of the reader (e.g. "mason").
            instance: Instance ID of the reader (e.g. "inst-a3f7b2c1").
            team: Team of the reader (e.g. "avalon").

        Returns:
            List of matching Message objects (consumed from the bus).
        """
        matched: list[Message] = []
        async with self._lock:
            self._prune_expired()
            remaining: list[Message] = []
            for msg in self._messages:
                match_result = self._match(msg, agent, instance, team)
                if match_result:
                    parsed = parse_address(msg.to_addr)
                    if parsed.agent == "@everyone":
                        # Track reader, return message but keep it on the bus
                        inst_key = instance or agent
                        if inst_key not in msg.read_by:
                            msg.read_by.add(inst_key)
                            matched.append(msg)
                        remaining.append(msg)
                    elif parsed.agent == "@anyone":
                        # Competing consumer — first reader takes it
                        matched.append(msg)
                        # Do NOT add to remaining — consumed
                    else:
                        # Direct message — consume it
                        matched.append(msg)
                        # Do NOT add to remaining — consumed
                else:
                    remaining.append(msg)
            self._messages = remaining
        return matched

    def _match(
        self,
        message: Message,
        agent: str,
        instance: str | None,
        team: str | None,
    ) -> bool:
        """Check whether a message matches the reader's identity.

        Matching rules:
        - Direct agent: agent name matches.
        - With team: agent AND team match.
        - With instance: exact instance match.
        - @anyone: first non-mechanical agent to read consumes it.
        - @everyone: all agents get it, tracked via read_by set.
        - Leader visibility: leaders see all @team traffic for their team.

        Args:
            message: The message to check.
            agent: Reader's agent code.
            instance: Reader's instance ID.
            team: Reader's team.

        Returns:
            True if the message matches the reader.
        """
        parsed = parse_address(message.to_addr)

        # @everyone broadcast
        if parsed.agent == "@everyone":
            if parsed.team is None:
                return True
            return team == parsed.team

        # @anyone competing consumer
        if parsed.agent == "@anyone":
            if agent in MECHANICAL_AGENTS:
                return False
            if parsed.team is not None and team != parsed.team:
                return False
            return True

        # Instance-specific: exact match required
        if parsed.instance is not None:
            return instance == parsed.instance

        # Agent-level with team
        if parsed.team is not None:
            if parsed.agent == agent and team == parsed.team:
                return True
            # Leader visibility: leaders see all team-scoped messages
            if agent in LEADER_AGENTS and team == parsed.team:
                return True
            return False

        # Agent-level without team
        return parsed.agent == agent

    def _prune_expired(self) -> None:
        """Remove messages older than MAX_MESSAGE_AGE.

        Called under the lock from read(). No separate scheduling needed.
        """
        cutoff = datetime.now(UTC) - MAX_MESSAGE_AGE
        before = len(self._messages)
        self._messages = [m for m in self._messages if m.sent_at > cutoff]
        pruned = before - len(self._messages)
        if pruned:
            logger.info("Pruned %d expired messages", pruned)


# ---------------------------------------------------------------------------
# Checkin registry — in-memory heartbeat and status tracking
# ---------------------------------------------------------------------------

# Unresponsive threshold: agents not heard from in 10 minutes.
UNRESPONSIVE_THRESHOLD = timedelta(seconds=600)

# Stale threshold: agents not heard from in 5 minutes.
STALE_THRESHOLD = timedelta(seconds=300)


@dataclass
class CheckinEntry:
    """Latest checkin state for one agent instance.

    Attributes:
        status: Brief status text from the agent.
        timestamp: UTC time of the last checkin.
        ticket: Optional ticket the agent is working on.
        agent: Agent code (e.g. "mason").
        team: Team the agent belongs to (e.g. "avalon").
    """

    status: str
    timestamp: datetime
    ticket: str | None = None
    agent: str = ""
    team: str = ""


class CheckinRegistry:
    """In-memory registry of agent checkin state.

    Thread-safe via asyncio.Lock. Used by the herd_checkin tool to record
    heartbeats and build context panes showing who is active.
    """

    def __init__(self) -> None:
        self._entries: dict[str, CheckinEntry] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    async def record(
        self,
        address: str,
        status: str,
        agent: str,
        team: str,
        ticket: str | None = None,
    ) -> None:
        """Record a checkin heartbeat.

        Args:
            address: Agent instance address string.
            status: Brief status text.
            agent: Agent code.
            team: Team identifier.
            ticket: Optional ticket ID the agent is working on.
        """
        async with self._lock:
            self._entries[address] = CheckinEntry(
                status=status,
                timestamp=datetime.now(UTC),
                ticket=ticket,
                agent=agent,
                team=team,
            )

    def get_active(self, team: str | None = None) -> dict[str, CheckinEntry]:
        """Get all active checkin entries, optionally filtered by team.

        Args:
            team: Optional team to filter by.

        Returns:
            Dict of address to CheckinEntry for agents checked in
            within the unresponsive threshold.
        """
        cutoff = datetime.now(UTC) - UNRESPONSIVE_THRESHOLD
        result: dict[str, CheckinEntry] = {}
        for addr, entry in self._entries.items():
            if entry.timestamp > cutoff:
                if team is None or entry.team == team:
                    result[addr] = entry
        return result

    def staleness(self, address: str) -> str | None:
        """Return staleness label or None if active.

        Args:
            address: Agent instance address string.

        Returns:
            "unresponsive" if past 10 minutes, "stale" if past 5 minutes,
            or None if the agent is active.
        """
        entry = self._entries.get(address)
        if not entry:
            return None
        age = (datetime.now(UTC) - entry.timestamp).total_seconds()
        if age > UNRESPONSIVE_THRESHOLD.total_seconds():
            return "unresponsive"
        elif age > STALE_THRESHOLD.total_seconds():
            return "stale"
        return None
