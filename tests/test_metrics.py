"""Tests for herd_metrics tool."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from herd_core.types import (
    AgentRecord,
    AgentState,
    LifecycleEvent,
    ReviewEvent,
    ReviewRecord,
    SprintRecord,
    TicketEvent,
    TicketRecord,
    TokenEvent,
)
from herd_mcp.adapters import AdapterRegistry
from herd_mcp.tools import metrics


@pytest.fixture
def mock_registry(mock_store):
    """Provide an AdapterRegistry with MockStore."""
    return AdapterRegistry(store=mock_store, write_lock=asyncio.Lock())


@pytest.fixture
def seeded_store(mock_store):
    """Provide a mock store seeded with test data for metrics tool."""
    now = datetime.now(timezone.utc)

    # Insert test agent instances
    mock_store.save(
        AgentRecord(
            id="inst-001",
            agent="mason",
            model="claude-sonnet-4",
            ticket_id="DBC-100",
            state=AgentState.RUNNING,
        )
    )
    mock_store.save(
        AgentRecord(
            id="inst-002",
            agent="fresco",
            model="claude-opus-4",
            ticket_id="DBC-101",
            state=AgentState.RUNNING,
        )
    )

    # Insert token events
    mock_store.append(
        TokenEvent(
            entity_id="inst-001",
            event_type="token_usage",
            instance_id="inst-001",
            model="claude-sonnet-4",
            input_tokens=1000,
            output_tokens=500,
            total_tokens=1500,
            cost_usd=Decimal("0.50"),
            created_at=now,
        )
    )
    mock_store.append(
        TokenEvent(
            entity_id="inst-001",
            event_type="token_usage",
            instance_id="inst-001",
            model="claude-sonnet-4",
            input_tokens=2000,
            output_tokens=1000,
            total_tokens=3000,
            cost_usd=Decimal("1.00"),
            created_at=now,
        )
    )
    mock_store.append(
        TokenEvent(
            entity_id="inst-002",
            event_type="token_usage",
            instance_id="inst-002",
            model="claude-opus-4",
            input_tokens=500,
            output_tokens=250,
            total_tokens=750,
            cost_usd=Decimal("2.00"),
            created_at=now,
        )
    )

    # Insert lifecycle events (pr_submitted)
    mock_store.append(
        LifecycleEvent(
            entity_id="inst-001",
            event_type="pr_submitted",
            instance_id="inst-001",
            detail="PR #123",
            created_at=now,
        )
    )
    mock_store.append(
        LifecycleEvent(
            entity_id="inst-002",
            event_type="pr_submitted",
            instance_id="inst-002",
            detail="PR #456",
            created_at=now,
        )
    )

    # Insert reviews
    mock_store.save(
        ReviewRecord(
            id="REV-001",
            pr_id="PR-123",
            reviewer_instance_id="inst-001",
            verdict="pass",
            body="Clean implementation.",
            findings_count=0,
        )
    )
    mock_store.save(
        ReviewRecord(
            id="REV-002",
            pr_id="PR-456",
            reviewer_instance_id="inst-002",
            verdict="fail",
            body="[blocking] correctness: Bug in logic\n[advisory] style: Format issue",
            findings_count=2,
        )
    )

    # Insert review events
    mock_store.append(
        ReviewEvent(
            entity_id="inst-001",
            event_type="review_submitted",
            instance_id="inst-001",
            review_id="REV-001",
            pr_id="PR-123",
            verdict="pass",
            detail="pass",
            created_at=now,
        )
    )
    mock_store.append(
        ReviewEvent(
            entity_id="inst-002",
            event_type="review_submitted",
            instance_id="inst-002",
            review_id="REV-002",
            pr_id="PR-456",
            verdict="fail",
            detail="fail",
            created_at=now,
        )
    )

    # Insert tickets
    mock_store.save(
        TicketRecord(
            id="DBC-100",
            title="Test ticket 1",
            description="Description 1",
            status="done",
        )
    )
    mock_store.save(
        TicketRecord(
            id="DBC-101",
            title="Test ticket 2",
            description="Description 2",
            status="done",
        )
    )
    mock_store.save(
        TicketRecord(
            id="DBC-102",
            title="Test ticket 3",
            description="Description 3",
            status="done",
        )
    )

    # Insert ticket events
    mock_store.append(
        TicketEvent(
            entity_id="DBC-100",
            event_type="status_changed",
            instance_id="inst-001",
            previous_status="backlog",
            new_status="in_progress",
            note="Started work",
            created_at=now,
        )
    )
    mock_store.append(
        TicketEvent(
            entity_id="DBC-100",
            event_type="status_changed",
            instance_id="inst-001",
            previous_status="in_progress",
            new_status="done",
            note="Completed",
            created_at=now,
        )
    )

    # Insert sprints
    mock_store.save(
        SprintRecord(
            id="sprint-1",
            name="Sprint 1",
            number=1,
            status="active",
        )
    )
    mock_store.save(
        SprintRecord(
            id="sprint-2",
            name="Sprint 2",
            number=2,
            status="active",
        )
    )

    return mock_store


@pytest.mark.asyncio
async def test_cost_per_ticket(seeded_store, mock_registry):
    """Test cost per ticket query."""
    result = await metrics.execute(
        query="cost_per_ticket",
        period=None,
        group_by=None,
        agent_name="mason",
        registry=mock_registry,
    )

    assert "data" in result
    assert "summary" in result
    assert len(result["data"]) == 2  # Two tickets with activity
    assert any(d["ticket"] == "DBC-100" for d in result["data"])
    assert result["data"][0]["cost_usd"] > 0


@pytest.mark.asyncio
async def test_agent_performance(seeded_store, mock_registry):
    """Test agent performance query."""
    result = await metrics.execute(
        query="agent_performance",
        period=None,
        group_by=None,
        agent_name="mason",
        registry=mock_registry,
    )

    assert "data" in result
    assert "summary" in result
    assert len(result["data"]) == 2  # Two agents
    # Should show PR and review counts
    assert "2 PRs created" in result["summary"]


@pytest.mark.asyncio
async def test_model_efficiency(seeded_store, mock_registry):
    """Test model efficiency query."""
    result = await metrics.execute(
        query="model_efficiency",
        period=None,
        group_by=None,
        agent_name="mason",
        registry=mock_registry,
    )

    assert "data" in result
    assert "summary" in result
    assert len(result["data"]) == 2  # Two models
    assert any(d["model"] == "claude-sonnet-4" for d in result["data"])
    assert any(d["model"] == "claude-opus-4" for d in result["data"])


@pytest.mark.asyncio
async def test_review_effectiveness_by_verdict(seeded_store, mock_registry):
    """Test review effectiveness query grouped by verdict."""
    result = await metrics.execute(
        query="review_effectiveness",
        period=None,
        group_by=None,
        agent_name="mason",
        registry=mock_registry,
    )

    assert "data" in result
    assert "summary" in result
    # Should have pass and fail verdicts
    assert any(d["verdict"] == "pass" for d in result["data"])
    assert any(d["verdict"] == "fail" for d in result["data"])
    assert "50.0% pass rate" in result["summary"]  # 1 pass, 1 fail


@pytest.mark.asyncio
async def test_review_effectiveness_by_category(seeded_store, mock_registry):
    """Test review effectiveness query grouped by category."""
    result = await metrics.execute(
        query="review_effectiveness",
        period=None,
        group_by="category",
        agent_name="mason",
        registry=mock_registry,
    )

    assert "data" in result
    assert "summary" in result
    # Should have categories from findings parsed from review body
    assert any(d["category"] == "correctness" for d in result["data"])
    assert any(d["category"] == "style" for d in result["data"])


@pytest.mark.asyncio
async def test_sprint_velocity(seeded_store, mock_registry):
    """Test sprint velocity query."""
    result = await metrics.execute(
        query="sprint_velocity",
        period=None,
        group_by=None,
        agent_name="mason",
        registry=mock_registry,
    )

    assert "data" in result
    assert "summary" in result
    # Should have 2 sprints
    assert len(result["data"]) == 2
    assert any(d["sprint"] == "Sprint 1" for d in result["data"])


@pytest.mark.asyncio
async def test_pipeline_efficiency(seeded_store, mock_registry):
    """Test pipeline efficiency query."""
    result = await metrics.execute(
        query="pipeline_efficiency",
        period=None,
        group_by=None,
        agent_name="mason",
        registry=mock_registry,
    )

    assert "data" in result
    assert "summary" in result
    # Should show status transitions
    assert len(result["data"]) > 0


@pytest.mark.asyncio
async def test_headline_metric(seeded_store, mock_registry):
    """Test headline metric (cost per merged line)."""
    result = await metrics.execute(
        query="headline",
        period=None,
        group_by=None,
        agent_name="mason",
        registry=mock_registry,
    )

    assert "data" in result
    assert "summary" in result
    assert len(result["data"]) == 3  # total_cost, lines_added, cost_per_line
    assert any(d["metric"] == "total_cost_usd" for d in result["data"])
    assert any(d["metric"] == "cost_per_line_usd" for d in result["data"])


@pytest.mark.asyncio
async def test_unknown_query(seeded_store, mock_registry):
    """Test unknown query type."""
    result = await metrics.execute(
        query="unknown_query",
        period=None,
        group_by=None,
        agent_name="mason",
        registry=mock_registry,
    )

    assert "error" in result
    assert "Unknown query" in result["error"]


@pytest.mark.asyncio
async def test_period_filtering_today(seeded_store, mock_registry):
    """Test period filtering with 'today'."""
    result = await metrics.execute(
        query="cost_per_ticket",
        period="today",
        group_by=None,
        agent_name="mason",
        registry=mock_registry,
    )

    assert "data" in result
    # Should still return data since test data was created at current time


@pytest.mark.asyncio
async def test_period_filtering_iso_range(seeded_store, mock_registry):
    """Test period filtering with ISO date range."""
    result = await metrics.execute(
        query="cost_per_ticket",
        period="2026-01-01T00:00:00+00:00..2026-12-31T23:59:59+00:00",
        group_by=None,
        agent_name="mason",
        registry=mock_registry,
    )

    assert "data" in result


def test_parse_period():
    """Test period parsing helper function."""
    # Test today
    start, end = metrics._parse_period("today")
    assert start is not None
    assert end is not None
    assert isinstance(start, datetime)
    assert isinstance(end, datetime)

    # Test this_week
    start, end = metrics._parse_period("this_week")
    assert start is not None
    assert end is not None

    # Test ISO range
    start, end = metrics._parse_period("2026-01-01..2026-02-01")
    assert start is not None
    assert end is not None
    assert isinstance(start, datetime)
    assert isinstance(end, datetime)

    # Test None
    start, end = metrics._parse_period(None)
    assert start is None
    assert end is None


@pytest.mark.asyncio
async def test_query_alias_token_costs(seeded_store, mock_registry):
    """Test that token_costs alias works for cost_per_ticket."""
    result = await metrics.execute(
        query="token_costs",
        period=None,
        group_by=None,
        agent_name="mason",
        registry=mock_registry,
    )

    assert "data" in result
    assert "summary" in result
    # Just verify it returns data (same structure as cost_per_ticket)
    # The actual data content depends on the store state
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
async def test_query_alias_review_stats(seeded_store, mock_registry):
    """Test that review_stats alias works for review_effectiveness."""
    result = await metrics.execute(
        query="review_stats",
        period=None,
        group_by=None,
        agent_name="mason",
        registry=mock_registry,
    )

    assert "data" in result
    assert "summary" in result
    # Just verify it returns review data structure
    assert isinstance(result["data"], list)


@pytest.mark.asyncio
async def test_query_alias_velocity(seeded_store, mock_registry):
    """Test that velocity alias works for sprint_velocity."""
    result = await metrics.execute(
        query="velocity",
        period=None,
        group_by=None,
        agent_name="mason",
        registry=mock_registry,
    )

    assert "data" in result
    assert "summary" in result
    # Just verify it returns sprint velocity data structure
    assert isinstance(result["data"], list)
