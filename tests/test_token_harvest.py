"""Tests for herd_harvest_tokens tool."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from herd_mcp.tools import token_harvest


@pytest.fixture
def seeded_db(in_memory_db):
    """Provide a database with test data for token harvest tool."""
    conn = in_memory_db

    # Insert test model pricing
    conn.execute("""
        INSERT INTO herd.model_def
          (model_code, model_provider, model_context_window,
           model_input_cost_per_m, model_output_cost_per_m,
           model_cache_read_cost_per_m, model_cache_create_cost_per_m,
           created_at)
        VALUES ('claude-opus-4-6', 'anthropic', 200000, 15.00, 75.00, 1.50, 18.75, CURRENT_TIMESTAMP)
        """)

    conn.execute("""
        INSERT INTO herd.model_def
          (model_code, model_provider, model_context_window,
           model_input_cost_per_m, model_output_cost_per_m,
           model_cache_read_cost_per_m, model_cache_create_cost_per_m,
           created_at)
        VALUES ('claude-sonnet-4', 'anthropic', 200000, 3.00, 15.00, 0.30, 3.75, CURRENT_TIMESTAMP)
        """)

    yield conn


@pytest.fixture
def sample_jsonl_dir(tmp_path):
    """Create a temporary directory with sample JSONL session files."""
    # Create the full .claude/projects structure
    claude_home = tmp_path / "home"
    projects_dir = claude_home / ".claude" / "projects"
    session_dir = projects_dir / "-tmp-test-project"
    session_dir.mkdir(parents=True, exist_ok=True)

    # Create sample JSONL file with token usage
    session_file = session_dir / "test-session-001.jsonl"

    messages = [
        # File history snapshot (no usage)
        {
            "type": "file-history-snapshot",
            "messageId": "msg-001",
            "timestamp": "2026-02-09T10:00:00Z",
        },
        # Assistant message with usage
        {
            "type": "assistant",
            "messageId": "msg-002",
            "message": {
                "model": "claude-opus-4-6",
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "cache_read_input_tokens": 2000,
                    "cache_creation_input_tokens": 1500,
                },
            },
            "timestamp": "2026-02-09T10:01:00Z",
        },
        # Another assistant message
        {
            "type": "assistant",
            "messageId": "msg-003",
            "message": {
                "model": "claude-opus-4-6",
                "usage": {
                    "input_tokens": 500,
                    "output_tokens": 250,
                    "cache_read_input_tokens": 1000,
                    "cache_creation_input_tokens": 0,
                },
            },
            "timestamp": "2026-02-09T10:02:00Z",
        },
        # Different model
        {
            "type": "assistant",
            "messageId": "msg-004",
            "message": {
                "model": "claude-sonnet-4",
                "usage": {
                    "input_tokens": 2000,
                    "output_tokens": 1000,
                    "cache_read_input_tokens": 3000,
                    "cache_creation_input_tokens": 500,
                },
            },
            "timestamp": "2026-02-09T10:03:00Z",
        },
    ]

    with open(session_file, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")

    return claude_home


def test_find_project_session_dir_success(sample_jsonl_dir):
    """Test finding session directory for valid project path."""
    with patch("herd_mcp.tools.token_harvest.Path.home") as mock_home:
        mock_home.return_value = sample_jsonl_dir

        result = token_harvest._find_project_session_dir("/tmp/test-project")

        # The function should convert /tmp/test-project to -tmp-test-project
        assert result is not None
        assert result.exists()
        assert result.name == "-tmp-test-project"


def test_find_project_session_dir_not_found():
    """Test finding session directory for non-existent project."""
    result = token_harvest._find_project_session_dir("/nonexistent/project")
    assert result is None


def test_parse_jsonl_sessions(sample_jsonl_dir):
    """Test parsing JSONL session files."""
    session_dir = sample_jsonl_dir / ".claude" / "projects" / "-tmp-test-project"

    messages = token_harvest._parse_jsonl_sessions(session_dir)

    # Should have 3 assistant messages with usage data
    assert len(messages) == 3

    # Check first message
    assert messages[0]["model"] == "claude-opus-4-6"
    assert messages[0]["usage"]["input_tokens"] == 1000
    assert messages[0]["usage"]["output_tokens"] == 500
    assert messages[0]["usage"]["cache_read_input_tokens"] == 2000
    assert messages[0]["usage"]["cache_creation_input_tokens"] == 1500

    # Check third message (different model)
    assert messages[2]["model"] == "claude-sonnet-4"
    assert messages[2]["usage"]["input_tokens"] == 2000


def test_parse_jsonl_sessions_malformed(tmp_path):
    """Test parsing JSONL with malformed lines."""
    session_dir = tmp_path / "malformed"
    session_dir.mkdir()

    session_file = session_dir / "bad.jsonl"
    with open(session_file, "w") as f:
        f.write('{"valid": "json"}\n')
        f.write("not valid json\n")
        f.write(
            '{"type": "assistant", "message": {"model": "test", "usage": {"input_tokens": 100, "output_tokens": 50}}}\n'
        )

    messages = token_harvest._parse_jsonl_sessions(session_dir)

    # Should skip malformed line and return valid message
    assert len(messages) == 1
    assert messages[0]["model"] == "test"


def test_aggregate_usage_by_model():
    """Test aggregating token counts by model."""
    messages = [
        {
            "model": "claude-opus-4-6",
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_read_input_tokens": 2000,
                "cache_creation_input_tokens": 1500,
            },
        },
        {
            "model": "claude-opus-4-6",
            "usage": {
                "input_tokens": 500,
                "output_tokens": 250,
                "cache_read_input_tokens": 1000,
                "cache_creation_input_tokens": 0,
            },
        },
        {
            "model": "claude-sonnet-4",
            "usage": {
                "input_tokens": 2000,
                "output_tokens": 1000,
                "cache_read_input_tokens": 3000,
                "cache_creation_input_tokens": 500,
            },
        },
    ]

    result = token_harvest._aggregate_usage_by_model(messages)

    # Check claude-opus-4-6 aggregation
    assert result["claude-opus-4-6"]["input_tokens"] == 1500
    assert result["claude-opus-4-6"]["output_tokens"] == 750
    assert result["claude-opus-4-6"]["cache_read_tokens"] == 3000
    assert result["claude-opus-4-6"]["cache_create_tokens"] == 1500

    # Check claude-sonnet-4 aggregation
    assert result["claude-sonnet-4"]["input_tokens"] == 2000
    assert result["claude-sonnet-4"]["output_tokens"] == 1000
    assert result["claude-sonnet-4"]["cache_read_tokens"] == 3000
    assert result["claude-sonnet-4"]["cache_create_tokens"] == 500


def test_calculate_cost(seeded_db):
    """Test cost calculation based on model pricing."""
    with patch("herd_mcp.tools.token_harvest.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        # Calculate cost for claude-opus-4-6
        # Pricing: input=$15/M, output=$75/M, cache_read=$1.50/M, cache_create=$18.75/M
        cost = token_harvest._calculate_cost(
            "claude-opus-4-6",
            input_tokens=1_000_000,  # 1M tokens
            output_tokens=500_000,  # 0.5M tokens
            cache_read_tokens=2_000_000,  # 2M tokens
            cache_create_tokens=1_000_000,  # 1M tokens
        )

        # Expected: (1M * $15) + (0.5M * $75) + (2M * $1.50) + (1M * $18.75)
        # = $15 + $37.50 + $3.00 + $18.75 = $74.25
        assert abs(cost - 74.25) < 0.01


def test_calculate_cost_unknown_model(seeded_db):
    """Test cost calculation for unknown model returns zero."""
    with patch("herd_mcp.tools.token_harvest.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        cost = token_harvest._calculate_cost(
            "unknown-model",
            input_tokens=1000,
            output_tokens=500,
            cache_read_tokens=0,
            cache_create_tokens=0,
        )

        assert cost == 0.0


def test_write_token_activity(seeded_db):
    """Test writing token activity records to database."""
    usage_data = {
        "claude-opus-4-6": {
            "input_tokens": 1500,
            "output_tokens": 750,
            "cache_read_tokens": 3000,
            "cache_create_tokens": 1500,
        },
        "claude-sonnet-4": {
            "input_tokens": 2000,
            "output_tokens": 1000,
            "cache_read_tokens": 3000,
            "cache_create_tokens": 500,
        },
    }

    with patch("herd_mcp.tools.token_harvest.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        records_written = token_harvest._write_token_activity("inst-001", usage_data)

        assert records_written == 2

        # Verify records in database
        activities = seeded_db.execute("""
            SELECT agent_instance_code, model_code, token_input_count,
                   token_output_count, token_cache_read_count, token_cache_create_count,
                   token_cost_usd
            FROM herd.agent_instance_token_activity
            ORDER BY model_code
            """).fetchall()

        assert len(activities) == 2

        # Check first record (claude-opus-4-6)
        assert activities[0][0] == "inst-001"
        assert activities[0][1] == "claude-opus-4-6"
        assert activities[0][2] == 1500  # input
        assert activities[0][3] == 750  # output
        assert activities[0][4] == 3000  # cache_read
        assert activities[0][5] == 1500  # cache_create
        assert activities[0][6] > 0  # cost should be calculated

        # Check second record (claude-sonnet-4)
        assert activities[1][0] == "inst-001"
        assert activities[1][1] == "claude-sonnet-4"


@pytest.mark.asyncio
async def test_execute_success(seeded_db, sample_jsonl_dir):
    """Test successful token harvest execution."""
    with patch("herd_mcp.tools.token_harvest.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch("herd_mcp.tools.token_harvest.Path.home") as mock_home:
            mock_home.return_value = sample_jsonl_dir

            result = await token_harvest.execute("inst-001", "/tmp/test-project")

            assert result["success"] is True
            assert result["records_written"] == 2
            assert result["total_cost_usd"] > 0
            assert "claude-opus-4-6" in result["models_processed"]
            assert "claude-sonnet-4" in result["models_processed"]


@pytest.mark.asyncio
async def test_execute_no_session_dir(seeded_db):
    """Test execution when session directory not found."""
    with patch("herd_mcp.tools.token_harvest.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch("herd_mcp.tools.token_harvest.Path.home") as mock_home:
            mock_home.return_value = Path("/nonexistent")

            result = await token_harvest.execute("inst-001", "/tmp/test-project")

            assert result["success"] is False
            assert "error" in result
            assert "Could not locate session directory" in result["error"]
            assert result["records_written"] == 0


@pytest.mark.asyncio
async def test_execute_no_usage_data(seeded_db, tmp_path):
    """Test execution when no usage data found in session files."""
    # Create the full .claude/projects structure
    claude_home = tmp_path / "home"
    projects_dir = claude_home / ".claude" / "projects"
    session_dir = projects_dir / "-tmp-test-project"
    session_dir.mkdir(parents=True)

    # Create JSONL file without usage data
    session_file = session_dir / "empty.jsonl"
    with open(session_file, "w") as f:
        f.write('{"type": "file-history-snapshot", "messageId": "msg-001"}\n')

    with patch("herd_mcp.tools.token_harvest.connection") as mock_context:
        mock_context.return_value.__enter__ = MagicMock(return_value=seeded_db)
        mock_context.return_value.__exit__ = MagicMock(return_value=None)

        with patch("herd_mcp.tools.token_harvest.Path.home") as mock_home:
            mock_home.return_value = claude_home

            result = await token_harvest.execute("inst-001", "/tmp/test-project")

            assert result["success"] is True
            assert result["records_written"] == 0
            assert result["total_cost_usd"] == 0.0
            assert "No token usage data found" in result["message"]
