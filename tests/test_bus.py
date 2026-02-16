"""Tests for the in-memory message bus."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from herd_mcp.bus import (
    LEADER_AGENTS,
    MAX_MESSAGE_AGE,
    MECHANICAL_AGENTS,
    Message,
    MessageBus,
    ParsedAddress,
    parse_address,
)

# ---------------------------------------------------------------------------
# Address parsing tests
# ---------------------------------------------------------------------------


class TestParseAddress:
    """Test address parsing for all seven documented formats."""

    def test_agent_only(self) -> None:
        """Parse bare agent name: mason."""
        result = parse_address("mason")
        assert result == ParsedAddress(agent="mason", instance=None, team=None)

    def test_agent_with_team(self) -> None:
        """Parse agent@team: mason@avalon."""
        result = parse_address("mason@avalon")
        assert result == ParsedAddress(agent="mason", instance=None, team="avalon")

    def test_agent_instance_team(self) -> None:
        """Parse agent.instance@team: mason.inst-abc@avalon."""
        result = parse_address("mason.inst-abc@avalon")
        assert result == ParsedAddress(
            agent="mason", instance="inst-abc", team="avalon"
        )

    def test_anyone_bare(self) -> None:
        """Parse @anyone broadcast."""
        result = parse_address("@anyone")
        assert result == ParsedAddress(agent="@anyone", instance=None, team=None)

    def test_anyone_with_team(self) -> None:
        """Parse @anyone@avalon broadcast with team scope."""
        result = parse_address("@anyone@avalon")
        assert result == ParsedAddress(agent="@anyone", instance=None, team="avalon")

    def test_everyone_bare(self) -> None:
        """Parse @everyone broadcast."""
        result = parse_address("@everyone")
        assert result == ParsedAddress(agent="@everyone", instance=None, team=None)

    def test_everyone_with_team(self) -> None:
        """Parse @everyone@avalon broadcast with team scope."""
        result = parse_address("@everyone@avalon")
        assert result == ParsedAddress(agent="@everyone", instance=None, team="avalon")


# ---------------------------------------------------------------------------
# MessageBus send/read tests
# ---------------------------------------------------------------------------


class TestMessageBusSendRead:
    """Test basic send and read cycle."""

    @pytest.mark.asyncio
    async def test_direct_send_read(self) -> None:
        """Send to mason, read as mason returns the message."""
        bus = MessageBus()
        msg = await bus.send("steve@avalon", "mason", "build the thing")

        assert msg.id
        assert msg.from_addr == "steve@avalon"
        assert msg.to_addr == "mason"
        assert msg.body == "build the thing"
        assert msg.priority == "normal"

        inbox = await bus.read("mason")
        assert len(inbox) == 1
        assert inbox[0].id == msg.id

    @pytest.mark.asyncio
    async def test_direct_message_consumed(self) -> None:
        """Direct messages are consumed on read and not returned again."""
        bus = MessageBus()
        await bus.send("steve", "mason", "first task")

        first_read = await bus.read("mason")
        assert len(first_read) == 1

        second_read = await bus.read("mason")
        assert len(second_read) == 0

    @pytest.mark.asyncio
    async def test_empty_inbox(self) -> None:
        """Reading with no pending messages returns empty list."""
        bus = MessageBus()
        inbox = await bus.read("mason")
        assert inbox == []

    @pytest.mark.asyncio
    async def test_message_not_delivered_to_wrong_agent(self) -> None:
        """Messages to mason are not delivered to fresco."""
        bus = MessageBus()
        await bus.send("steve", "mason", "for mason only")

        inbox = await bus.read("fresco")
        assert len(inbox) == 0

        # mason should still get it
        inbox = await bus.read("mason")
        assert len(inbox) == 1


# ---------------------------------------------------------------------------
# Team scoping tests
# ---------------------------------------------------------------------------


class TestTeamScoping:
    """Test that team-scoped messages don't leak across teams."""

    @pytest.mark.asyncio
    async def test_team_scoped_delivery(self) -> None:
        """mason@avalon reaches mason on team avalon."""
        bus = MessageBus()
        await bus.send("steve@avalon", "mason@avalon", "avalon task")

        inbox = await bus.read("mason", team="avalon")
        assert len(inbox) == 1

    @pytest.mark.asyncio
    async def test_team_scoped_isolation(self) -> None:
        """mason@avalon does NOT reach mason on team metropolis."""
        bus = MessageBus()
        await bus.send("steve@avalon", "mason@avalon", "avalon only")

        inbox = await bus.read("mason", team="metropolis")
        assert len(inbox) == 0

    @pytest.mark.asyncio
    async def test_unscoped_message_reaches_any_team(self) -> None:
        """Bare 'mason' reaches mason regardless of team."""
        bus = MessageBus()
        await bus.send("steve", "mason", "for any mason")

        inbox = await bus.read("mason", team="avalon")
        assert len(inbox) == 1

    @pytest.mark.asyncio
    async def test_instance_scoped_message(self) -> None:
        """mason.inst-abc@avalon only matches instance inst-abc."""
        bus = MessageBus()
        await bus.send("steve", "mason.inst-abc@avalon", "instance specific")

        # Wrong instance
        inbox = await bus.read("mason", instance="inst-xyz", team="avalon")
        assert len(inbox) == 0

        # Right instance
        inbox = await bus.read("mason", instance="inst-abc", team="avalon")
        assert len(inbox) == 1


