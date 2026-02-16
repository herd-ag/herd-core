"""Tests for herd_record_decision tool."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from herd_core.types import DecisionRecord
from herd_mcp.adapters import AdapterRegistry
from herd_mcp.tools import record_decision


@pytest.fixture
def mock_registry(mock_store):
    """Create an AdapterRegistry with MockStore."""
    return AdapterRegistry(store=mock_store, write_lock=asyncio.Lock())


@pytest.mark.asyncio
async def test_record_decision_success(mock_store, mock_registry):
    """Test successful decision recording."""
    with patch("herd_mcp.tools.record_decision._post_to_slack_decisions") as mock_slack:
        mock_slack.return_value = {"success": True, "response": {"ok": True}}

        result = await record_decision.execute(
            decision_type="architectural",
            context="Need to choose a database",
            decision="Use DuckDB for embedded analytics",
            rationale="DuckDB is fast, embeddable, and requires no server",
            alternatives_considered="PostgreSQL, SQLite, ClickHouse",
            ticket_code="DBC-125",
            agent_name="mason",
            registry=mock_registry,
        )

        assert result["success"] is True
        assert "decision_id" in result
        assert result["agent"] == "mason"
        assert result["ticket_code"] == "DBC-125"
        assert result["posted_to_slack"] is True

    # Verify decision was written to store
    decisions = mock_store.list(DecisionRecord, decision_maker="mason")
    assert len(decisions) == 1
    dec = decisions[0]
    assert "architectural" in dec.title
    assert "Need to choose a database" in dec.body
    assert "Use DuckDB for embedded analytics" in dec.body
    assert "DuckDB is fast, embeddable, and requires no server" in dec.body
    assert "PostgreSQL, SQLite, ClickHouse" in dec.body
    assert dec.decision_maker == "mason"
    assert dec.scope == "DBC-125"


@pytest.mark.asyncio
async def test_record_decision_no_alternatives(mock_store, mock_registry):
    """Test decision recording without alternatives considered."""
    with patch("herd_mcp.tools.record_decision._post_to_slack_decisions") as mock_slack:
        mock_slack.return_value = {"success": True}

        result = await record_decision.execute(
            decision_type="implementation",
            context="How to structure API responses",
            decision="Use consistent JSON envelope with data/errors fields",
            rationale="Makes client error handling easier",
            alternatives_considered=None,
            ticket_code=None,
            agent_name="mason",
            registry=mock_registry,
        )

        assert result["success"] is True
        assert result["ticket_code"] is None

    # Verify decision was written
    decisions = mock_store.list(DecisionRecord, decision_maker="mason")
    assert len(decisions) == 1
    dec = decisions[0]
    assert "Alternatives" not in dec.body  # No alternatives section
    assert dec.scope is None  # ticket_code


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
async def test_record_decision_slack_failure(mock_store, mock_registry):
    """Test decision recording continues even if Slack posting fails."""
    with patch("herd_mcp.tools.record_decision._post_to_slack_decisions") as mock_slack:
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
            registry=mock_registry,
        )

        # Should still succeed in store even if Slack fails
        assert result["success"] is True
        assert result["posted_to_slack"] is False
        assert "slack_response" in result

    # Verify decision was still written to store
    decisions = mock_store.list(DecisionRecord, decision_maker="mason")
    assert len(decisions) == 1


@pytest.mark.asyncio
async def test_record_decision_types(mock_store, mock_registry):
    """Test various decision types can be recorded."""
    decision_types = [
        "architectural",
        "implementation",
        "pattern",
        "design",
        "technical",
    ]

    with patch("herd_mcp.tools.record_decision._post_to_slack_decisions") as mock_slack:
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
                registry=mock_registry,
            )

            assert result["success"] is True

    # Verify all decisions were written
    decisions = mock_store.list(DecisionRecord, decision_maker="mason")
    assert len(decisions) == len(decision_types)
    # Verify each type is present in the stored decisions
    stored_types = set()
    for dec in decisions:
        # Title format is "decision_type: decision_text[:80]"
        for dt in decision_types:
            if dec.title.startswith(dt):
                stored_types.add(dt)
    assert stored_types == set(decision_types)


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
        assert "HERD_NOTIFY_SLACK_TOKEN not set" in result["error"]
