"""Tests for the herd_checkin tool and CheckinRegistry."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from herd_mcp.bus import (
    CheckinEntry,
    CheckinRegistry,
    Message,
    MessageBus,
    STALE_THRESHOLD,
    UNRESPONSIVE_THRESHOLD,
)
from herd_mcp.tools.checkin import (
    LEADER_AGENTS,
    MECHANICAL_AGENTS,
    SENIOR_AGENTS,
    TIER_CONFIG,
    _build_context_pane,
    _filter_messages_by_tier,
    _get_tier,
    execute,
)


# ---------------------------------------------------------------------------
# CheckinRegistry tests
# ---------------------------------------------------------------------------


class TestCheckinRegistry:
    """Test the in-memory checkin registry."""

    @pytest.mark.asyncio
    async def test_record_and_get_active(self) -> None:
        """Recording a checkin makes it visible in get_active."""
        reg = CheckinRegistry()
        await reg.record("mason.inst-001@avalon", "working on DBC-99", "mason", "avalon")

        active = reg.get_active()
        assert "mason.inst-001@avalon" in active
        assert active["mason.inst-001@avalon"].status == "working on DBC-99"
        assert active["mason.inst-001@avalon"].agent == "mason"
        assert active["mason.inst-001@avalon"].team == "avalon"

    @pytest.mark.asyncio
    async def test_record_overwrites_previous(self) -> None:
        """A new checkin from the same address overwrites the previous one."""
        reg = CheckinRegistry()
        await reg.record("mason.inst-001@avalon", "phase 1", "mason", "avalon")
        await reg.record("mason.inst-001@avalon", "phase 2", "mason", "avalon")

        active = reg.get_active()
        assert active["mason.inst-001@avalon"].status == "phase 2"

    @pytest.mark.asyncio
    async def test_record_with_ticket(self) -> None:
        """Recording a checkin with a ticket ID stores it."""
        reg = CheckinRegistry()
        await reg.record(
            "mason.inst-001@avalon", "working", "mason", "avalon", ticket="DBC-99"
        )
        active = reg.get_active()
        assert active["mason.inst-001@avalon"].ticket == "DBC-99"

    @pytest.mark.asyncio
    async def test_get_active_filters_by_team(self) -> None:
        """get_active with team parameter filters to that team only."""
        reg = CheckinRegistry()
        await reg.record("mason.inst-001@avalon", "working", "mason", "avalon")
        await reg.record("fresco.inst-002@metro", "designing", "fresco", "metro")

        avalon_active = reg.get_active(team="avalon")
        assert "mason.inst-001@avalon" in avalon_active
        assert "fresco.inst-002@metro" not in avalon_active

        metro_active = reg.get_active(team="metro")
        assert "fresco.inst-002@metro" in metro_active
        assert "mason.inst-001@avalon" not in metro_active

    @pytest.mark.asyncio
    async def test_get_active_excludes_unresponsive(self) -> None:
        """Entries older than UNRESPONSIVE_THRESHOLD are excluded."""
        reg = CheckinRegistry()
        await reg.record("mason.inst-001@avalon", "working", "mason", "avalon")

        # Manually backdate the entry
        entry = reg._entries["mason.inst-001@avalon"]
        entry.timestamp = datetime.now(UTC) - UNRESPONSIVE_THRESHOLD - timedelta(seconds=1)

        active = reg.get_active()
        assert len(active) == 0

    def test_staleness_none_for_fresh(self) -> None:
        """Fresh entries return None staleness."""
        reg = CheckinRegistry()
        reg._entries["mason@avalon"] = CheckinEntry(
            status="working",
            timestamp=datetime.now(UTC),
            agent="mason",
            team="avalon",
        )
        assert reg.staleness("mason@avalon") is None

    def test_staleness_stale(self) -> None:
        """Entries past STALE_THRESHOLD but within UNRESPONSIVE_THRESHOLD are stale."""
        reg = CheckinRegistry()
        reg._entries["mason@avalon"] = CheckinEntry(
            status="working",
            timestamp=datetime.now(UTC) - STALE_THRESHOLD - timedelta(seconds=1),
            agent="mason",
            team="avalon",
        )
        assert reg.staleness("mason@avalon") == "stale"

    def test_staleness_unresponsive(self) -> None:
        """Entries past UNRESPONSIVE_THRESHOLD are unresponsive."""
        reg = CheckinRegistry()
        reg._entries["mason@avalon"] = CheckinEntry(
            status="working",
            timestamp=datetime.now(UTC) - UNRESPONSIVE_THRESHOLD - timedelta(seconds=1),
            agent="mason",
            team="avalon",
        )
        assert reg.staleness("mason@avalon") == "unresponsive"

    def test_staleness_unknown_address(self) -> None:
        """Staleness for unknown address returns None."""
        reg = CheckinRegistry()
        assert reg.staleness("nobody@nowhere") is None


# ---------------------------------------------------------------------------
# Tier determination tests
# ---------------------------------------------------------------------------


class TestTierDetermination:
    """Test agent tier classification."""

    def test_leader_tier(self) -> None:
        """Leaders are classified correctly."""
        for agent in LEADER_AGENTS:
            assert _get_tier(agent) == "leader"

    def test_senior_tier(self) -> None:
        """Senior agents are classified correctly."""
        for agent in SENIOR_AGENTS:
            assert _get_tier(agent) == "senior"

    def test_mechanical_tier(self) -> None:
        """Mechanical agents are classified correctly."""
        for agent in MECHANICAL_AGENTS:
            assert _get_tier(agent) == "mechanical"

    def test_execution_tier(self) -> None:
        """Everything else is execution tier."""
        assert _get_tier("mason") == "execution"
        assert _get_tier("fresco") == "execution"
        assert _get_tier("gauss") == "execution"


# ---------------------------------------------------------------------------
# Checkin execute tests
# ---------------------------------------------------------------------------


class TestCheckinExecute:
    """Test the checkin execute function."""

    @pytest.mark.asyncio
    async def test_basic_checkin_returns_heartbeat_ack(self) -> None:
        """Basic checkin returns heartbeat_ack: True."""
        bus = MessageBus()
        reg = CheckinRegistry()

        result = await execute(
            "working on tests", "mason", bus=bus, checkin_registry=reg
        )

        assert result["heartbeat_ack"] is True
        assert isinstance(result["messages"], list)

    @pytest.mark.asyncio
    async def test_messages_drained(self) -> None:
        """Pending messages are drained from the bus on checkin."""
        bus = MessageBus()
        reg = CheckinRegistry()

        await bus.send("steve@avalon", "mason", "do the thing", msg_type="directive")

        result = await execute(
            "checking in", "mason", bus=bus, checkin_registry=reg
        )

        assert len(result["messages"]) == 1
        assert result["messages"][0]["body"] == "do the thing"
        assert result["messages"][0]["type"] == "directive"
        assert result["messages"][0]["from"] == "steve@avalon"

    @pytest.mark.asyncio
    async def test_messages_consumed_after_drain(self) -> None:
        """After checkin drains messages, they are gone from the bus."""
        bus = MessageBus()
        reg = CheckinRegistry()

        await bus.send("steve", "mason", "task 1")

        await execute("checking in", "mason", bus=bus, checkin_registry=reg)

        # Second checkin should have no messages
        result = await execute("checking in again", "mason", bus=bus, checkin_registry=reg)
        assert len(result["messages"]) == 0

    @pytest.mark.asyncio
    async def test_mechanical_agents_get_no_context(self) -> None:
        """Mechanical agents get context: null."""
        bus = MessageBus()
        reg = CheckinRegistry()

        # Add some team activity
        await reg.record("mason@avalon", "working", "mason", "avalon")

        with patch.dict("os.environ", {"HERD_TEAM": "avalon"}):
            result = await execute(
                "monitoring", "rook", bus=bus, checkin_registry=reg
            )

        assert result["context"] is None

    @pytest.mark.asyncio
    async def test_mechanical_agents_only_get_directives(self) -> None:
        """Mechanical agents only receive directive messages."""
        bus = MessageBus()
        reg = CheckinRegistry()

        # Send different message types to rook
        await bus.send("steve", "rook", "do this now", msg_type="directive")
        await bus.send("mason", "rook", "fyi update", msg_type="inform")
        await bus.send("wardenstein", "rook", "quality issue", msg_type="flag")

        result = await execute(
            "monitoring", "rook", bus=bus, checkin_registry=reg
        )

        assert len(result["messages"]) == 1
        assert result["messages"][0]["type"] == "directive"
        assert result["messages"][0]["body"] == "do this now"

    @pytest.mark.asyncio
    async def test_execution_agents_get_all_message_types(self) -> None:
        """Execution agents receive all three message types."""
        bus = MessageBus()
        reg = CheckinRegistry()

        await bus.send("steve", "mason", "build it", msg_type="directive")
        await bus.send("fresco", "mason", "heads up", msg_type="inform")
        await bus.send("wardenstein", "mason", "fix this", msg_type="flag")

        result = await execute(
            "working", "mason", bus=bus, checkin_registry=reg
        )

        assert len(result["messages"]) == 3
        types = {m["type"] for m in result["messages"]}
        assert types == {"directive", "inform", "flag"}

    @pytest.mark.asyncio
    async def test_context_pane_built_for_execution_agents(self) -> None:
        """Execution agents get a context pane when team agents are active."""
        bus = MessageBus()
        reg = CheckinRegistry()

        # Register some active agents on the same team
        await reg.record("fresco.inst-002@avalon", "designing UI", "fresco", "avalon")
        await reg.record("steve.inst-003@avalon", "coordinating", "steve", "avalon")

        with patch.dict("os.environ", {"HERD_TEAM": "avalon"}):
            result = await execute(
                "working", "mason", bus=bus, checkin_registry=reg
            )

        assert result["context"] is not None
        assert "agents active" in result["context"]

    @pytest.mark.asyncio
    async def test_heartbeat_recorded_in_registry(self) -> None:
        """Checkin records the agent's status in the checkin registry."""
        bus = MessageBus()
        reg = CheckinRegistry()

        with patch.dict("os.environ", {"HERD_TEAM": "avalon", "HERD_INSTANCE_ID": "inst-001"}):
            await execute(
                "writing tests", "mason", bus=bus, checkin_registry=reg
            )

        active = reg.get_active()
        assert len(active) == 1
        addr = list(active.keys())[0]
        assert "mason" in addr
        assert active[addr].status == "writing tests"

    @pytest.mark.asyncio
    async def test_no_bus_still_works(self) -> None:
        """Checkin works even without a bus (returns empty messages)."""
        reg = CheckinRegistry()

        result = await execute("working", "mason", checkin_registry=reg)

        assert result["heartbeat_ack"] is True
        assert result["messages"] == []

    @pytest.mark.asyncio
    async def test_no_registry_still_works(self) -> None:
        """Checkin works even without a registry (no heartbeat, no context)."""
        bus = MessageBus()

        result = await execute("working", "mason", bus=bus)

        assert result["heartbeat_ack"] is True
        assert result["context"] is None

    @pytest.mark.asyncio
    async def test_leader_gets_larger_context_budget(self) -> None:
        """Leaders have a 500-token context budget (vs 200 for execution)."""
        assert TIER_CONFIG["leader"]["context_budget"] == 500
        assert TIER_CONFIG["execution"]["context_budget"] == 200


