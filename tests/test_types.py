"""Tests for herd_core.types module — entities, events, enums, and return types."""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from herd_core.types import (
    AgentRecord,
    AgentState,
    CommitInfo,
    DecisionRecord,
    Entity,
    Event,
    LifecycleEvent,
    ModelRecord,
    PostResult,
    PREvent,
    PRRecord,
    ReviewEvent,
    ReviewRecord,
    SpawnContext,
    SpawnResult,
    SprintRecord,
    ThreadMessage,
    TicketEvent,
    TicketPriority,
    TicketRecord,
    TokenEvent,
    TransitionResult,
)


class TestEntityBase:
    """Test Entity base class behavior."""

    def test_entity_id_required(self) -> None:
        """Entity requires an id field."""
        entity = Entity(id="test-001")
        assert entity.id == "test-001"

    def test_entity_timestamps_optional(self) -> None:
        """Entity timestamps default to None."""
        entity = Entity(id="test-001")
        assert entity.created_at is None
        assert entity.modified_at is None
        assert entity.deleted_at is None

    def test_entity_is_mutable(self) -> None:
        """Entities can be modified after creation."""
        entity = Entity(id="test-001")
        entity.created_at = datetime.now(timezone.utc)
        entity.modified_at = datetime.now(timezone.utc)
        assert entity.created_at is not None
        assert entity.modified_at is not None


class TestEventBase:
    """Test Event base class behavior."""

    def test_event_required_fields(self) -> None:
        """Event requires entity_id and event_type."""
        event = Event(entity_id="test-001", event_type="test_event")
        assert event.entity_id == "test-001"
        assert event.event_type == "test_event"

    def test_event_created_at_optional(self) -> None:
        """Event created_at defaults to None."""
        event = Event(entity_id="test-001", event_type="test_event")
        assert event.created_at is None

    def test_event_is_frozen(self) -> None:
        """Events are immutable after creation."""
        event = Event(entity_id="test-001", event_type="test_event")
        with pytest.raises(FrozenInstanceError):
            event.entity_id = "test-002"  # type: ignore[misc]


class TestEntitySubclasses:
    """Test all 7 entity subclasses."""

    def test_agent_record_minimal_construction(self) -> None:
        """AgentRecord instantiates with just id."""
        agent = AgentRecord(id="agent-001")
        assert agent.id == "agent-001"
        assert agent.agent == ""
        assert agent.state == AgentState.SPAWNING

    def test_agent_record_is_mutable(self) -> None:
        """AgentRecord can be modified after creation."""
        agent = AgentRecord(id="agent-001")
        agent.state = AgentState.RUNNING
        agent.ticket_id = "DBC-137"
        assert agent.state == AgentState.RUNNING
        assert agent.ticket_id == "DBC-137"

    def test_ticket_record_minimal_construction(self) -> None:
        """TicketRecord instantiates with just id."""
        ticket = TicketRecord(id="DBC-137")
        assert ticket.id == "DBC-137"
        assert ticket.title == ""
        assert ticket.priority == TicketPriority.NONE

    def test_pr_record_minimal_construction(self) -> None:
        """PRRecord instantiates with just id."""
        pr = PRRecord(id="pr-123")
        assert pr.id == "pr-123"
        assert pr.branch == ""
        assert pr.base == "main"

    def test_decision_record_minimal_construction(self) -> None:
        """DecisionRecord instantiates with just id."""
        decision = DecisionRecord(id="hdr-0001")
        assert decision.id == "hdr-0001"
        assert decision.status == "accepted"

    def test_review_record_minimal_construction(self) -> None:
        """ReviewRecord instantiates with just id."""
        review = ReviewRecord(id="review-001")
        assert review.id == "review-001"
        assert review.findings_count == 0

    def test_model_record_minimal_construction(self) -> None:
        """ModelRecord instantiates with just id."""
        model = ModelRecord(id="model-001")
        assert model.id == "model-001"
        assert model.input_cost_per_token == Decimal("0")

    def test_sprint_record_minimal_construction(self) -> None:
        """SprintRecord instantiates with just id."""
        sprint = SprintRecord(id="sprint-001")
        assert sprint.id == "sprint-001"
        assert sprint.number == 0


