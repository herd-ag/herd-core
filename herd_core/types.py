"""Shared data types for Herd adapter interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# --- Agent types ---


class AgentState(Enum):
    """Lifecycle states for an agent instance."""

    SPAWNING = "spawning"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass(frozen=True)
class SpawnContext:
    """Everything an agent needs to start working.

    Context completeness is a core Herd principle — agents must never
    be spawned with partial context. Every field here must be populated
    before calling AgentAdapter.spawn().
    """

    role_definition: str
    craft_standards: str
    project_guidelines: str
    assignment: str
    environment: dict[str, str] = field(default_factory=dict)
    skills: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SpawnResult:
    """Returned by AgentAdapter.spawn()."""

    instance_id: str
    agent: str
    ticket_id: str
    model: str
    worktree: str
    branch: str
    spawned_at: datetime


@dataclass(frozen=True)
class AgentStatus:
    """Current state of a running agent instance."""

    instance_id: str
    agent: str
    state: AgentState
    ticket_id: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


# --- Ticket types ---


class TicketPriority(Enum):
    """Ticket priority levels."""

    NONE = 0
    URGENT = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4


@dataclass(frozen=True)
class TicketState:
    """Snapshot of a ticket's current state."""

    ticket_id: str
    title: str
    status: str
    priority: TicketPriority = TicketPriority.NONE
    description: str | None = None
    assignee: str | None = None
    project: str | None = None
    labels: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    modified_at: datetime | None = None


@dataclass(frozen=True)
class TransitionResult:
    """Returned by TicketAdapter.transition()."""

    ticket_id: str
    previous_status: str
    new_status: str
    event_type: str
    elapsed_minutes: float | None = None


# --- Repository types ---


@dataclass(frozen=True)
class PRState:
    """Snapshot of a pull request's current state."""

    pr_id: str
    title: str
    branch: str
    base: str
    status: str
    lines_added: int = 0
    lines_deleted: int = 0
    files_changed: int = 0
    url: str | None = None
    merged_at: datetime | None = None


# --- Notification types ---


@dataclass(frozen=True)
class PostResult:
    """Returned by NotifyAdapter.post()."""

    message_id: str
    channel: str
    timestamp: str


@dataclass(frozen=True)
class ThreadMessage:
    """A single message in a notification thread."""

    author: str
    text: str
    timestamp: str


# --- Store types ---


@dataclass(frozen=True)
class QueryResult:
    """Result of a store query operation."""

    rows: list[dict[str, Any]]
    row_count: int