# ---------------------------------------------------------------------------
# @anyone competing consumer tests
# ---------------------------------------------------------------------------


class TestAnyoneConsumer:
    """Test @anyone competing consumer pattern."""

    @pytest.mark.asyncio
    async def test_anyone_first_reader_consumes(self) -> None:
        """@anyone message is consumed by the first qualified reader."""
        bus = MessageBus()
        await bus.send("steve", "@anyone", "who wants this?")

        # mason reads first — gets it
        inbox = await bus.read("mason")
        assert len(inbox) == 1

        # fresco reads second — empty
        inbox = await bus.read("fresco")
        assert len(inbox) == 0

    @pytest.mark.asyncio
    async def test_anyone_excludes_mechanical(self) -> None:
        """@anyone messages are not delivered to mechanical agents (rook, vigil)."""
        bus = MessageBus()
        await bus.send("steve", "@anyone", "not for bots")

        for mech in MECHANICAL_AGENTS:
            inbox = await bus.read(mech)
            assert (
                len(inbox) == 0
            ), f"Mechanical agent {mech} should not receive @anyone"

        # Non-mechanical agent should get it
        inbox = await bus.read("mason")
        assert len(inbox) == 1

    @pytest.mark.asyncio
    async def test_anyone_with_team_scope(self) -> None:
        """@anyone@avalon only matches agents on team avalon."""
        bus = MessageBus()
        await bus.send("steve", "@anyone@avalon", "avalon volunteers only")

        # Wrong team
        inbox = await bus.read("mason", team="metropolis")
        assert len(inbox) == 0

        # Right team
        inbox = await bus.read("fresco", team="avalon")
        assert len(inbox) == 1


# ---------------------------------------------------------------------------
# @everyone broadcast tests
# ---------------------------------------------------------------------------


class TestEveryoneBroadcast:
    """Test @everyone broadcast pattern."""

    @pytest.mark.asyncio
    async def test_everyone_all_agents_get_it(self) -> None:
        """@everyone delivers to every agent that reads."""
        bus = MessageBus()
        await bus.send("steve", "@everyone", "team standup in 5")

        inbox_mason = await bus.read("mason", instance="inst-m1")
        assert len(inbox_mason) == 1

        inbox_fresco = await bus.read("fresco", instance="inst-f1")
        assert len(inbox_fresco) == 1

        # Same agent reading again should NOT get it again
        inbox_mason_again = await bus.read("mason", instance="inst-m1")
        assert len(inbox_mason_again) == 0

    @pytest.mark.asyncio
    async def test_everyone_tracked_by_read_by(self) -> None:
        """@everyone messages track which instances have read them."""
        bus = MessageBus()
        msg = await bus.send("steve", "@everyone", "broadcast")

        await bus.read("mason", instance="inst-m1")
        assert "inst-m1" in msg.read_by

        await bus.read("fresco", instance="inst-f1")
        assert "inst-f1" in msg.read_by

    @pytest.mark.asyncio
    async def test_everyone_with_team_scope(self) -> None:
        """@everyone@avalon only reaches agents on team avalon."""
        bus = MessageBus()
        await bus.send("steve", "@everyone@avalon", "avalon broadcast")

        inbox = await bus.read("mason", instance="inst-m1", team="metropolis")
        assert len(inbox) == 0

        inbox = await bus.read("mason", instance="inst-m2", team="avalon")
        assert len(inbox) == 1


