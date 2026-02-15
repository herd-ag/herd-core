"""Tests for herd_metrics tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from herd_mcp.tools import metrics


@pytest.fixture
def seeded_db(in_memory_db):
    """Provide a database with test data for metrics tool."""
    conn = in_memory_db

    # Insert test agents
    conn.execute("""
        INSERT INTO herd.agent_def
          (agent_code, agent_role, agent_status, default_model_code, created_at)
        VALUES
          ('mason', 'backend', 'active', 'claude-sonnet-4', CURRENT_TIMESTAMP),
          ('fresco', 'frontend', 'active', 'claude-opus-4', CURRENT_TIMESTAMP)
        """)

    # Insert test agent instances
    conn.execute("""
        INSERT INTO herd.agent_instance
          (agent_instance_code, agent_code, model_code, ticket_code, agent_instance_started_at)
        VALUES
          ('inst-001', 'mason', 'claude-sonnet-4', 'DBC-100', CURRENT_TIMESTAMP),
          ('inst-002', 'fresco', 'claude-opus-4', 'DBC-101', CURRENT_TIMESTAMP)
        """)

    # Insert token activity
    conn.execute("""
        INSERT INTO herd.agent_instance_token_activity
          (agent_instance_code, model_code, token_input_count, token_output_count,
           token_cost_usd, created_at)
        VALUES
          ('inst-001', 'claude-sonnet-4', 1000, 500, 0.50, CURRENT_TIMESTAMP),
          ('inst-001', 'claude-sonnet-4', 2000, 1000, 1.00, CURRENT_TIMESTAMP),
          ('inst-002', 'claude-opus-4', 500, 250, 2.00, CURRENT_TIMESTAMP)
        """)

    # Insert lifecycle activities
    conn.execute("""
        INSERT INTO herd.agent_instance_lifecycle_activity
          (agent_instance_code, lifecycle_event_type, lifecycle_detail, created_at)
        VALUES
          ('inst-001', 'pr_submitted', 'PR #123', CURRENT_TIMESTAMP),
          ('inst-002', 'pr_submitted', 'PR #456', CURRENT_TIMESTAMP)
        """)

    # Insert reviews
    conn.execute("""
        INSERT INTO herd.review_def
          (review_code, pr_code, reviewer_agent_instance_code, review_round,
           review_verdict, created_at)
        VALUES
          ('REV-001', 'PR-123', 'inst-001', 1, 'pass', CURRENT_TIMESTAMP),
          ('REV-002', 'PR-456', 'inst-002', 1, 'fail', CURRENT_TIMESTAMP)
        """)

    # Insert review findings
    conn.execute("""
        INSERT INTO herd.review_finding
          (review_finding_code, review_code, finding_category, finding_severity,
           finding_description, created_at)
        VALUES
          ('RF-001', 'REV-002', 'correctness', 'blocking', 'Bug in logic', CURRENT_TIMESTAMP),
          ('RF-002', 'REV-002', 'style', 'advisory', 'Format issue', CURRENT_TIMESTAMP)
        """)

    # Insert review activity
    conn.execute("""
        INSERT INTO herd.agent_instance_review_activity
          (agent_instance_code, review_code, pr_code, review_event_type,
           review_activity_detail, created_at)
        VALUES
          ('inst-001', 'REV-001', 'PR-123', 'review_submitted', 'pass', CURRENT_TIMESTAMP),
          ('inst-002', 'REV-002', 'PR-456', 'review_submitted', 'fail', CURRENT_TIMESTAMP)
        """)

    # Insert tickets
    conn.execute("""
        INSERT INTO herd.ticket_def
          (ticket_code, ticket_title, ticket_description, ticket_current_status,
           current_sprint_code, created_at)
        VALUES
          ('DBC-100', 'Test ticket 1', 'Description 1', 'done', 'Sprint 1', CURRENT_TIMESTAMP),
          ('DBC-101', 'Test ticket 2', 'Description 2', 'done', 'Sprint 1', CURRENT_TIMESTAMP),
          ('DBC-102', 'Test ticket 3', 'Description 3', 'done', 'Sprint 2', CURRENT_TIMESTAMP)
        """)

    # Insert ticket activity
    conn.execute("""
        INSERT INTO herd.agent_instance_ticket_activity
          (agent_instance_code, ticket_code, ticket_event_type, ticket_status,
           ticket_activity_comment, created_at)
        VALUES
          ('inst-001', 'DBC-100', 'status_changed', 'in_progress', 'Started work', CURRENT_TIMESTAMP),
          ('inst-001', 'DBC-100', 'status_changed', 'done', 'Completed', CURRENT_TIMESTAMP)
        """)

    yield conn


@pytest.mark.asyncio
async def test_cost_per_ticket(seeded_db):
    """Test cost per ticket query."""
    with patch("herd_mcp.tools.metrics.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await metrics.execute(
            query="cost_per_ticket",
            period=None,
            group_by=None,
            agent_name="mason",
        )

        assert "data" in result
        assert "summary" in result
        assert len(result["data"]) == 2  # Two tickets with activity
        assert any(d["ticket"] == "DBC-100" for d in result["data"])
        assert result["data"][0]["cost_usd"] > 0


@pytest.mark.asyncio
async def test_agent_performance(seeded_db):
    """Test agent performance query."""
    with patch("herd_mcp.tools.metrics.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await metrics.execute(
            query="agent_performance",
            period=None,
            group_by=None,
            agent_name="mason",
        )

        assert "data" in result
        assert "summary" in result
        assert len(result["data"]) == 2  # Two agents
        # Should show PR and review counts
        assert "2 PRs created" in result["summary"]


@pytest.mark.asyncio
async def test_model_efficiency(seeded_db):
    """Test model efficiency query."""
    with patch("herd_mcp.tools.metrics.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await metrics.execute(
            query="model_efficiency",
            period=None,
            group_by=None,
            agent_name="mason",
        )

        assert "data" in result
        assert "summary" in result
        assert len(result["data"]) == 2  # Two models
        assert any(d["model"] == "claude-sonnet-4" for d in result["data"])
        assert any(d["model"] == "claude-opus-4" for d in result["data"])


@pytest.mark.asyncio
async def test_review_effectiveness_by_verdict(seeded_db):
    """Test review effectiveness query grouped by verdict."""
    with patch("herd_mcp.tools.metrics.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await metrics.execute(
            query="review_effectiveness",
            period=None,
            group_by=None,
            agent_name="mason",
        )

        assert "data" in result
        assert "summary" in result
        # Should have pass and fail verdicts
        assert any(d["verdict"] == "pass" for d in result["data"])
        assert any(d["verdict"] == "fail" for d in result["data"])
        assert "50.0% pass rate" in result["summary"]  # 1 pass, 1 fail


@pytest.mark.asyncio
async def test_review_effectiveness_by_category(seeded_db):
    """Test review effectiveness query grouped by category."""
    with patch("herd_mcp.tools.metrics.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await metrics.execute(
            query="review_effectiveness",
            period=None,
            group_by="category",
            agent_name="mason",
        )

        assert "data" in result
        assert "summary" in result
        # Should have categories from findings
        assert any(d["category"] == "correctness" for d in result["data"])
        assert any(d["category"] == "style" for d in result["data"])


@pytest.mark.asyncio
async def test_sprint_velocity(seeded_db):
    """Test sprint velocity query."""
    with patch("herd_mcp.tools.metrics.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await metrics.execute(
            query="sprint_velocity",
            period=None,
            group_by=None,
            agent_name="mason",
        )

        assert "data" in result
        assert "summary" in result
        # Should have 2 sprints
        assert len(result["data"]) == 2
        assert any(d["sprint"] == "Sprint 1" for d in result["data"])


@pytest.mark.asyncio
async def test_pipeline_efficiency(seeded_db):
    """Test pipeline efficiency query."""
    with patch("herd_mcp.tools.metrics.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await metrics.execute(
            query="pipeline_efficiency",
            period=None,
            group_by=None,
            agent_name="mason",
        )

        assert "data" in result
        assert "summary" in result
        # Should show status transitions
        assert len(result["data"]) > 0


@pytest.mark.asyncio
async def test_headline_metric(seeded_db):
    """Test headline metric (cost per merged line)."""
    with patch("herd_mcp.tools.metrics.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await metrics.execute(
            query="headline",
            period=None,
            group_by=None,
            agent_name="mason",
        )

        assert "data" in result
        assert "summary" in result
        assert len(result["data"]) == 3  # total_cost, lines_added, cost_per_line
        assert any(d["metric"] == "total_cost_usd" for d in result["data"])
        assert any(d["metric"] == "cost_per_line_usd" for d in result["data"])


@pytest.mark.asyncio
async def test_unknown_query(seeded_db):
    """Test unknown query type."""
    with patch("herd_mcp.tools.metrics.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await metrics.execute(
            query="unknown_query",
            period=None,
            group_by=None,
            agent_name="mason",
        )

        assert "error" in result
        assert "Unknown query" in result["error"]


@pytest.mark.asyncio
async def test_period_filtering_today(seeded_db):
    """Test period filtering with 'today'."""
    with patch("herd_mcp.tools.metrics.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await metrics.execute(
            query="cost_per_ticket",
            period="today",
            group_by=None,
            agent_name="mason",
        )

        assert "data" in result
        # Should still return data since test data is created at CURRENT_TIMESTAMP


@pytest.mark.asyncio
async def test_period_filtering_iso_range(seeded_db):
    """Test period filtering with ISO date range."""
    with patch("herd_mcp.tools.metrics.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await metrics.execute(
            query="cost_per_ticket",
            period="2026-01-01..2026-12-31",
            group_by=None,
            agent_name="mason",
        )

        assert "data" in result


def test_parse_period():
    """Test period parsing helper function."""
    # Test today
    start, end = metrics._parse_period("today")
    assert start is not None
    assert end is not None

    # Test this_week
    start, end = metrics._parse_period("this_week")
    assert start is not None
    assert end is not None

    # Test ISO range
    start, end = metrics._parse_period("2026-01-01..2026-02-01")
    assert start == "2026-01-01"
    assert end == "2026-02-01"

    # Test None
    start, end = metrics._parse_period(None)
    assert start is None
    assert end is None


def test_build_period_filter():
    """Test period filter building."""
    filter_clause = metrics._build_period_filter("2026-01-01", "2026-02-01")
    assert "created_at" in filter_clause
    assert "2026-01-01" in filter_clause
    assert "2026-02-01" in filter_clause

    # Test with custom column
    filter_clause = metrics._build_period_filter(
        "2026-01-01", "2026-02-01", "modified_at"
    )
    assert "modified_at" in filter_clause

    # Test with None
    filter_clause = metrics._build_period_filter(None, None)
    assert filter_clause == ""


@pytest.mark.asyncio
async def test_query_alias_token_costs(seeded_db):
    """Test that token_costs alias works for cost_per_ticket."""
    with patch("herd_mcp.tools.metrics.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await metrics.execute(
            query="token_costs",
            period=None,
            group_by=None,
            agent_name="mason",
        )

        assert "data" in result
        assert "summary" in result
        # Just verify it returns data (same structure as cost_per_ticket)
        # The actual data content depends on the DB state
        assert isinstance(result["data"], list)


@pytest.mark.asyncio
async def test_query_alias_review_stats(seeded_db):
    """Test that review_stats alias works for review_effectiveness."""
    with patch("herd_mcp.tools.metrics.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await metrics.execute(
            query="review_stats",
            period=None,
            group_by=None,
            agent_name="mason",
        )

        assert "data" in result
        assert "summary" in result
        # Just verify it returns review data structure
        assert isinstance(result["data"], list)


@pytest.mark.asyncio
async def test_query_alias_velocity(seeded_db):
    """Test that velocity alias works for sprint_velocity."""
    with patch("herd_mcp.tools.metrics.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await metrics.execute(
            query="velocity",
            period=None,
            group_by=None,
            agent_name="mason",
        )

        assert "data" in result
        assert "summary" in result
        # Just verify it returns sprint velocity data structure
        assert isinstance(result["data"], list)
