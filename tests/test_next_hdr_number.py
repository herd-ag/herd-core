"""Tests for next_hdr_number helper function."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def lance_test_db():
    """Create a temporary LanceDB database for testing.

    Resets the module-level singleton connection so each test gets
    a fresh LanceDB instance pointing at a new temporary directory.
    """
    import herd_mcp.memory as mem_mod

    # Save and clear the singleton so get_memory_store() reconnects
    saved_conn = mem_mod._db_connection
    mem_mod._db_connection = None

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.lance")
        with patch.dict(os.environ, {"HERD_LANCE_PATH": db_path}):
            yield db_path
            # Reset singleton after the test to avoid leaking state
            mem_mod._db_connection = None

    # Restore original singleton (relevant if other tests rely on it)
    mem_mod._db_connection = saved_conn


def test_next_hdr_number_empty_store(lance_test_db):
    """Test next_hdr_number returns HDR-0001 when no HDRs exist."""
    from herd_mcp.memory import next_hdr_number

    result = next_hdr_number()
    assert result == "HDR-0001"


def test_next_hdr_number_with_existing_hdrs(lance_test_db):
    """Test next_hdr_number returns correct next number."""
    from herd_mcp.memory import next_hdr_number, store_memory

    # Store three decisions with HDR numbers
    store_memory(
        project="herd",
        agent="mason",
        memory_type="decision_context",
        content="First decision",
        session_id="test-session-1",
        metadata={"hdr_number": "HDR-0001"},
    )
    store_memory(
        project="herd",
        agent="mason",
        memory_type="decision_context",
        content="Second decision",
        session_id="test-session-2",
        metadata={"hdr_number": "HDR-0002"},
    )
    store_memory(
        project="herd",
        agent="steve",
        memory_type="decision_context",
        content="Third decision",
        session_id="test-session-3",
        metadata={"hdr_number": "HDR-0005"},
    )

    # Should return HDR-0006 (max + 1)
    result = next_hdr_number()
    assert result == "HDR-0006"


def test_next_hdr_number_handles_gaps(lance_test_db):
    """Test next_hdr_number handles gaps in sequence correctly."""
    from herd_mcp.memory import next_hdr_number, store_memory

    # Store decisions with gaps (HDR-0001, HDR-0005, HDR-0010)
    store_memory(
        project="herd",
        agent="mason",
        memory_type="decision_context",
        content="First decision",
        session_id="test-session-1",
        metadata={"hdr_number": "HDR-0001"},
    )
    store_memory(
        project="herd",
        agent="mason",
        memory_type="decision_context",
        content="Fifth decision",
        session_id="test-session-2",
        metadata={"hdr_number": "HDR-0005"},
    )
    store_memory(
        project="herd",
        agent="steve",
        memory_type="decision_context",
        content="Tenth decision",
        session_id="test-session-3",
        metadata={"hdr_number": "HDR-0010"},
    )

    # Should return HDR-0011 (never reuse numbers)
    result = next_hdr_number()
    assert result == "HDR-0011"


def test_next_hdr_number_ignores_malformed(lance_test_db):
    """Test next_hdr_number ignores malformed HDR numbers."""
    from herd_mcp.memory import next_hdr_number, store_memory

    # Store decisions with valid and invalid HDR numbers
    store_memory(
        project="herd",
        agent="mason",
        memory_type="decision_context",
        content="First decision",
        session_id="test-session-1",
        metadata={"hdr_number": "HDR-0003"},
    )
    store_memory(
        project="herd",
        agent="mason",
        memory_type="decision_context",
        content="Malformed decision",
        session_id="test-session-2",
        metadata={"hdr_number": "HDR-XXXX"},  # Invalid
    )
    store_memory(
        project="herd",
        agent="steve",
        memory_type="decision_context",
        content="Another malformed",
        session_id="test-session-3",
        metadata={"hdr_number": "INVALID"},  # Invalid
    )

    # Should return HDR-0004 (ignoring malformed numbers)
    result = next_hdr_number()
    assert result == "HDR-0004"


def test_next_hdr_number_ignores_non_decision_memories(lance_test_db):
    """Test next_hdr_number only considers decision_context memories."""
    from herd_mcp.memory import next_hdr_number, store_memory

    # Store a decision with HDR number
    store_memory(
        project="herd",
        agent="mason",
        memory_type="decision_context",
        content="Decision",
        session_id="test-session-1",
        metadata={"hdr_number": "HDR-0002"},
    )

    # Store a session_summary with an HDR number (should be ignored)
    store_memory(
        project="herd",
        agent="mason",
        memory_type="session_summary",
        content="Session summary",
        session_id="test-session-2",
        metadata={"hdr_number": "HDR-0100"},  # Should be ignored
    )

    # Should return HDR-0003 (ignoring non-decision memories)
    result = next_hdr_number()
    assert result == "HDR-0003"


def test_next_hdr_number_handles_missing_metadata(lance_test_db):
    """Test next_hdr_number handles decisions without metadata gracefully."""
    from herd_mcp.memory import next_hdr_number, store_memory

    # Store decision with HDR number
    store_memory(
        project="herd",
        agent="mason",
        memory_type="decision_context",
        content="First decision",
        session_id="test-session-1",
        metadata={"hdr_number": "HDR-0007"},
    )

    # Store decision without metadata
    store_memory(
        project="herd",
        agent="steve",
        memory_type="decision_context",
        content="Decision without metadata",
        session_id="test-session-2",
        metadata=None,
    )

    # Store decision with metadata but no hdr_number field
    store_memory(
        project="herd",
        agent="fresco",
        memory_type="decision_context",
        content="Decision with other metadata",
        session_id="test-session-3",
        metadata={"ticket_code": "DBC-123"},
    )

    # Should return HDR-0008 (handling missing metadata gracefully)
    result = next_hdr_number()
    assert result == "HDR-0008"


def test_next_hdr_number_format(lance_test_db):
    """Test next_hdr_number returns properly formatted strings."""
    from herd_mcp.memory import next_hdr_number, store_memory

    # Store decision with large HDR number
    store_memory(
        project="herd",
        agent="mason",
        memory_type="decision_context",
        content="Decision",
        session_id="test-session-1",
        metadata={"hdr_number": "HDR-0042"},
    )

    result = next_hdr_number()
    # Should be zero-padded to 4 digits
    assert result == "HDR-0043"
    assert result.startswith("HDR-")
    assert len(result) == 8  # "HDR-" + 4 digits