class TestEventSubclasses:
    """Test all 5 event subclasses."""

    def test_lifecycle_event_required_fields(self) -> None:
        """LifecycleEvent requires entity_id and event_type."""
        event = LifecycleEvent(entity_id="agent-001", event_type="spawned")
        assert event.entity_id == "agent-001"
        assert event.event_type == "spawned"

    def test_lifecycle_event_is_frozen(self) -> None:
        """LifecycleEvent is immutable."""
        event = LifecycleEvent(entity_id="agent-001", event_type="spawned")
        with pytest.raises(FrozenInstanceError):
            event.detail = "modified"  # type: ignore[misc]

    def test_ticket_event_required_fields(self) -> None:
        """TicketEvent requires entity_id and event_type."""
        event = TicketEvent(
            entity_id="DBC-137",
            event_type="transition",
            previous_status="backlog",
            new_status="in_progress",
        )
        assert event.entity_id == "DBC-137"
        assert event.previous_status == "backlog"
        assert event.new_status == "in_progress"

    def test_ticket_event_is_frozen(self) -> None:
        """TicketEvent is immutable."""
        event = TicketEvent(
            entity_id="DBC-137",
            event_type="transition",
            previous_status="backlog",
            new_status="in_progress",
        )
        with pytest.raises(FrozenInstanceError):
            event.new_status = "done"  # type: ignore[misc]

    def test_pr_event_required_fields(self) -> None:
        """PREvent requires entity_id and event_type."""
        event = PREvent(entity_id="DBC-137", event_type="commit", pr_id="pr-123")
        assert event.entity_id == "DBC-137"
        assert event.pr_id == "pr-123"

    def test_pr_event_is_frozen(self) -> None:
        """PREvent is immutable."""
        event = PREvent(entity_id="DBC-137", event_type="commit", pr_id="pr-123")
        with pytest.raises(FrozenInstanceError):
            event.detail = "modified"  # type: ignore[misc]

    def test_review_event_required_fields(self) -> None:
        """ReviewEvent requires entity_id and event_type."""
        event = ReviewEvent(
            entity_id="DBC-137",
            event_type="review_submitted",
            review_id="review-001",
            pr_id="pr-123",
            verdict="pass",
        )
        assert event.entity_id == "DBC-137"
        assert event.verdict == "pass"

    def test_review_event_is_frozen(self) -> None:
        """ReviewEvent is immutable."""
        event = ReviewEvent(
            entity_id="DBC-137",
            event_type="review_submitted",
            review_id="review-001",
            pr_id="pr-123",
            verdict="pass",
        )
        with pytest.raises(FrozenInstanceError):
            event.verdict = "fail"  # type: ignore[misc]

    def test_token_event_required_fields(self) -> None:
        """TokenEvent requires entity_id and event_type."""
        event = TokenEvent(
            entity_id="DBC-137",
            event_type="usage",
            model="claude-sonnet-4-5",
            input_tokens=1000,
            output_tokens=500,
            total_tokens=1500,
            cost_usd=Decimal("0.05"),
        )
        assert event.total_tokens == 1500
        assert event.cost_usd == Decimal("0.05")
        assert event.model == "claude-sonnet-4-5"

    def test_token_event_is_frozen(self) -> None:
        """TokenEvent is immutable."""
        event = TokenEvent(
            entity_id="DBC-137",
            event_type="usage",
            model="claude-sonnet-4-5",
            total_tokens=1500,
        )
        with pytest.raises(FrozenInstanceError):
            event.total_tokens = 2000  # type: ignore[misc]


class TestEnums:
    """Test enum definitions."""

    def test_agent_state_values(self) -> None:
        """AgentState should have all 6 lifecycle states."""
        assert AgentState.SPAWNING.value == "spawning"
        assert AgentState.RUNNING.value == "running"
        assert AgentState.BLOCKED.value == "blocked"
        assert AgentState.COMPLETED.value == "completed"
        assert AgentState.FAILED.value == "failed"
        assert AgentState.STOPPED.value == "stopped"

    def test_ticket_priority_values(self) -> None:
        """TicketPriority should have correct numeric values."""
        assert TicketPriority.NONE.value == 0
        assert TicketPriority.URGENT.value == 1
        assert TicketPriority.HIGH.value == 2
        assert TicketPriority.NORMAL.value == 3
        assert TicketPriority.LOW.value == 4


class TestReturnTypes:
    """Test adapter return types are frozen dataclasses."""

    def test_spawn_context_required_fields(self) -> None:
        """SpawnContext requires all context fields."""
        ctx = SpawnContext(
            role_definition="Grunt role definition",
            craft_standards="Backend craft standards",
            project_guidelines="CLAUDE.md content",
            assignment="DBC-137 assignment text",
        )
        assert ctx.role_definition == "Grunt role definition"
        assert ctx.assignment == "DBC-137 assignment text"

    def test_spawn_context_is_frozen(self) -> None:
        """SpawnContext is immutable."""
        ctx = SpawnContext(
            role_definition="test",
            craft_standards="test",
            project_guidelines="test",
            assignment="test",
        )
        with pytest.raises(FrozenInstanceError):
            ctx.assignment = "modified"  # type: ignore[misc]

    def test_spawn_result_is_frozen(self) -> None:
        """SpawnResult is immutable."""
        result = SpawnResult(
            instance_id="agent-001",
            agent="mason",
            ticket_id="DBC-137",
            model="claude-sonnet-4-5",
            worktree="/tmp/test",
            branch="test-branch",
            spawned_at=datetime.now(timezone.utc),
        )
        with pytest.raises(FrozenInstanceError):
            result.agent = "fresco"  # type: ignore[misc]

    def test_transition_result_is_frozen(self) -> None:
        """TransitionResult is immutable."""
        result = TransitionResult(
            ticket_id="DBC-137",
            previous_status="backlog",
            new_status="in_progress",
            event_type="transition",
        )
        with pytest.raises(FrozenInstanceError):
            result.new_status = "done"  # type: ignore[misc]

    def test_post_result_is_frozen(self) -> None:
        """PostResult is immutable."""
        result = PostResult(
            message_id="msg-001", channel="#herd-feed", timestamp="1234567890"
        )
        with pytest.raises(FrozenInstanceError):
            result.channel = "#other"  # type: ignore[misc]

    def test_thread_message_is_frozen(self) -> None:
        """ThreadMessage is immutable."""
        msg = ThreadMessage(author="Mason", text="Test message", timestamp="1234567890")
        with pytest.raises(FrozenInstanceError):
            msg.text = "Modified"  # type: ignore[misc]

    def test_commit_info_is_frozen(self) -> None:
        """CommitInfo is immutable."""
        commit = CommitInfo(
            sha="abc123",
            message="Test commit",
            author="Mason",
            timestamp=datetime.now(timezone.utc),
        )
        with pytest.raises(FrozenInstanceError):
            commit.message = "Modified"  # type: ignore[misc]
