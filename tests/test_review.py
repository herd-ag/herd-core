"""Tests for herd_review tool."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from herd_core.types import (
    AgentRecord,
    AgentState,
    ReviewEvent,
    ReviewRecord,
)
from herd_mcp.adapters import AdapterRegistry
from herd_mcp.tools import review


@pytest.fixture
def mock_registry(mock_store):
    """Create an AdapterRegistry with MockStore."""
    return AdapterRegistry(store=mock_store, write_lock=asyncio.Lock())


@pytest.fixture
def seeded_store(mock_store):
    """Seed mock_store with test data for review tool."""
    mock_store.save(
        AgentRecord(
            id="inst-ward-001",
            agent="wardenstein",
            model="claude-sonnet-4",
            state=AgentState.RUNNING,
            started_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    return mock_store


@pytest.fixture
def seeded_registry(seeded_store):
    """Create an AdapterRegistry with seeded MockStore."""
    return AdapterRegistry(store=seeded_store, write_lock=asyncio.Lock())


@pytest.mark.asyncio
async def test_review_with_findings(seeded_store, seeded_registry):
    """Test review creation with findings."""
    findings = [
        {
            "severity": "blocking",
            "category": "correctness",
            "description": "Null pointer dereference on line 42",
            "file_path": "src/main.py",
            "line_number": 42,
        },
        {
            "severity": "advisory",
            "category": "style",
            "description": "Consider using list comprehension",
        },
    ]

    with patch("herd_mcp.tools.review._post_review_to_github") as mock_gh:
        with patch("herd_mcp.tools.review._post_to_slack") as mock_slack:
            mock_gh.return_value = True
            mock_slack.return_value = {"success": True}

            result = await review.execute(
                pr_number=123,
                ticket_id="DBC-100",
                verdict="fail",
                findings=findings,
                agent_name="wardenstein",
                registry=seeded_registry,
            )

            assert result["review_id"] is not None
            assert result["review_id"].startswith("REV-")
            assert result["posted"] is True
            assert result["github_posted"] is True
            assert result["slack_posted"] is True
            assert result["findings_count"] == 2
            assert result["verdict"] == "fail"
            assert result["review_round"] == 1
            assert result["pr_number"] == 123

    # Verify review was recorded in store
    reviews = seeded_store.list(ReviewRecord)
    assert len(reviews) == 1
    rev = reviews[0]
    assert rev.pr_id == "PR-123"
    assert rev.verdict == "fail"

    # Verify review event was recorded
    events = seeded_store.events(ReviewEvent)
    assert len(events) >= 1
    evt = events[0]
    assert evt.event_type == "review_submitted"
    assert "fail" in evt.detail


@pytest.mark.asyncio
async def test_review_pass_no_findings(seeded_store, seeded_registry):
    """Test passing review with no findings."""
    with patch("herd_mcp.tools.review._post_review_to_github") as mock_gh:
        with patch("herd_mcp.tools.review._post_to_slack") as mock_slack:
            mock_gh.return_value = True
            mock_slack.return_value = {"success": True}

            result = await review.execute(
                pr_number=456,
                ticket_id="DBC-101",
                verdict="pass",
                findings=[],
                agent_name="wardenstein",
                registry=seeded_registry,
            )

            assert result["verdict"] == "pass"
            assert result["findings_count"] == 0
            assert result["posted"] is True

    # Verify review was stored but no findings body
    reviews = seeded_store.list(ReviewRecord)
    assert len(reviews) == 1
    assert reviews[0].findings_count == 0


@pytest.mark.asyncio
async def test_review_pass_with_advisory(seeded_store, seeded_registry):
    """Test passing review with advisory findings."""
    findings = [
        {
            "severity": "advisory",
            "category": "performance",
            "description": "Consider caching this computation",
        },
    ]

    with patch("herd_mcp.tools.review._post_review_to_github") as mock_gh:
        with patch("herd_mcp.tools.review._post_to_slack") as mock_slack:
            mock_gh.return_value = True
            mock_slack.return_value = {"success": True}

            result = await review.execute(
                pr_number=789,
                ticket_id="DBC-102",
                verdict="pass_with_advisory",
                findings=findings,
                agent_name="wardenstein",
                registry=seeded_registry,
            )

            assert result["verdict"] == "pass_with_advisory"
            assert result["findings_count"] == 1


@pytest.mark.asyncio
async def test_review_round_calculation(seeded_store, seeded_registry):
    """Test that review rounds are calculated correctly."""
    # Create first review manually in store
    seeded_store.save(
        ReviewRecord(
            id="REV-first",
            pr_id="PR-999",
            reviewer_instance_id="inst-ward-001",
            verdict="fail",
            body="First review",
            findings_count=1,
        )
    )

    with patch("herd_mcp.tools.review._post_review_to_github") as mock_gh:
        with patch("herd_mcp.tools.review._post_to_slack") as mock_slack:
            mock_gh.return_value = True
            mock_slack.return_value = {"success": True}

            result = await review.execute(
                pr_number=999,
                ticket_id="DBC-103",
                verdict="pass",
                findings=[],
                agent_name="wardenstein",
                registry=seeded_registry,
            )

            assert result["review_round"] == 2


@pytest.mark.asyncio
async def test_review_invalid_verdict(seeded_store, seeded_registry):
    """Test review with invalid verdict."""
    result = await review.execute(
        pr_number=123,
        ticket_id="DBC-100",
        verdict="invalid_verdict",
        findings=[],
        agent_name="wardenstein",
        registry=seeded_registry,
    )

    assert result["review_id"] is None
    assert result["posted"] is False
    assert "error" in result
    assert "Invalid verdict" in result["error"]


@pytest.mark.asyncio
async def test_review_github_post_failure(seeded_store, seeded_registry):
    """Test review when GitHub posting fails."""
    with patch("herd_mcp.tools.review._post_review_to_github") as mock_gh:
        with patch("herd_mcp.tools.review._post_to_slack") as mock_slack:
            mock_gh.return_value = False  # GitHub post fails
            mock_slack.return_value = {"success": True}

            result = await review.execute(
                pr_number=123,
                ticket_id="DBC-100",
                verdict="pass",
                findings=[],
                agent_name="wardenstein",
                registry=seeded_registry,
            )

            assert result["github_posted"] is False
            assert result["posted"] is False  # Overall posted is false


@pytest.mark.asyncio
async def test_review_slack_post_failure(seeded_store, seeded_registry):
    """Test review when Slack posting fails."""
    with patch("herd_mcp.tools.review._post_review_to_github") as mock_gh:
        with patch("herd_mcp.tools.review._post_to_slack") as mock_slack:
            mock_gh.return_value = True
            mock_slack.return_value = {"success": False}  # Slack post fails

            result = await review.execute(
                pr_number=123,
                ticket_id="DBC-100",
                verdict="pass",
                findings=[],
                agent_name="wardenstein",
                registry=seeded_registry,
            )

            assert result["slack_posted"] is False
            assert result["posted"] is False  # Overall posted is false


@pytest.mark.asyncio
async def test_review_format_body():
    """Test review body formatting."""
    findings = [
        {
            "severity": "blocking",
            "category": "security",
            "description": "SQL injection risk",
        },
        {"severity": "advisory", "category": "style", "description": "Use snake_case"},
    ]

    body = review._format_review_body("fail", findings, "REV-test")

    assert "## Code Review" in body
    assert "\u274c" in body  # fail emoji
    assert "REV-test" in body
    assert "Blocking Issues" in body
    assert "SQL injection risk" in body
    assert "Advisory Notes" in body
    assert "Use snake_case" in body
