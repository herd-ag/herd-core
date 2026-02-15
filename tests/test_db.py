"""Tests for database connection and schema initialization."""

from __future__ import annotations

import duckdb
from herd_mcp import db


def test_get_connection_memory():
    """Test that get_connection works with in-memory database."""
    conn = db.get_connection(":memory:")
    assert isinstance(conn, duckdb.DuckDBPyConnection)
    conn.close()


def test_init_schema_creates_all_tables(empty_db):
    """Test that init_schema creates all 28 tables in herd schema."""
    db.init_schema(empty_db)

    # Query for all tables in herd schema
    result = empty_db.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'herd' ORDER BY table_name"
    ).fetchall()

    table_names = [row[0] for row in result]

    # Verify we have exactly 28 tables
    assert len(table_names) == 28

    # Verify specific expected tables
    expected_tables = [
        "agent_def",
        "agent_instance",
        "agent_instance_lifecycle_activity",
        "agent_instance_pr_activity",
        "agent_instance_review_activity",
        "agent_instance_skillset",
        "agent_instance_ticket_activity",
        "agent_instance_token_activity",
        "agent_observation",
        "agent_skillset",
        "craft_def",
        "craft_version",
        "decision_record",
        "initiative_def",
        "model_def",
        "personality_def",
        "personality_version",
        "pr_def",
        "project_def",
        "review_def",
        "review_finding",
        "skill_def",
        "skill_version",
        "skill_skillset",
        "skillset_def",
        "skillset_version",
        "sprint_def",
        "ticket_def",
    ]

    assert sorted(table_names) == sorted(expected_tables)


def test_schema_exists_check(empty_db, in_memory_db):
    """Test that _schema_exists correctly detects schema presence."""
    # Empty database should return False
    assert db._schema_exists(empty_db) is False

    # Database with schema should return True
    assert db._schema_exists(in_memory_db) is True


def test_connection_context_manager():
    """Test that connection context manager works correctly."""
    with db.connection(":memory:") as conn:
        assert isinstance(conn, duckdb.DuckDBPyConnection)
        # Schema should be auto-initialized
        assert db._schema_exists(conn) is True


def test_table_columns_sample(in_memory_db):
    """Test that key tables have expected columns."""
    # Check agent_def table
    result = in_memory_db.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'herd' AND table_name = 'agent_def' "
        "ORDER BY ordinal_position"
    ).fetchall()

    agent_def_columns = [row[0] for row in result]
    assert "agent_code" in agent_def_columns
    assert "agent_role" in agent_def_columns
    assert "agent_status" in agent_def_columns
    assert "created_at" in agent_def_columns

    # Check ticket_def table
    result = in_memory_db.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'herd' AND table_name = 'ticket_def' "
        "ORDER BY ordinal_position"
    ).fetchall()

    ticket_def_columns = [row[0] for row in result]
    assert "ticket_code" in ticket_def_columns
    assert "ticket_title" in ticket_def_columns
    assert "ticket_current_status" in ticket_def_columns
    assert "project_code" in ticket_def_columns
