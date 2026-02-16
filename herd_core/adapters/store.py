"""Storage adapter protocol.

Implemented by: herd-store-duckdb (reference), or any persistence backend.

Responsible for persisting and retrieving Herd domain records. The adapter
maps Entity/Event types to its backend's storage model — the caller never
sees SQL, table names, or connection details.

Design:
    store.get(AgentRecord, "abc-123")           -> AgentRecord | None
    store.list(TicketRecord, status="blocked")   -> list[TicketRecord]
    store.save(agent_record)                     -> "abc-123"
    store.append(lifecycle_event)                -> None

The adapter dispatches by type: it knows that AgentRecord maps to its
internal agent table, TicketRecord to its ticket table, etc. How it
stores them is its business — DuckDB, SQLite, Postgres, Snowflake,
a REST API, or flat files.
"""

from __future__ import annotations

from builtins import list as builtin_list
from typing import Any, Protocol, TypeVar, runtime_checkable

from herd_core.types import Entity, Event

E = TypeVar("E", bound=Entity)
Ev = TypeVar("Ev", bound=Event)


@runtime_checkable
class StoreAdapter(Protocol):
    """Persists and retrieves Herd domain records.

    Principles:
    - Entities (get/list/save): mutable records with identity and soft deletes.
    - Events (append): immutable, append-only audit trail. Never update or delete.
    - Backend-agnostic: no SQL, no table names, no connection details in the interface.
    - Timestamps are UTC, set by the adapter if not provided.
    """

    def get(self, entity_type: type[E], id: str) -> E | None:
        """Retrieve a single entity by ID.

        Args:
            entity_type: The Entity subclass to retrieve (e.g., AgentRecord).
            id: The entity's unique identifier.

        Returns:
            The entity instance, or None if not found (or soft-deleted).
        """
        ...

    def list(self, entity_type: type[E], **filters: Any) -> list[E]:
        """List entities matching filters.

        Args:
            entity_type: The Entity subclass to list (e.g., TicketRecord).
            **filters: Field-value pairs to filter on. Adapter maps these
                to its backend's query mechanism. Common filters:
                - status="in_progress"
                - assignee="grunt"
                - active=True (shorthand for deleted_at IS NULL)

        Returns:
            List of matching entities. Empty list if none match.
        """
        ...

    def save(self, record: Entity) -> str:
        """Save an entity (insert or update).

        If the entity's id exists in the store, updates it.
        If not, inserts it. Sets modified_at automatically.

        Args:
            record: The entity to persist.

        Returns:
            The entity's id.
        """
        ...

    def delete(self, entity_type: type[E], id: str) -> None:
        """Soft-delete an entity by setting deleted_at.

        Does not physically remove the record.
        """
        ...

    def append(self, event: Event) -> None:
        """Append an immutable event to the activity ledger.

        Events are never updated or deleted. This is the audit trail.
        Sets created_at automatically if not provided.

        Args:
            event: The event to append. Must be an Event subclass
                (LifecycleEvent, TicketEvent, PREvent, etc.).
        """
        ...

    def count(self, entity_type: type[E], **filters: Any) -> int:
        """Count entities matching filters.

        More efficient than len(list()) for large datasets.
        """
        ...

    def events(self, event_type: type[Ev], **filters: Any) -> builtin_list[Ev]:
        """Query the activity ledger.

        Args:
            event_type: The Event subclass to query (e.g., TicketEvent).
            **filters: Field-value pairs. Common filters:
                - entity_id="DBC-120" (all events for a ticket)
                - instance_id="abc-123" (all events by an agent)
                - since=datetime (events after a timestamp)

        Returns:
            List of matching events, ordered by created_at ascending.
        """
        ...

    def storage_info(self) -> dict[str, str | int]:
        """Return storage metadata for this adapter.

        Provides information about the storage backend's location, size,
        and last modification time. Used for health checks and monitoring.

        Returns:
            Dict with keys:
                - path: Storage location (file path, directory, or empty for in-memory/cloud)
                - size_bytes: Total storage size in bytes (0 for in-memory/cloud)
                - last_modified: ISO 8601 UTC timestamp of last modification (empty for in-memory/cloud)
        """
        ...
