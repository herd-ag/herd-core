"""Tests for herd_status tool."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from herd_mcp.tools import status


@pytest.fixture
def seeded_db(in_memory_db):
    """Provide a database with test data for status tool."""
    conn = in_memory_db

    # Insert test agents
    conn.execute("""
        INSERT INTO herd.agent_def
          (agent_code, agent_role, agent_status, default_model_code, created_at)
        VALUES
          ('mason', 'backend', 'active', 'claude-sonnet-4', CURRENT_TIMESTAMP),
          ('fresco', 'frontend', 'active', 'claude-sonnet-4', CURRENT_TIMESTAMP),
          ('steve', 'architect', 'active', 'claude-opus-4', CURRENT_TIMESTAMP)
        """)

    # Insert test sprint
    conn.execute("""
        INSERT INTO herd.sprint_def
          (sprint_code, sprint_title, sprint_goal, sprint_started_at,
           sprint_planned_end_at, created_at)
        VALUES ('SP-001', 'Sprint 1', 'Build core tools', CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP + INTERVAL '2 weeks', CURRENT_TIMESTAMP)
        """)

    # Insert test tickets
    conn.execute("""
        INSERT INTO herd.ticket_def
          (ticket_code, ticket_title, ticket_description, ticket_current_status,
           current_sprint_code, created_at)
        VALUES
          ('DBC-91', 'Core tools', 'Implement core MCP tools', 'in_progress', 'SP-001', CURRENT_TIMESTAMP),
          ('DBC-92', 'Documentation', 'Write docs', 'backlog', 'SP-001', CURRENT_TIMESTAMP),
          ('DBC-93', 'Blocked ticket', 'Cannot proceed', 'blocked', NULL, CURRENT_TIMESTAMP)
        """)

    # Insert test agent instances
    conn.execute("""
        INSERT INTO herd.agent_instance
          (agent_instance_code, agent_code, model_code, ticket_code,
           agent_instance_started_at)
        VALUES
          ('inst-001', 'mason', 'claude-sonnet-4', 'DBC-91', CURRENT_TIMESTAMP)
        """)

    # Insert ticket activity (for blocked ticket)
    conn.execute("""
        INSERT INTO herd.agent_instance_ticket_activity
          (agent_instance_code, ticket_code, ticket_event_type, ticket_status,
           blocker_ticket_code, blocker_description, created_at)
        VALUES
          ('inst-001', 'DBC-93', 'blocked', 'blocked', 'DBC-91',
           'Waiting for core tools', CURRENT_TIMESTAMP)
        """)

    yield conn


@pytest.mark.asyncio
async def test_status_scope_all(seeded_db):
    """Test status query with scope='all'."""
    with patch("herd_mcp.db.get_connection", return_value=seeded_db):
        result = await status.execute(scope="all", agent_name="steve")

        assert result["scope"] == "all"
        assert "agents" in result
        assert "sprint" in result
        assert "blockers" in result
        assert result["requesting_agent"] == "steve"

        # Check agents
        assert len(result["agents"]) == 3
        agent_codes = [a["agent_code"] for a in result["agents"]]
        assert "mason" in agent_codes
        assert "fresco" in agent_codes
        assert "steve" in agent_codes

        # Check that mason has assignment
        mason = next(a for a in result["agents"] if a["agent_code"] == "mason")
        assert mason["current_assignment"] is not None
        assert mason["current_assignment"]["ticket_code"] == "DBC-91"

        # Check sprint
        assert result["sprint"] is not None
        assert result["sprint"]["sprint_code"] == "SP-001"
        assert len(result["sprint"]["tickets"]) == 2

        # Check blockers
        assert len(result["blockers"]) == 1
        assert result["blockers"][0]["ticket_code"] == "DBC-93"
        assert result["blockers"][0]["blocker_ticket_code"] == "DBC-91"


@pytest.mark.asyncio
async def test_status_scope_sprint(seeded_db):
    """Test status query with scope='sprint'."""
    with patch("herd_mcp.db.get_connection", return_value=seeded_db):
        result = await status.execute(scope="sprint", agent_name="steve")

        assert result["scope"] == "sprint"
        assert "sprint" in result
        assert "agents" not in result
        assert "blockers" not in result

        assert result["sprint"]["sprint_code"] == "SP-001"
        assert len(result["sprint"]["tickets"]) == 2


@pytest.mark.asyncio
async def test_status_scope_agent(seeded_db):
    """Test status query with scope='agent:<name>'."""
    with patch("herd_mcp.db.get_connection", return_value=seeded_db):
        result = await status.execute(scope="agent:mason", agent_name="steve")

        assert result["scope"] == "agent:mason"
        assert "agent_status" in result

        agent_status = result["agent_status"]
        assert agent_status["agent_code"] == "mason"
        assert agent_status["agent_role"] == "backend"
        assert agent_status["agent_status"] == "active"
        assert len(agent_status["recent_instances"]) == 1
        assert agent_status["recent_instances"][0]["ticket_code"] == "DBC-91"


@pytest.mark.asyncio
async def test_status_scope_agent_not_found(seeded_db):
    """Test status query for nonexistent agent."""
    with patch("herd_mcp.db.get_connection", return_value=seeded_db):
        result = await status.execute(scope="agent:nonexistent", agent_name="steve")

        assert result["scope"] == "agent:nonexistent"
        assert "agent_status" in result
        assert "error" in result["agent_status"]


@pytest.mark.asyncio
async def test_status_scope_ticket(seeded_db):
    """Test status query with scope='ticket:<id>'."""
    with patch("herd_mcp.db.get_connection", return_value=seeded_db):
        result = await status.execute(scope="ticket:DBC-91", agent_name="steve")

        assert result["scope"] == "ticket:DBC-91"
        assert "ticket_status" in result

        ticket_status = result["ticket_status"]
        assert ticket_status["ticket_code"] == "DBC-91"
        assert ticket_status["ticket_title"] == "Core tools"
        assert ticket_status["current_status"] == "in_progress"
        assert ticket_status["sprint_code"] == "SP-001"


@pytest.mark.asyncio
async def test_status_scope_ticket_not_found(seeded_db):
    """Test status query for nonexistent ticket."""
    with patch("herd_mcp.db.get_connection", return_value=seeded_db):
        result = await status.execute(scope="ticket:NONEXISTENT", agent_name="steve")

        assert result["scope"] == "ticket:NONEXISTENT"
        assert "ticket_status" in result
        assert "error" in result["ticket_status"]


@pytest.mark.asyncio
async def test_status_scope_available(seeded_db):
    """Test status query with scope='available'."""
    with patch("herd_mcp.db.get_connection", return_value=seeded_db):
        result = await status.execute(scope="available", agent_name="steve")

        assert result["scope"] == "available"
        assert "available_agents" in result

        # fresco and steve should be available (no active instances)
        available_codes = [a["agent_code"] for a in result["available_agents"]]
        assert "fresco" in available_codes
        assert "steve" in available_codes
        assert "mason" not in available_codes  # mason has active instance


@pytest.mark.asyncio
async def test_status_scope_blocked(seeded_db):
    """Test status query with scope='blocked'."""
    with patch("herd_mcp.db.get_connection", return_value=seeded_db):
        result = await status.execute(scope="blocked", agent_name="steve")

        assert result["scope"] == "blocked"
        assert "blockers" in result
        assert len(result["blockers"]) == 1
        assert result["blockers"][0]["ticket_code"] == "DBC-93"


@pytest.mark.asyncio
async def test_status_scope_unknown_defaults_to_all(seeded_db):
    """Test status query with unknown scope defaults to 'all'."""
    with patch("herd_mcp.db.get_connection", return_value=seeded_db):
        result = await status.execute(scope="unknown_scope", agent_name="steve")

        assert result["scope"] == "all"
        assert "agents" in result
        assert "sprint" in result
        assert "blockers" in result


@pytest.mark.asyncio
async def test_status_no_active_sprint(in_memory_db):
    """Test status query when no active sprint exists."""
    with patch("herd_mcp.db.get_connection", return_value=in_memory_db):
        result = await status.execute(scope="sprint", agent_name="steve")

        assert result["scope"] == "sprint"
        assert result["sprint"] is None
