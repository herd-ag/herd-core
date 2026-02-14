"""Operational query layer — the semantic layer over StoreAdapter.

Provides typed, named queries for operational analytics. Callers get
domain objects back, never raw dicts or SQL. The StoreAdapter handles
the actual data retrieval; this module composes the queries and types
the results.

Usage:
    queries = OperationalQueries(store)
    active = queries.active_agents()
    timeline = queries.ticket_timeline("DBC-120")
    costs = queries.cost_summary(since=last_monday)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from herd_core.adapters.store import StoreAdapter
from herd_core.types import (
    AgentRecord,
    AgentState,
    LifecycleEvent,
    PRRecord,
    ReviewRecord,
    SprintRecord,
    TicketEvent,
    TicketRecord,
    TokenEvent,
)


# ============================================================
# Query result types — domain-specific return values
# ============================================================


@dataclass(frozen=True)
class CostSummary:
    """Token cost summary for a period."""

    total_tokens: int
    total_cost_usd: Decimal
    by_agent: dict[str, Decimal]
    by_model: dict[str, Decimal]
    period_start: datetime | None = None
    period_end: datetime | None = None


@dataclass(frozen=True)
class TicketTimeline:
    """Full timeline of a ticket's lifecycle."""

    ticket: TicketRecord
    events: list[TicketEvent]
    total_elapsed_minutes: float


@dataclass(frozen=True)
class AgentPerformance:
    """Performance summary for an agent role."""

    agent: str
    tickets_completed: int
    avg_cycle_minutes: float
    total_cost_usd: Decimal
    review_pass_rate: float


@dataclass(frozen=True)
class ReviewSummary:
    """Review effectiveness summary."""

    total_reviews: int
    pass_rate: float
    avg_findings_per_review: float
    by_reviewer: dict[str, int]


# ============================================================
# Query class — composes StoreAdapter calls into typed results
# ============================================================


class OperationalQueries:
    """Semantic query layer over the operational store.

    All methods return typed domain objects. The underlying StoreAdapter
    handles data retrieval — this class composes and aggregates.
    """

    def __init__(self, store: StoreAdapter) -> None:
        self._store = store

    def active_agents(self) -> list[AgentRecord]:
        """All currently running agent instances."""
        return self._store.list(
            AgentRecord,
            state=AgentState.RUNNING,
            active=True,
        )

    def ticket_timeline(self, ticket_id: str) -> TicketTimeline | None:
        """Full lifecycle timeline for a ticket."""
        ticket = self._store.get(TicketRecord, ticket_id)
        if ticket is None:
            return None
        events = self._store.events(TicketEvent, entity_id=ticket_id)
        total = sum(
            e.elapsed_minutes for e in events if e.elapsed_minutes is not None
        )
        return TicketTimeline(
            ticket=ticket,
            events=events,  # type: ignore[arg-type]
            total_elapsed_minutes=total,
        )

    def cost_summary(
        self, *, since: datetime | None = None
    ) -> CostSummary:
        """Token cost summary, optionally filtered by period."""
        filters: dict[str, Any] = {}
        if since:
            filters["since"] = since
        events: list[TokenEvent] = self._store.events(  # type: ignore[assignment]
            TokenEvent, **filters
        )

        by_agent: dict[str, Decimal] = {}
        by_model: dict[str, Decimal] = {}
        total_tokens = 0
        total_cost = Decimal("0")

        for e in events:
            total_tokens += e.total_tokens
            total_cost += e.cost_usd
            by_agent[e.instance_id] = by_agent.get(
                e.instance_id, Decimal("0")
            ) + e.cost_usd
            if e.model:
                by_model[e.model] = by_model.get(e.model, Decimal("0")) + e.cost_usd

        return CostSummary(
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            by_agent=by_agent,
            by_model=by_model,
            period_start=since,
        )

    def review_summary(
        self, *, since: datetime | None = None
    ) -> ReviewSummary:
        """Review effectiveness summary."""
        filters: dict[str, Any] = {"active": True}
        if since:
            filters["since"] = since
        reviews = self._store.list(ReviewRecord, **filters)

        total = len(reviews)
        passed = sum(1 for r in reviews if r.verdict == "pass")
        total_findings = sum(r.findings_count for r in reviews)
        by_reviewer: dict[str, int] = {}
        for r in reviews:
            rid = r.reviewer_instance_id or "unknown"
            by_reviewer[rid] = by_reviewer.get(rid, 0) + 1

        return ReviewSummary(
            total_reviews=total,
            pass_rate=passed / total if total > 0 else 0.0,
            avg_findings_per_review=total_findings / total if total > 0 else 0.0,
            by_reviewer=by_reviewer,
        )

    def blocked_tickets(self) -> list[TicketRecord]:
        """All tickets currently in blocked state."""
        return self._store.list(TicketRecord, status="blocked", active=True)

    def stale_agents(
        self, *, threshold_hours: int = 24
    ) -> list[AgentRecord]:
        """Running agents with no recent activity."""
        agents = self._store.list(
            AgentRecord, state=AgentState.RUNNING, active=True
        )
        if not threshold_hours:
            return agents
        cutoff = datetime.now(timezone.utc).timestamp() - (threshold_hours * 3600)
        stale = []
        for a in agents:
            events = self._store.events(
                LifecycleEvent, instance_id=a.id
            )
            if not events:
                stale.append(a)
                continue
            latest = max(
                e.created_at.timestamp()
                for e in events
                if e.created_at is not None
            )
            if latest < cutoff:
                stale.append(a)
        return stale

    def review_round_count(self, pr_id: str) -> int:
        """How many review rounds a PR has been through."""
        return self._store.count(ReviewRecord, pr_id=pr_id, active=True)