# ---------------------------------------------------------------------------
# Context pane tests
# ---------------------------------------------------------------------------


class TestContextPane:
    """Test the context pane builder."""

    def test_empty_when_no_other_agents(self) -> None:
        """Context pane is None when no other agents are active."""
        reg = CheckinRegistry()
        result = _build_context_pane("mason", "avalon", None, 200, reg)
        assert result is None

    @pytest.mark.asyncio
    async def test_populated_when_team_agents_active(self) -> None:
        """Context pane contains team agent status when agents are active."""
        reg = CheckinRegistry()
        await reg.record("fresco.inst-002@avalon", "designing", "fresco", "avalon")

        result = _build_context_pane("mason", "avalon", None, 200, reg)
        assert result is not None
        assert "fresco" in result
        assert "designing" in result
        assert "agents active" in result

    @pytest.mark.asyncio
    async def test_excludes_self(self) -> None:
        """Context pane does not include the calling agent."""
        reg = CheckinRegistry()
        await reg.record("mason.inst-001@avalon", "working", "mason", "avalon")
        await reg.record("fresco.inst-002@avalon", "designing", "fresco", "avalon")

        result = _build_context_pane("mason", "avalon", None, 200, reg)
        # Should only show fresco, not mason
        assert result is not None
        assert "fresco" in result
        # mason.inst-001 should not appear in the pane
        assert "mason.inst-001" not in result

    @pytest.mark.asyncio
    async def test_budget_enforcement(self) -> None:
        """Context pane is truncated when it exceeds the budget."""
        reg = CheckinRegistry()
        # Add many agents to exceed a very small budget
        for i in range(20):
            await reg.record(
                f"agent-{i}.inst-{i:03d}@avalon",
                f"doing something very important with a long description number {i}",
                f"agent-{i}",
                "avalon",
            )

        # Very small budget (10 tokens ~ 40 chars)
        result = _build_context_pane("mason", "avalon", None, 10, reg)
        assert result is not None
        assert len(result) <= 40  # 10 tokens * 4 chars
        assert result.endswith("...")

    def test_zero_budget_returns_none(self) -> None:
        """Zero budget returns None (mechanical agents)."""
        reg = CheckinRegistry()
        result = _build_context_pane("rook", "avalon", None, 0, reg)
        assert result is None

    @pytest.mark.asyncio
    async def test_graph_filtering_graceful_fallback(self) -> None:
        """When graph is unavailable, falls back to team-based filtering."""
        reg = CheckinRegistry()
        await reg.record("fresco.inst-002@avalon", "designing", "fresco", "avalon")

        # Mock graph to simulate unavailability — is_available returns False
        with patch("herd_mcp.graph.is_available", return_value=False):
            result = _build_context_pane("mason", "avalon", "DBC-99", 200, reg)
        assert result is not None
        assert "fresco" in result

    @pytest.mark.asyncio
    async def test_graph_filtering_narrows_to_connected(self) -> None:
        """When graph is available, context pane filters to connected agents."""
        reg = CheckinRegistry()
        await reg.record("fresco.inst-002@avalon", "designing", "fresco", "avalon")
        await reg.record("gauss.inst-003@avalon", "analyzing", "gauss", "avalon")

        # Mock graph to return only fresco as connected
        with patch("herd_mcp.graph.is_available", return_value=True), \
             patch("herd_mcp.graph.query_graph", return_value=[{"a.code": "fresco"}]):
            result = _build_context_pane("mason", "avalon", "DBC-99", 500, reg)

        assert result is not None
        assert "fresco" in result
        assert "gauss" not in result

    @pytest.mark.asyncio
    async def test_staleness_label_in_pane(self) -> None:
        """Stale agents get a staleness label in the context pane."""
        reg = CheckinRegistry()
        await reg.record("fresco.inst-002@avalon", "designing", "fresco", "avalon")

        # Backdate entry to make it stale
        entry = reg._entries["fresco.inst-002@avalon"]
        entry.timestamp = datetime.now(UTC) - STALE_THRESHOLD - timedelta(seconds=1)

        result = _build_context_pane("mason", "avalon", None, 500, reg)
        assert result is not None
        assert "(stale)" in result


