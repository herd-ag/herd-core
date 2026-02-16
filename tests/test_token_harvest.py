"""Tests for herd_harvest_tokens tool."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from herd_core.types import (
    ModelRecord,
    TokenEvent,
)
from herd_mcp.adapters import AdapterRegistry
from herd_mcp.tools import token_harvest


@pytest.fixture
def mock_registry(mock_store):
    """Create an AdapterRegistry with MockStore."""
    return AdapterRegistry(store=mock_store, write_lock=asyncio.Lock())


@pytest.fixture
def seeded_store(mock_store):
    """Seed mock_store with model pricing data for token harvest tool."""
    mock_store.save(
        ModelRecord(
            id="claude-opus-4-6",
            name="claude-opus-4-6",
            provider="anthropic",
            context_window=200000,
            input_cost_per_token=Decimal("0.000015"),  # $15/M = $0.000015/token
            output_cost_per_token=Decimal("0.000075"),  # $75/M = $0.000075/token
        )
    )
    mock_store.save(
        ModelRecord(
            id="claude-sonnet-4",
            name="claude-sonnet-4",
            provider="anthropic",
            context_window=200000,
            input_cost_per_token=Decimal("0.000003"),  # $3/M = $0.000003/token
            output_cost_per_token=Decimal("0.000015"),  # $15/M = $0.000015/token
        )
    )
    return mock_store


@pytest.fixture
def seeded_registry(seeded_store):
    """Create an AdapterRegistry with seeded MockStore."""
    return AdapterRegistry(store=seeded_store, write_lock=asyncio.Lock())


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


def test_calculate_cost(seeded_store):
    """Test cost calculation based on model pricing."""
    # Calculate cost for claude-opus-4-6
    # Pricing: input=$0.000015/token, output=$0.000075/token
    cost = token_harvest._calculate_cost(
        seeded_store,
        "claude-opus-4-6",
        input_tokens=1_000_000,  # 1M tokens
        output_tokens=500_000,  # 0.5M tokens
    )

    # Expected: (1M * $0.000015) + (0.5M * $0.000075)
    # = $15 + $37.50 = $52.50
    assert abs(float(cost) - 52.50) < 0.01


def test_calculate_cost_unknown_model(seeded_store):
    """Test cost calculation for unknown model returns zero."""
    cost = token_harvest._calculate_cost(
        seeded_store,
        "unknown-model",
        input_tokens=1000,
        output_tokens=500,
    )

    assert cost == Decimal("0")


def test_write_token_activity(seeded_store):
    """Test writing token activity records via store."""
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

    records_written = token_harvest._write_token_activity(
        seeded_store, "inst-001", usage_data
    )

    assert records_written == 2

    # Verify token events in store
    events = seeded_store.events(TokenEvent)
    assert len(events) == 2

    # Sort events by model for deterministic assertions
    events_by_model = {e.model: e for e in events}

    # Check first record (claude-opus-4-6)
    opus_event = events_by_model["claude-opus-4-6"]
    assert opus_event.entity_id == "inst-001"
    assert opus_event.input_tokens == 1500
    assert opus_event.output_tokens == 750
    assert opus_event.cost_usd > 0  # cost should be calculated

    # Check second record (claude-sonnet-4)
    sonnet_event = events_by_model["claude-sonnet-4"]
    assert sonnet_event.entity_id == "inst-001"
    assert sonnet_event.model == "claude-sonnet-4"


@pytest.mark.asyncio
async def test_execute_success(seeded_store, seeded_registry, sample_jsonl_dir):
    """Test successful token harvest execution."""
    with patch("herd_mcp.tools.token_harvest.Path.home") as mock_home:
        mock_home.return_value = sample_jsonl_dir

        result = await token_harvest.execute(
            "inst-001", "/tmp/test-project", seeded_registry
        )

        assert result["success"] is True
        assert result["records_written"] == 2
        assert result["total_cost_usd"] > 0
        assert "claude-opus-4-6" in result["models_processed"]
        assert "claude-sonnet-4" in result["models_processed"]


@pytest.mark.asyncio
async def test_execute_no_session_dir(seeded_store, seeded_registry):
    """Test execution when session directory not found."""
    with patch("herd_mcp.tools.token_harvest.Path.home") as mock_home:
        mock_home.return_value = Path("/nonexistent")

        result = await token_harvest.execute(
            "inst-001", "/tmp/test-project", seeded_registry
        )

        assert result["success"] is False
        assert "error" in result
        assert "Could not locate session directory" in result["error"]
        assert result["records_written"] == 0


@pytest.mark.asyncio
async def test_execute_no_usage_data(seeded_store, seeded_registry, tmp_path):
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

    with patch("herd_mcp.tools.token_harvest.Path.home") as mock_home:
        mock_home.return_value = claude_home

        result = await token_harvest.execute(
            "inst-001", "/tmp/test-project", seeded_registry
        )

        assert result["success"] is True
        assert result["records_written"] == 0
        assert result["total_cost_usd"] == 0.0
        assert "No token usage data found" in result["message"]
