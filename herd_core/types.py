"""Shared data types for Herd adapter interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


# ============================================================
# Base classes — the ORM-like foundation
# ============================================================


@dataclass
class Entity:
    """Base class for all persistable domain records.

    Entities have identity (an id field), can be saved and retrieved,
    and support soft deletes. Subclass this for any record that the
    StoreAdapter can get/list/save.
    """

    id: str
    created_at: datetime | None = None
    modified_at: datetime | None = None
    deleted_at: datetime | None = None


@dataclass(frozen=True)
class Event:
    """Base class for all append-only activity ledger records.

    Events are immutable — once appended, never updated or deleted.
    This is the audit trail. Subclass this for any activity record
    that the StoreAdapter can append.
    """

    entity_id: str
    event_type: str
    created_at: datetime | None = None


# ============================================================
# Enums
# ============================================================


class AgentState(Enum):
    """Lifecycle states for an agent instance."""

    SPAWNING = "spawning"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class TicketPriority(Enum):
    """Ticket priority levels."""

    NONE = 0
    URGENT = 1
    HIGH = 2
    NORMAL = 3
    LOW = 4


# ============================================================
# Entities — mutable, saveable domain records
# ============================================================


@dataclass
class AgentRecord(Entity):
    """An agent instance — one execution of a role on a ticket."""

    agent: str = ""
    model: str = ""
    ticket_id: str | None = None
    state: AgentState = AgentState.SPAWNING
    worktree: str | None = None
    branch: str | None = None
    spawned_by: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None


@dataclass
class TicketRecord(Entity):
    """A ticket in the project management system."""

    title: str = ""
    description: str | None = None
    status: str = ""
    priority: TicketPriority = TicketPriority.NONE
    project: str | None = None
    assignee: str | None = None
    labels: list[str] = field(default_factory=list)
    acceptance_criteria: str | None = None


@dataclass
class PRRecord(Entity):
    """A pull request in the repository system."""

    ticket_id: str | None = None
    title: str = ""
    branch: str = ""
    base: str = "main"
    status: str = ""
    creator_instance_id: str | None = None
    lines_added: int = 0
    lines_deleted: int = 0
    files_changed: int = 0
    url: str | None = None
    merged_at: datetime | None = None
    closed_at: datetime | None = None


@dataclass
class DecisionRecord(Entity):
    """A Herd Decision Record (HDR) or agent decision record."""

    title: str = ""
    body: str = ""
    decision_maker: str = ""
    principle: str | None = None
    scope: str | None = None
    status: str = "accepted"


@dataclass
class ReviewRecord(Entity):
    """A QA review of a pull request."""

    pr_id: str = ""
    ticket_id: str | None = None
    reviewer_instance_id: str | None = None
    verdict: str = ""
    body: str = ""
    findings_count: int = 0


@dataclass
class ModelRecord(Entity):
    """An AI model definition with pricing."""

    name: str = ""
    provider: str = ""
    input_cost_per_token: Decimal = Decimal("0")
    output_cost_per_token: Decimal = Decimal("0")
    context_window: int = 0
    target_role: str | None = None


@dataclass
class SprintRecord(Entity):
    """A sprint/cycle in the project management system."""

    name: str = ""
    number: int = 0
    status: str = ""
    started_at: datetime | None = None
    ended_at: datetime | None = None
    goal: str | None = None


# ============================================================
# Events — immutable, append-only activity ledger records
# ============================================================


@dataclass(frozen=True)
class LifecycleEvent(Event):
    """Agent lifecycle activity (spawned, started, blocked, completed, etc.)."""

    instance_id: str = ""
    detail: str = ""


@dataclass(frozen=True)
class TicketEvent(Event):
    """Ticket state change activity."""

    instance_id: str = ""
    previous_status: str = ""
    new_status: str = ""
    elapsed_minutes: float | None = None
    note: str | None = None
    blocked_by: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PREvent(Event):
    """Pull request activity (created, committed, pushed, merged, closed)."""

    instance_id: str = ""
    pr_id: str = ""
    commit_hash: str | None = None
    lines_added: int = 0
    lines_deleted: int = 0
    detail: str = ""


@dataclass(frozen=True)
class ReviewEvent(Event):
    """QA review activity."""

    instance_id: str = ""
    review_id: str = ""
    pr_id: str = ""
    verdict: str = ""
    detail: str = ""


@dataclass(frozen=True)
class TokenEvent(Event):
    """Token usage and cost tracking."""

    instance_id: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    context_utilization: Decimal = Decimal("0")


# ============================================================
# Adapter-specific return types (not entities/events)
# ============================================================


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
class TransitionResult:
    """Returned by TicketAdapter.transition()."""

    ticket_id: str
    previous_status: str
    new_status: str
    event_type: str
    elapsed_minutes: float | None = None


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


@dataclass(frozen=True)
class CommitInfo:
    """A git commit from RepoAdapter.get_log()."""

    sha: str
    message: str
    author: str
    timestamp: datetime
    branch: str | None = None
