"""Storage adapter protocol.

Implemented by: herd-store-duckdb (reference), or any persistence backend.

Responsible for persisting agent sessions, decision records, activity ledgers,
and operational state. Activity tables are append-only by convention — the
store adapter does not enforce this, but callers must respect it.
"""

from __future__ import annotations

from typing import Any, Protocol, Sequence, runtime_checkable

from herd_core.types import QueryResult


@runtime_checkable
class StoreAdapter(Protocol):
    """Persists and queries Herd operational data.

    Design principles:
    - Activity ledgers are append-only. Never UPDATE activity tables.
    - Soft deletes via deleted_at. Never hard-delete operational records.
    - Denormalized "current_status" fields are convenience copies, not source of truth.
    - All timestamps are UTC.
    """

    def execute(
        self,
        sql: str,
        params: Sequence[Any] | None = None,
    ) -> QueryResult:
        """Execute a SQL query and return results.

        For SELECT queries, returns matching rows.
        For INSERT/UPDATE/DELETE, returns affected row count.
        """
        ...

    def insert(self, table: str, data: dict[str, Any]) -> None:
        """Insert a single record into a table.

        Automatically sets created_at if not provided.
        """
        ...

    def insert_many(self, table: str, rows: list[dict[str, Any]]) -> None:
        """Insert multiple records into a table."""
        ...