# ---------------------------------------------------------------------------
# Message type filtering tests
# ---------------------------------------------------------------------------


class TestMessageTypeFiltering:
    """Test message filtering by tier."""

    def test_execution_gets_all_types(self) -> None:
        """Execution agents receive directive, inform, and flag."""
        messages = [
            Message(id="1", from_addr="steve", to_addr="mason", body="a", type="directive"),
            Message(id="2", from_addr="fresco", to_addr="mason", body="b", type="inform"),
            Message(id="3", from_addr="warden", to_addr="mason", body="c", type="flag"),
        ]
        result = _filter_messages_by_tier(messages, "execution")
        assert len(result) == 3

    def test_mechanical_gets_only_directives(self) -> None:
        """Mechanical agents only receive directive messages."""
        messages = [
            Message(id="1", from_addr="steve", to_addr="rook", body="a", type="directive"),
            Message(id="2", from_addr="fresco", to_addr="rook", body="b", type="inform"),
            Message(id="3", from_addr="warden", to_addr="rook", body="c", type="flag"),
        ]
        result = _filter_messages_by_tier(messages, "mechanical")
        assert len(result) == 1
        assert result[0]["type"] == "directive"

    def test_leader_gets_all_types(self) -> None:
        """Leaders receive all message types."""
        messages = [
            Message(id="1", from_addr="mason", to_addr="steve", body="a", type="directive"),
            Message(id="2", from_addr="fresco", to_addr="steve", body="b", type="inform"),
            Message(id="3", from_addr="warden", to_addr="steve", body="c", type="flag"),
        ]
        result = _filter_messages_by_tier(messages, "leader")
        assert len(result) == 3

    def test_filtered_format(self) -> None:
        """Filtered messages have the correct dict format."""
        messages = [
            Message(
                id="1",
                from_addr="steve@avalon",
                to_addr="mason",
                body="build it",
                type="directive",
                priority="urgent",
            ),
        ]
        result = _filter_messages_by_tier(messages, "execution")
        assert len(result) == 1
        assert result[0] == {
            "from": "steve@avalon",
            "type": "directive",
            "body": "build it",
            "priority": "urgent",
        }


# ---------------------------------------------------------------------------
# Piggyback removal verification tests
# ---------------------------------------------------------------------------


class TestPiggybackRemoved:
    """Verify that piggyback delivery is completely removed from other tools."""

    def test_no_piggyback_function_in_server(self) -> None:
        """_piggyback_messages function should not exist in server module."""
        from herd_mcp import server

        assert not hasattr(server, "_piggyback_messages")

    @pytest.mark.asyncio
    async def test_herd_send_no_pending_messages(self) -> None:
        """herd_send response should not contain _pending_messages."""
        from herd_mcp import server

        # Send a message and check the response format
        with patch.dict("os.environ", {"HERD_AGENT_NAME": "steve"}):
            result = await server.herd_send(
                to="mason",
                message="test",
                agent_name="steve",
            )

        assert "_pending_messages" not in result
        assert "injected" not in result  # stdin injection field also removed
        assert "message_id" in result
        assert "delivered" in result

    @pytest.mark.asyncio
    async def test_herd_send_has_type_field(self) -> None:
        """herd_send response should include the type field."""
        from herd_mcp import server

        result = await server.herd_send(
            to="mason",
            message="build it",
            type="directive",
            agent_name="steve",
        )

        assert result["type"] == "directive"
