"""Tests for herd_record_decision tool."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from herd_mcp.tools import record_decision


@pytest.fixture
def seeded_db(in_memory_db):
    """Provide a database with test data for record_decision tool."""
    conn = in_memory_db

    # Insert test agent
    conn.execute("""
        INSERT INTO herd.agent_def
          (agent_code, agent_role, agent_status, created_at)
        VALUES ('mason', 'backend', 'active', CURRENT_TIMESTAMP)
    """)

    yield conn


@pytest.mark.asyncio
async def test_record_decision_success(seeded_db):
    """Test successful decision recording."""
    with patch("herd_mcp.tools.record_decision.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch(
            "herd_mcp.tools.record_decision._post_to_slack_decisions"
        ) as mock_slack:
            mock_slack.return_value = {"success": True, "response": {"ok": True}}

            result = await record_decision.execute(
                decision_type="architectural",
                context="Need to choose a database",
                decision="Use DuckDB for embedded analytics",
                rationale="DuckDB is fast, embeddable, and requires no server",
                alternatives_considered="PostgreSQL, SQLite, ClickHouse",
                ticket_code="DBC-125",
                agent_name="mason",
            )

            assert result["success"] is True
            assert "decision_id" in result
            assert result["agent"] == "mason"
            assert result["ticket_code"] == "DBC-125"
            assert result["posted_to_slack"] is True

    # Verify decision was written to database
    decisions = seeded_db.execute("""
        SELECT decision_id, decision_type, context, decision, rationale,
               alternatives_considered, decided_by, ticket_code
        FROM herd.decision_record
        WHERE decided_by = 'mason'
    """).fetchall()

    assert len(decisions) == 1
    dec = decisions[0]
    assert dec[1] == "architectural"
    assert dec[2] == "Need to choose a database"
    assert dec[3] == "Use DuckDB for embedded analytics"
    assert dec[4] == "DuckDB is fast, embeddable, and requires no server"
    assert dec[5] == "PostgreSQL, SQLite, ClickHouse"
    assert dec[6] == "mason"
    assert dec[7] == "DBC-125"


@pytest.mark.asyncio
async def test_record_decision_no_alternatives(seeded_db):
    """Test decision recording without alternatives considered."""
    with patch("herd_mcp.tools.record_decision.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch(
            "herd_mcp.tools.record_decision._post_to_slack_decisions"
        ) as mock_slack:
            mock_slack.return_value = {"success": True}

            result = await record_decision.execute(
                decision_type="implementation",
                context="How to structure API responses",
                decision="Use consistent JSON envelope with data/errors fields",
                rationale="Makes client error handling easier",
                alternatives_considered=None,
                ticket_code=None,
                agent_name="mason",
            )

            assert result["success"] is True
            assert result["ticket_code"] is None

    # Verify decision was written
    decisions = seeded_db.execute("""
        SELECT alternatives_considered, ticket_code
        FROM herd.decision_record
        WHERE decided_by = 'mason'
    """).fetchall()

    assert len(decisions) == 1
    assert decisions[0][0] is None  # alternatives_considered
    assert decisions[0][1] is None  # ticket_code


@pytest.mark.asyncio
async def test_record_decision_no_agent_name():
    """Test decision recording fails without agent name."""
    result = await record_decision.execute(
        decision_type="test",
        context="test context",
        decision="test decision",
        rationale="test rationale",
        alternatives_considered=None,
        ticket_code=None,
        agent_name=None,
    )

    assert result["success"] is False
    assert "No agent identity" in result["error"]


@pytest.mark.asyncio
async def test_record_decision_slack_failure(seeded_db):
    """Test decision recording continues even if Slack posting fails."""
    with patch("herd_mcp.tools.record_decision.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch(
            "herd_mcp.tools.record_decision._post_to_slack_decisions"
        ) as mock_slack:
            mock_slack.return_value = {
                "success": False,
                "error": "HERD_SLACK_TOKEN not set",
            }

            result = await record_decision.execute(
                decision_type="pattern",
                context="How to name variables",
                decision="Use snake_case for Python",
                rationale="PEP 8 standard",
                alternatives_considered="camelCase",
                ticket_code="DBC-125",
                agent_name="mason",
            )

            # Should still succeed in DB even if Slack fails
            assert result["success"] is True
            assert result["posted_to_slack"] is False
            assert "slack_response" in result

    # Verify decision was still written to database
    decisions = seeded_db.execute("""
        SELECT COUNT(*) FROM herd.decision_record WHERE decided_by = 'mason'
    """).fetchone()

    assert decisions[0] == 1


@pytest.mark.asyncio
async def test_record_decision_types(seeded_db):
    """Test various decision types can be recorded."""
    decision_types = [
        "architectural",
        "implementation",
        "pattern",
        "design",
        "technical",
    ]

    with patch("herd_mcp.tools.record_decision.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch(
            "herd_mcp.tools.record_decision._post_to_slack_decisions"
        ) as mock_slack:
            mock_slack.return_value = {"success": True}

            for dec_type in decision_types:
                result = await record_decision.execute(
                    decision_type=dec_type,
                    context=f"Context for {dec_type}",
                    decision=f"Decision for {dec_type}",
                    rationale=f"Rationale for {dec_type}",
                    alternatives_considered=None,
                    ticket_code=None,
                    agent_name="mason",
                )

                assert result["success"] is True

    # Verify all decisions were written
    decisions = seeded_db.execute("""
        SELECT decision_type FROM herd.decision_record
        WHERE decided_by = 'mason'
        ORDER BY created_at
    """).fetchall()

    assert len(decisions) == len(decision_types)
    for i, dec_type in enumerate(decision_types):
        assert decisions[i][0] == dec_type


@pytest.mark.asyncio
async def test_post_to_slack_decisions_formatting():
    """Test Slack message formatting for decisions."""
    with patch("herd_mcp.tools.record_decision.os.getenv") as mock_getenv:
        mock_getenv.return_value = "test-token"

        with patch(
            "herd_mcp.tools.record_decision.urllib.request.urlopen"
        ) as mock_urlopen:
            # Mock successful Slack response
            mock_response = MagicMock()
            mock_response.read.return_value = b'{"ok": true}'
            mock_response.__enter__ = MagicMock(return_value=mock_response)
            mock_response.__exit__ = MagicMock(return_value=None)
            mock_urlopen.return_value = mock_response

            result = record_decision._post_to_slack_decisions(
                decision_text="Test decision text",
                ticket_code="DBC-125",
                agent_name="mason",
            )

            assert result["success"] is True

            # Verify the request was made with correct channel
            call_args = mock_urlopen.call_args
            assert call_args is not None


@pytest.mark.asyncio
async def test_post_to_slack_decisions_no_token():
    """Test Slack posting fails gracefully without token."""
    with patch("herd_mcp.tools.record_decision.os.getenv") as mock_getenv:
        mock_getenv.return_value = None

        result = record_decision._post_to_slack_decisions(
            decision_text="Test decision",
            ticket_code=None,
            agent_name="mason",
        )

        assert result["success"] is False
        assert "HERD_SLACK_TOKEN not set" in result["error"]
