"""Message bus for agent-to-agent communication with DiskCache persistence.

Provides addressed message routing with support for direct, broadcast,
and competing-consumer delivery patterns. Uses an in-memory hot cache for
same-session delivery and DiskCache Deque for persistence across restarts.

Storage path: $HERD_PROJECT_PATH/data/messages/ (default ~/herd/data/messages/).
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NamedTuple

import diskcache  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)

# Agents that cannot consume @anyone messages (mechanical workers).
MECHANICAL_AGENTS: frozenset[str] = frozenset({"rook", "vigil"})

# Agents with leader visibility (see all @team traffic for their team).
LEADER_AGENTS: frozenset[str] = frozenset({"steve", "leonardo"})

# Maximum message age before automatic pruning.
MAX_MESSAGE_AGE = timedelta(hours=1)


def _extract_read_by(raw: str | list[str] | datetime) -> set[str]:
    """Extract read_by set from deserialized data.

    Args:
        raw: Value from the serialized dict (expected to be list[str]).

    Returns:
        Set of reader instance IDs.
    """
    if isinstance(raw, list):
        return {item for item in raw if isinstance(item, str)}
    return set()


def _default_storage_path() -> Path:
    """Resolve the DiskCache storage directory for message queues.

    Uses HERD_PROJECT_PATH env var if set, otherwise falls back to ~/herd.
    Creates the directory tree if it does not exist.

    Returns:
        Path to the messages storage directory.
    """
    project_path = os.getenv("HERD_PROJECT_PATH", os.path.expanduser("~/herd"))
    path = Path(project_path) / "data" / "messages"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Message:
    """A single message on the bus.

    Attributes:
        id: Unique message identifier (UUID).
        from_addr: Sender address (e.g. mason.inst-a3f7@avalon).
        to_addr: Recipient address (e.g. mason@avalon, @anyone, @everyone).
        body: Free-text message body.
        type: Message type -- "directive", "inform", or "flag".
        priority: Message priority -- "normal" or "urgent".
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

    def to_dict(self) -> dict[str, str | list[str] | datetime]:
        """Serialize to a JSON-safe dict for DiskCache storage.

        Returns:
            Dict representation with ISO-formatted timestamp and list for read_by.
        """
        return {
            "id": self.id,
            "from_addr": self.from_addr,
            "to_addr": self.to_addr,
            "body": self.body,
            "type": self.type,
            "priority": self.priority,
            "sent_at": self.sent_at.isoformat(),
            "read_by": list(self.read_by),
        }

    @classmethod
    def from_dict(cls, data: dict[str, str | list[str] | datetime]) -> Message:
        """Deserialize from a dict (as stored in DiskCache).

        Args:
            data: Dict with message fields.

        Returns:
            Reconstructed Message instance.
        """
        raw_sent_at = data["sent_at"]
        sent_at: datetime
        if isinstance(raw_sent_at, str):
            sent_at = datetime.fromisoformat(raw_sent_at)
        elif isinstance(raw_sent_at, datetime):
            sent_at = raw_sent_at
        else:
            sent_at = datetime.now(UTC)
        return cls(
            id=str(data["id"]),
            from_addr=str(data["from_addr"]),
            to_addr=str(data["to_addr"]),
            body=str(data["body"]),
            type=str(data.get("type", "inform")),
            priority=str(data.get("priority", "normal")),
            sent_at=sent_at,
            read_by=_extract_read_by(data.get("read_by", [])),
        )


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
        parts = addr.split("@")
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
    """Message bus with in-memory hot cache and DiskCache persistence.

    In-memory list provides fast same-session delivery. DiskCache provides
    durability across MCP server restarts. Both layers are kept in sync:
    send writes to both, read consumes from both.

    Thread-safe via asyncio.Lock. Supports direct, broadcast (@everyone),
    and competing-consumer (@anyone) delivery patterns with team scoping
    and leader visibility.
    """

    def __init__(self, storage_path: Path | None = None) -> None:
        """Initialize the message bus.

        Args:
            storage_path: Override path for DiskCache storage.
                          Defaults to HERD_PROJECT_PATH/data/messages/.
        """
        self._messages: list[Message] = []
        self._lock: asyncio.Lock = asyncio.Lock()

        # Initialize DiskCache for persistence
        resolved_path = storage_path or _default_storage_path()
        self._disk: diskcache.Cache = diskcache.Cache(str(resolved_path))

        # Rehydrate in-memory cache from disk on startup
        self._rehydrate()

    def _rehydrate(self) -> None:
        """Load persisted messages from DiskCache into the in-memory list.

        Called once during __init__ to restore state after a restart.
        Prunes expired messages during rehydration.
        """
        cutoff = datetime.now(UTC) - MAX_MESSAGE_AGE
        restored = 0
        expired = 0

        for key in list(self._disk):
            try:
                data = self._disk[key]
                msg = Message.from_dict(data)
                if msg.sent_at > cutoff:
                    self._messages.append(msg)
                    restored += 1
                else:
                    del self._disk[key]
                    expired += 1
            except (KeyError, TypeError, ValueError) as exc:
                logger.warning(
                    "Skipping corrupt message %s during rehydration: %s", key, exc
                )
                try:
                    del self._disk[key]
                except KeyError:
                    pass

        if restored or expired:
            logger.info(
                "Rehydrated %d messages from disk (%d expired pruned)",
                restored,
                expired,
            )

    async def send(
        self,
        from_addr: str,
        to_addr: str,
        body: str,
        msg_type: str = "inform",
        priority: str = "normal",
    ) -> Message:
        """Send a message to an address.

        Writes to both the in-memory hot cache and DiskCache for persistence.

        Args:
            from_addr: Sender address string.
            to_addr: Recipient address string.
            body: Message body text.
            msg_type: Message type -- "directive", "inform", or "flag".
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
            self._disk[msg.id] = msg.to_dict()
        logger.info(
            "Message %s sent from %s to %s (priority=%s)",
            msg.id,
            from_addr,
            to_addr,
            priority,
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

        Consumed messages are removed from both the in-memory cache and DiskCache.

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
                        inst_key = instance or agent
                        if inst_key not in msg.read_by:
                            msg.read_by.add(inst_key)
                            matched.append(msg)
                            self._disk[msg.id] = msg.to_dict()
                        remaining.append(msg)
                    elif parsed.agent == "@anyone":
                        matched.append(msg)
                        self._disk.pop(msg.id, None)
                    else:
                        matched.append(msg)
                        self._disk.pop(msg.id, None)
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

        if parsed.agent == "@everyone":
            if parsed.team is None:
                return True
            return team == parsed.team

        if parsed.agent == "@anyone":
            if agent in MECHANICAL_AGENTS:
                return False
            if parsed.team is not None and team != parsed.team:
                return False
            return True

        if parsed.instance is not None:
            return instance == parsed.instance

        if parsed.team is not None:
            if parsed.agent == agent and team == parsed.team:
                return True
            if agent in LEADER_AGENTS and team == parsed.team:
                return True
            return False

        return parsed.agent == agent

    def _prune_expired(self) -> None:
        """Remove messages older than MAX_MESSAGE_AGE from memory and disk.

        Called under the lock from read(). No separate scheduling needed.
        """
        cutoff = datetime.now(UTC) - MAX_MESSAGE_AGE
        before = len(self._messages)
        pruned_ids: list[str] = []
        kept: list[Message] = []
        for m in self._messages:
            if m.sent_at > cutoff:
                kept.append(m)
            else:
                pruned_ids.append(m.id)
        self._messages = kept
        for msg_id in pruned_ids:
            self._disk.pop(msg_id, None)
        pruned = before - len(self._messages)
        if pruned:
            logger.info("Pruned %d expired messages", pruned)

    def close(self) -> None:
        """Close the DiskCache backend.

        Should be called during server shutdown for clean resource release.
        """
        self._disk.close()


# ---------------------------------------------------------------------------
# Checkin registry -- in-memory heartbeat and status tracking
# ---------------------------------------------------------------------------

UNRESPONSIVE_THRESHOLD = timedelta(seconds=600)
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
