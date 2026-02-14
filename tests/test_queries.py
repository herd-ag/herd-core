"""Tests for herd_core.queries module — OperationalQueries semantic layer."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from herd_core.queries import OperationalQueries
from herd_core.types import (
    AgentRecord,
    AgentState,
    LifecycleEvent,
    ReviewRecord,
    TicketEvent,
    TicketPriority,
    TicketRecord,
    TokenEvent,
)


class TestActiveAgents:
    """Test active_agents() query."""

    def test_returns_only_running_agents(self, mock_store):
        """active_agents() returns only agents with state=RUNNING."""
        # Create agents in different states
        agent1 = AgentRecord(id="agent-001", state=AgentState.RUNNING)
        agent2 = AgentRecord(id="agent-002", state=AgentState.COMPLETED)
        agent3 = AgentRecord(id="agent-003", state=AgentState.RUNNING)

        mock_store.save(agent1)
        mock_store.save(agent2)
        mock_store.save(agent3)

        queries = OperationalQueries(mock_store)
        active = queries.active_agents()

        assert len(active) == 2
        assert agent1 in active
        assert agent3 in active
        assert agent2 not in active


class TestTicketTimeline:
    """Test ticket_timeline() query."""

    def test_returns_none_for_missing_ticket(self, mock_store):
        """ticket_timeline() returns None for non-existent ticket."""
        queries = OperationalQueries(mock_store)
        timeline = queries.ticket_timeline("DBC-999")
        assert timeline is None

    def test_returns_timeline_with_events(self, mock_store):
        """ticket_timeline() returns TicketTimeline with events."""
        ticket = TicketRecord(id="DBC-137", title="Test ticket")
        mock_store.save(ticket)

        # Add events
        event1 = TicketEvent(
            entity_id="DBC-137",
            event_type="transition",
            previous_status="backlog",
            new_status="in_progress",
            elapsed_minutes=30.0,
            created_at=datetime.now(timezone.utc),
        )
        event2 = TicketEvent(
            entity_id="DBC-137",
            event_type="transition",
            previous_status="in_progress",
            new_status="done",
            elapsed_minutes=120.0,
            created_at=datetime.now(timezone.utc),
        )
        mock_store.append(event1)
        mock_store.append(event2)

        queries = OperationalQueries(mock_store)
        timeline = queries.ticket_timeline("DBC-137")

        assert timeline is not None
        assert timeline.ticket.id == "DBC-137"
        assert len(timeline.events) == 2
        assert timeline.total_elapsed_minutes == 150.0

    def test_handles_none_elapsed_minutes(self, mock_store):
        """ticket_timeline() handles None elapsed_minutes gracefully."""
        ticket = TicketRecord(id="DBC-137")
        mock_store.save(ticket)

        event = TicketEvent(
            entity_id="DBC-137",
            event_type="transition",
            previous_status="backlog",
            new_status="in_progress",
            elapsed_minutes=None,
            created_at=datetime.now(timezone.utc),
        )
        mock_store.append(event)

        queries = OperationalQueries(mock_store)
        timeline = queries.ticket_timeline("DBC-137")

        assert timeline is not None
        assert timeline.total_elapsed_minutes == 0.0


class TestCostSummary:
    """Test cost_summary() query."""

    def test_aggregates_token_events_correctly(self, mock_store):
        """cost_summary() aggregates TokenEvents correctly."""
        event1 = TokenEvent(
            entity_id="DBC-137",
            event_type="usage",
            instance_id="agent-001",
            model="claude-sonnet-4-5",
            input_tokens=1000,
            output_tokens=500,
            total_tokens=1500,
            cost_usd=Decimal("0.05"),
            created_at=datetime.now(timezone.utc),
        )
        event2 = TokenEvent(
            entity_id="DBC-138",
            event_type="usage",
            instance_id="agent-002",
            model="claude-opus-4-6",
            input_tokens=2000,
            output_tokens=1000,
            total_tokens=3000,
            cost_usd=Decimal("0.10"),
            created_at=datetime.now(timezone.utc),
        )
        mock_store.append(event1)
        mock_store.append(event2)

        queries = OperationalQueries(mock_store)
        summary = queries.cost_summary()

        assert summary.total_tokens == 4500
        assert summary.total_cost_usd == Decimal("0.15")
        assert summary.by_agent["agent-001"] == Decimal("0.05")
        assert summary.by_agent["agent-002"] == Decimal("0.10")
        assert summary.by_model["claude-sonnet-4-5"] == Decimal("0.05")
        assert summary.by_model["claude-opus-4-6"] == Decimal("0.10")

    def test_respects_since_filter(self, mock_store):
        """cost_summary(since=...) respects time filter."""
        now = datetime.now(timezone.utc)
        yesterday = now - timedelta(days=1)
        two_days_ago = now - timedelta(days=2)

        # Old event (should be excluded)
        old_event = TokenEvent(
            entity_id="DBC-137",
            event_type="usage",
            instance_id="agent-001",
            model="claude-sonnet-4-5",
            total_tokens=1000,
            cost_usd=Decimal("0.05"),
            created_at=two_days_ago,
        )
        # Recent event (should be included)
        recent_event = TokenEvent(
            entity_id="DBC-138",
            event_type="usage",
            instance_id="agent-002",
            model="claude-opus-4-6",
            total_tokens=2000,
            cost_usd=Decimal("0.10"),
            created_at=now,
        )
        mock_store.append(old_event)
        mock_store.append(recent_event)

        queries = OperationalQueries(mock_store)
        summary = queries.cost_summary(since=yesterday)

        assert summary.total_tokens == 2000
        assert summary.total_cost_usd == Decimal("0.10")
        assert summary.period_start == yesterday

    def test_populates_by_model_when_model_set(self, mock_store):
        """cost_summary() populates by_model when TokenEvents have model field."""
        event1 = TokenEvent(
            entity_id="DBC-137",
            event_type="usage",
            instance_id="agent-001",
            model="claude-sonnet-4-5",
            total_tokens=1500,
            cost_usd=Decimal("0.05"),
            created_at=datetime.now(timezone.utc),
        )
        event2 = TokenEvent(
            entity_id="DBC-138",
            event_type="usage",
            instance_id="agent-002",
            model="claude-sonnet-4-5",
            total_tokens=2000,
            cost_usd=Decimal("0.07"),
            created_at=datetime.now(timezone.utc),
        )
        event3 = TokenEvent(
            entity_id="DBC-139",
            event_type="usage",
            instance_id="agent-003",
            model="claude-opus-4-6",
            total_tokens=3000,
            cost_usd=Decimal("0.15"),
            created_at=datetime.now(timezone.utc),
        )
        mock_store.append(event1)
        mock_store.append(event2)
        mock_store.append(event3)

        queries = OperationalQueries(mock_store)
        summary = queries.cost_summary()

        assert summary.by_model["claude-sonnet-4-5"] == Decimal("0.12")
        assert summary.by_model["claude-opus-4-6"] == Decimal("0.15")

    def test_by_model_empty_when_no_model_set(self, mock_store):
        """cost_summary() has empty by_model when TokenEvents have no model."""
        event = TokenEvent(
            entity_id="DBC-137",
            event_type="usage",
            instance_id="agent-001",
            model="",
            total_tokens=1500,
            cost_usd=Decimal("0.05"),
            created_at=datetime.now(timezone.utc),
        )
        mock_store.append(event)

        queries = OperationalQueries(mock_store)
        summary = queries.cost_summary()

        assert summary.by_model == {}


class TestReviewSummary:
    """Test review_summary() query."""

    def test_calculates_pass_rate_correctly(self, mock_store):
        """review_summary() calculates pass rate correctly."""
        review1 = ReviewRecord(
            id="review-001",
            pr_id="pr-123",
            verdict="pass",
            findings_count=0,
        )
        review2 = ReviewRecord(
            id="review-002",
            pr_id="pr-124",
            verdict="fail",
            findings_count=3,
        )
        review3 = ReviewRecord(
            id="review-003",
            pr_id="pr-125",
            verdict="pass",
            findings_count=1,
        )
        mock_store.save(review1)
        mock_store.save(review2)
        mock_store.save(review3)

        queries = OperationalQueries(mock_store)
        summary = queries.review_summary()

        assert summary.total_reviews == 3
        assert summary.pass_rate == 2 / 3  # 2 passed out of 3
        assert summary.avg_findings_per_review == 4 / 3  # (0 + 3 + 1) / 3

    def test_handles_no_reviews(self, mock_store):
        """review_summary() handles empty review list."""
        queries = OperationalQueries(mock_store)
        summary = queries.review_summary()

        assert summary.total_reviews == 0
        assert summary.pass_rate == 0.0
        assert summary.avg_findings_per_review == 0.0

    def test_aggregates_by_reviewer(self, mock_store):
        """review_summary() aggregates by reviewer."""
        review1 = ReviewRecord(
            id="review-001",
            pr_id="pr-123",
            reviewer_instance_id="wardenstein-001",
            verdict="pass",
        )
        review2 = ReviewRecord(
            id="review-002",
            pr_id="pr-124",
            reviewer_instance_id="wardenstein-001",
            verdict="pass",
        )
        review3 = ReviewRecord(
            id="review-003",
            pr_id="pr-125",
            reviewer_instance_id="wardenstein-002",
            verdict="fail",
        )
        mock_store.save(review1)
        mock_store.save(review2)
        mock_store.save(review3)

        queries = OperationalQueries(mock_store)
        summary = queries.review_summary()

        assert summary.by_reviewer["wardenstein-001"] == 2
        assert summary.by_reviewer["wardenstein-002"] == 1


class TestBlockedTickets:
    """Test blocked_tickets() query."""

    def test_filters_by_blocked_status(self, mock_store):
        """blocked_tickets() returns only tickets with status='blocked'."""
        ticket1 = TicketRecord(id="DBC-137", status="in_progress")
        ticket2 = TicketRecord(id="DBC-138", status="blocked")
        ticket3 = TicketRecord(id="DBC-139", status="blocked")

        mock_store.save(ticket1)
        mock_store.save(ticket2)
        mock_store.save(ticket3)

        queries = OperationalQueries(mock_store)
        blocked = queries.blocked_tickets()

        assert len(blocked) == 2
        assert ticket2 in blocked
        assert ticket3 in blocked
        assert ticket1 not in blocked


class TestStaleAgents:
    """Test stale_agents() query."""

    def test_identifies_agents_with_no_recent_events(self, mock_store):
        """stale_agents() identifies agents with no recent activity."""
        now = datetime.now(timezone.utc)
        old_timestamp = now - timedelta(hours=48)

        # Agent with recent activity
        agent1 = AgentRecord(id="agent-001", state=AgentState.RUNNING)
        event1 = LifecycleEvent(
            entity_id="DBC-137",
            event_type="activity",
            instance_id="agent-001",
            detail="Recent work",
            created_at=now,
        )

        # Agent with old activity
        agent2 = AgentRecord(id="agent-002", state=AgentState.RUNNING)
        event2 = LifecycleEvent(
            entity_id="DBC-138",
            event_type="activity",
            instance_id="agent-002",
            detail="Old work",
            created_at=old_timestamp,
        )

        # Agent with no activity
        agent3 = AgentRecord(id="agent-003", state=AgentState.RUNNING)

        mock_store.save(agent1)
        mock_store.save(agent2)
        mock_store.save(agent3)
        mock_store.append(event1)
        mock_store.append(event2)

        queries = OperationalQueries(mock_store)
        stale = queries.stale_agents(threshold_hours=24)

        assert len(stale) == 2
        assert agent2 in stale
        assert agent3 in stale
        assert agent1 not in stale

    def test_returns_all_agents_when_threshold_is_zero(self, mock_store):
        """stale_agents(threshold_hours=0) returns all running agents."""
        agent1 = AgentRecord(id="agent-001", state=AgentState.RUNNING)
        agent2 = AgentRecord(id="agent-002", state=AgentState.RUNNING)
        mock_store.save(agent1)
        mock_store.save(agent2)

        queries = OperationalQueries(mock_store)
        stale = queries.stale_agents(threshold_hours=0)

        assert len(stale) == 2


class TestReviewRoundCount:
    """Test review_round_count() query."""

    def test_returns_correct_count(self, mock_store):
        """review_round_count() returns correct number of reviews for a PR."""
        review1 = ReviewRecord(id="review-001", pr_id="pr-123", verdict="fail")
        review2 = ReviewRecord(id="review-002", pr_id="pr-123", verdict="fail")
        review3 = ReviewRecord(id="review-003", pr_id="pr-123", verdict="pass")
        review4 = ReviewRecord(id="review-004", pr_id="pr-999", verdict="pass")

        mock_store.save(review1)
        mock_store.save(review2)
        mock_store.save(review3)
        mock_store.save(review4)

        queries = OperationalQueries(mock_store)
        count = queries.review_round_count("pr-123")

        assert count == 3

    def test_returns_zero_for_pr_with_no_reviews(self, mock_store):
        """review_round_count() returns 0 for PR with no reviews."""
        queries = OperationalQueries(mock_store)
        count = queries.review_round_count("pr-999")

        assert count == 0
