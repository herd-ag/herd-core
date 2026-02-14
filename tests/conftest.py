"""Shared test fixtures for herd-core tests.

Provides mock adapters and sample entities/events for testing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from herd_core.types import (
    AgentRecord,
    AgentState,
    DecisionRecord,
    Entity,
    Event,
    LifecycleEvent,
    ModelRecord,
    PREvent,
    PRRecord,
    ReviewEvent,
    ReviewRecord,
    SprintRecord,
    TicketEvent,
    TicketPriority,
    TicketRecord,
    TokenEvent,
)


class MockStore:
    """Mock StoreAdapter implementation for testing queries.

    Stores entities in dicts, events in lists, supports basic filtering.
    """

    def __init__(self) -> None:
        self._entities: dict[type[Entity], dict[str, Entity]] = {}
        self._events: list[Event] = []

    def get(self, entity_type: type[Entity], id: str) -> Entity | None:
        """Retrieve a single entity by ID."""
        store = self._entities.get(entity_type, {})
        entity = store.get(id)
        # Exclude soft-deleted
        if entity and entity.deleted_at is None:
            return entity
        return None

    def list(self, entity_type: type[Entity], **filters: Any) -> list[Entity]:
        """List entities matching filters."""
        store = self._entities.get(entity_type, {})
        results = []
        for entity in store.values():
            # Apply active filter (deleted_at IS NULL)
            if filters.get("active") and entity.deleted_at is not None:
                continue
            # Apply other filters
            match = True
            for key, value in filters.items():
                if key == "active":
                    continue
                if hasattr(entity, key):
                    entity_value = getattr(entity, key)
                    if entity_value != value:
                        match = False
                        break
            if match:
                results.append(entity)
        return results

    def save(self, record: Entity) -> str:
        """Save an entity (insert or update)."""
        entity_type = type(record)
        if entity_type not in self._entities:
            self._entities[entity_type] = {}

        # Set modified_at
        record.modified_at = datetime.now(timezone.utc)

        self._entities[entity_type][record.id] = record
        return record.id

    def delete(self, entity_type: type[Entity], id: str) -> None:
        """Soft-delete an entity."""
        store = self._entities.get(entity_type, {})
        if id in store:
            store[id].deleted_at = datetime.now(timezone.utc)

    def append(self, event: Event) -> None:
        """Append an immutable event."""
        self._events.append(event)

    def count(self, entity_type: type[Entity], **filters: Any) -> int:
        """Count entities matching filters."""
        return len(self.list(entity_type, **filters))

    def events(self, event_type: type[Event], **filters: Any) -> list[Event]:
        """Query the activity ledger."""
        results = []
        for event in self._events:
            if not isinstance(event, event_type):
                continue

            # Apply filters
            match = True
            for key, value in filters.items():
                if key == "since":
                    if event.created_at and event.created_at < value:
                        match = False
                        break
                elif hasattr(event, key):
                    if getattr(event, key) != value:
                        match = False
                        break

            if match:
                results.append(event)

        # Sort by created_at ascending
        return sorted(results, key=lambda e: e.created_at or datetime.min)


@pytest.fixture
def mock_store() -> MockStore:
    """Provide a fresh MockStore instance."""
    return MockStore()


@pytest.fixture
def sample_agent() -> AgentRecord:
    """Provide a sample AgentRecord."""
    return AgentRecord(
        id="agent-001",
        agent="grunt",
        model="claude-sonnet-4-5",
        ticket_id="DBC-137",
        state=AgentState.RUNNING,
        worktree="/private/tmp/grunt-dbc137",
        branch="herd/grunt/dbc-137-test-suite",
    )


@pytest.fixture
def sample_ticket() -> TicketRecord:
    """Provide a sample TicketRecord."""
    return TicketRecord(
        id="DBC-137",
        title="Comprehensive test suite for herd-core",
        status="in_progress",
        priority=TicketPriority.HIGH,
        project="herd-core",
    )


@pytest.fixture
def sample_pr() -> PRRecord:
    """Provide a sample PRRecord."""
    return PRRecord(
        id="pr-123",
        ticket_id="DBC-137",
        title="[grunt] test(herd-core): comprehensive test suite",
        branch="herd/grunt/dbc-137-test-suite",
        status="open",
        lines_added=500,
        lines_deleted=10,
        files_changed=7,
    )


@pytest.fixture
def sample_review() -> ReviewRecord:
    """Provide a sample ReviewRecord."""
    return ReviewRecord(
        id="review-001",
        pr_id="pr-123",
        ticket_id="DBC-137",
        reviewer_instance_id="wardenstein-001",
        verdict="pass",
        body="Clean implementation, tests passing.",
        findings_count=0,
    )
