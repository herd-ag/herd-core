"""Tests for herd_review tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from herd_mcp.tools import review


@pytest.fixture
def seeded_db(in_memory_db):
    """Provide a database with test data for review tool."""
    conn = in_memory_db

    # Insert test agents
    conn.execute("""
        INSERT INTO herd.agent_def
          (agent_code, agent_role, agent_status, created_at)
        VALUES ('wardenstein', 'qa', 'active', CURRENT_TIMESTAMP)
        """)

    # Insert test agent instance
    conn.execute("""
        INSERT INTO herd.agent_instance
          (agent_instance_code, agent_code, model_code, agent_instance_started_at)
        VALUES ('inst-ward-001', 'wardenstein', 'claude-sonnet-4', CURRENT_TIMESTAMP)
        """)

    yield conn


@pytest.mark.asyncio
async def test_review_with_findings(seeded_db):
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

    with patch("herd_mcp.tools.review.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

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

    # Verify review was recorded
    review_record = seeded_db.execute("""
        SELECT review_code, pr_code, review_verdict, review_round
        FROM herd.review_def
        """).fetchone()
    assert review_record is not None
    assert review_record[1] == "PR-123"
    assert review_record[2] == "fail"
    assert review_record[3] == 1

    # Verify findings were recorded
    finding_count = seeded_db.execute(
        "SELECT COUNT(*) FROM herd.review_finding"
    ).fetchone()[0]
    assert finding_count == 2

    # Verify activity was recorded
    activity = seeded_db.execute("""
        SELECT review_event_type, review_activity_detail
        FROM herd.agent_instance_review_activity
        """).fetchone()
    assert activity is not None
    assert activity[0] == "review_submitted"
    assert "fail" in activity[1]


@pytest.mark.asyncio
async def test_review_pass_no_findings(seeded_db):
    """Test passing review with no findings."""
    with patch("herd_mcp.tools.review.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

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
                )

                assert result["verdict"] == "pass"
                assert result["findings_count"] == 0
                assert result["posted"] is True

    # Verify no findings recorded
    finding_count = seeded_db.execute(
        "SELECT COUNT(*) FROM herd.review_finding"
    ).fetchone()[0]
    assert finding_count == 0


@pytest.mark.asyncio
async def test_review_pass_with_advisory(seeded_db):
    """Test passing review with advisory findings."""
    findings = [
        {
            "severity": "advisory",
            "category": "performance",
            "description": "Consider caching this computation",
        },
    ]

    with patch("herd_mcp.tools.review.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

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
                )

                assert result["verdict"] == "pass_with_advisory"
                assert result["findings_count"] == 1


@pytest.mark.asyncio
async def test_review_round_calculation(seeded_db):
    """Test that review rounds are calculated correctly."""
    # Create first review manually
    seeded_db.execute("""
        INSERT INTO herd.review_def
          (review_code, pr_code, reviewer_agent_instance_code, review_round,
           review_verdict, created_at)
        VALUES ('REV-first', 'PR-999', 'inst-ward-001', 1, 'fail', CURRENT_TIMESTAMP)
        """)

    with patch("herd_mcp.tools.review.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

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
                )

                assert result["review_round"] == 2


@pytest.mark.asyncio
async def test_review_invalid_verdict(seeded_db):
    """Test review with invalid verdict."""
    with patch("herd_mcp.tools.review.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        result = await review.execute(
            pr_number=123,
            ticket_id="DBC-100",
            verdict="invalid_verdict",
            findings=[],
            agent_name="wardenstein",
        )

        assert result["review_id"] is None
        assert result["posted"] is False
        assert "error" in result
        assert "Invalid verdict" in result["error"]


@pytest.mark.asyncio
async def test_review_github_post_failure(seeded_db):
    """Test review when GitHub posting fails."""
    with patch("herd_mcp.tools.review.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

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
                )

                assert result["github_posted"] is False
                assert result["posted"] is False  # Overall posted is false


@pytest.mark.asyncio
async def test_review_slack_post_failure(seeded_db):
    """Test review when Slack posting fails."""
    with patch("herd_mcp.tools.review.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

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
    assert "❌" in body  # fail emoji
    assert "REV-test" in body
    assert "Blocking Issues" in body
    assert "SQL injection risk" in body
    assert "Advisory Notes" in body
    assert "Use snake_case" in body
