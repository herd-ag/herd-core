"""DuckDB connection manager for Herd MCP server.

This module provides connection management and schema initialization for the Herd
operational database backed by DuckDB.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import duckdb


def get_db_path() -> str:
    """Get the database path from environment or use default.

    Returns:
        Database file path, or ":memory:" for in-memory database.
    """
    return os.getenv("HERD_DB_PATH", ".herd/herddb.duckdb")


def get_connection(db_path: str | None = None) -> duckdb.DuckDBPyConnection:
    """Get a DuckDB connection and ensure schema is initialized.

    Args:
        db_path: Optional database path. If None, uses get_db_path().
                Use ":memory:" for in-memory database.

    Returns:
        DuckDB connection with schema initialized.
    """
    if db_path is None:
        db_path = get_db_path()

    conn = duckdb.connect(db_path)

    # Initialize schema if needed
    if not _schema_exists(conn):
        init_schema(conn)

    return conn


def _schema_exists(conn: duckdb.DuckDBPyConnection) -> bool:
    """Check if the herd schema and tables exist.

    Args:
        conn: DuckDB connection.

    Returns:
        True if schema exists with expected tables.
    """
    try:
        # Use sentinel table check instead of counting all tables
        # Just checking if the query executes (table exists) is sufficient
        # We don't care if the table has data
        conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema = 'herd' AND table_name = 'agent_def'"
        ).fetchone()
        result = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'herd' AND table_name = 'agent_def'"
        ).fetchone()
        return result is not None and result[0] > 0
    except Exception:
        return False


def init_schema(conn: duckdb.DuckDBPyConnection) -> None:
    """Initialize the database schema from schema.sql.

    Args:
        conn: DuckDB connection.
    """
    schema_path = Path(__file__).parent / "schema.sql"
    schema_sql = schema_path.read_text()

    # Execute the entire schema SQL
    conn.execute(schema_sql)


@contextmanager
def connection(
    db_path: str | None = None,
) -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Context manager for DuckDB connections.

    Args:
        db_path: Optional database path. If None, uses get_db_path().

    Yields:
        DuckDB connection with schema initialized.

    Example:
        >>> with connection() as conn:
        ...     conn.execute("SELECT * FROM herd.agent_def")
    """
    conn = get_connection(db_path)
    try:
        yield conn
    finally:
        conn.close()