# ---------------------------------------------------------------------------
# Leader visibility tests
# ---------------------------------------------------------------------------


class TestLeaderVisibility:
    """Test that leaders see all @team traffic for their team."""

    @pytest.mark.asyncio
    async def test_leader_sees_team_direct_messages(self) -> None:
        """Steve (leader) sees messages sent to mason@avalon."""
        bus = MessageBus()
        await bus.send("fresco@avalon", "mason@avalon", "hey mason")

        # Steve is a leader and on team avalon — should see it
        assert "steve" in LEADER_AGENTS
        inbox = await bus.read("steve", team="avalon")
        assert len(inbox) == 1

    @pytest.mark.asyncio
    async def test_leader_does_not_see_other_team_traffic(self) -> None:
        """Steve on avalon does NOT see messages scoped to metropolis."""
        bus = MessageBus()
        await bus.send("leonardo@metro", "mason@metropolis", "metro task")

        inbox = await bus.read("steve", team="avalon")
        assert len(inbox) == 0

    @pytest.mark.asyncio
    async def test_non_leader_does_not_get_visibility(self) -> None:
        """Non-leader agent does NOT see other agents' team-scoped messages."""
        bus = MessageBus()
        await bus.send("steve@avalon", "mason@avalon", "for mason")

        # Fresco is not a leader — should not see mason's messages
        assert "fresco" not in LEADER_AGENTS
        inbox = await bus.read("fresco", team="avalon")
        assert len(inbox) == 0


# ---------------------------------------------------------------------------
# Message expiry tests
# ---------------------------------------------------------------------------


class TestMessageExpiry:
    """Test periodic pruning of expired messages."""

    @pytest.mark.asyncio
    async def test_expired_messages_pruned(self) -> None:
        """Messages older than MAX_MESSAGE_AGE are pruned on read."""
        bus = MessageBus()
        # Manually insert an expired message
        expired_msg = Message(
            id="expired-1",
            from_addr="steve",
            to_addr="mason",
            body="old news",
            sent_at=datetime.now(UTC) - MAX_MESSAGE_AGE - timedelta(minutes=5),
        )
        bus._messages.append(expired_msg)

        inbox = await bus.read("mason")
        assert len(inbox) == 0

    @pytest.mark.asyncio
    async def test_fresh_messages_not_pruned(self) -> None:
        """Messages within MAX_MESSAGE_AGE are not pruned."""
        bus = MessageBus()
        msg = await bus.send("steve", "mason", "fresh message")

        inbox = await bus.read("mason")
        assert len(inbox) == 1
        assert inbox[0].id == msg.id


# ---------------------------------------------------------------------------
# Priority field tests
# ---------------------------------------------------------------------------


class TestPriority:
    """Test priority field handling."""

    @pytest.mark.asyncio
    async def test_default_priority_is_normal(self) -> None:
        """Messages default to normal priority."""
        bus = MessageBus()
        msg = await bus.send("steve", "mason", "regular task")
        assert msg.priority == "normal"

    @pytest.mark.asyncio
    async def test_urgent_priority(self) -> None:
        """Urgent priority is preserved."""
        bus = MessageBus()
        msg = await bus.send("steve", "mason", "fire", priority="urgent")
        assert msg.priority == "urgent"


# ---------------------------------------------------------------------------
# Multiple messages ordering
# ---------------------------------------------------------------------------


class TestMessageOrdering:
    """Test that messages are delivered in send order."""

    @pytest.mark.asyncio
    async def test_fifo_ordering(self) -> None:
        """Messages are delivered in FIFO order."""
        bus = MessageBus()
        await bus.send("steve", "mason", "first")
        await bus.send("steve", "mason", "second")
        await bus.send("steve", "mason", "third")

        inbox = await bus.read("mason")
        assert len(inbox) == 3
        assert inbox[0].body == "first"
        assert inbox[1].body == "second"
        assert inbox[2].body == "third"
