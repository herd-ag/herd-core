"""Tests for vault refresh manager."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from herd_mcp.vault_refresh import VaultRefreshManager, get_manager


@pytest.fixture
def reset_singleton():
    """Reset the VaultRefreshManager singleton between tests."""
    VaultRefreshManager._instance = None
    yield
    VaultRefreshManager._instance = None


@pytest.mark.asyncio
async def test_singleton_pattern(reset_singleton):
    """Test that VaultRefreshManager is a singleton."""
    manager1 = get_manager()
    manager2 = get_manager()
    assert manager1 is manager2


@pytest.mark.asyncio
async def test_trigger_refresh_success(reset_singleton):
    """Test successful vault refresh trigger."""
    manager = get_manager()

    # Mock the subprocess
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"dbt run success", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc) as mock_exec:
        result = await manager.trigger_refresh("test_milestone", {"test": "context"})

        # Verify subprocess was called correctly
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0]
        assert call_args[0] == "dbt"
        assert call_args[1] == "run"
        assert "--project-dir" in call_args
        assert "--profiles-dir" in call_args

        # Verify result
        assert result["status"] == "success"
        assert result["milestone"] == "test_milestone"
        assert result["returncode"] == 0
        assert "dbt run success" in result["stdout"]


@pytest.mark.asyncio
async def test_trigger_refresh_failure(reset_singleton):
    """Test failed vault refresh trigger."""
    manager = get_manager()

    # Mock a failed subprocess
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"dbt error"))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await manager.trigger_refresh("test_milestone", {"test": "context"})

        # Verify error result
        assert result["status"] == "error"
        assert result["milestone"] == "test_milestone"
        assert result["returncode"] == 1
        assert "dbt error" in result["stderr"]


@pytest.mark.asyncio
async def test_trigger_refresh_dbt_not_found(reset_singleton):
    """Test vault refresh when dbt is not installed."""
    manager = get_manager()

    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError()):
        result = await manager.trigger_refresh("test_milestone", {"test": "context"})

        # Verify error result
        assert result["status"] == "error"
        assert result["error"] == "dbt command not found"
        assert "not installed" in result["message"]


@pytest.mark.asyncio
async def test_mutex_behavior(reset_singleton):
    """Test that only one refresh runs at a time."""
    manager = get_manager()

    # Create a slow-running mock process
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"success", b""))

    # Add delay to simulate long-running process
    async def slow_communicate():
        await asyncio.sleep(0.2)
        return (b"success", b"")

    mock_proc.communicate = slow_communicate

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        # Start first refresh (will take 0.2s)
        task1 = asyncio.create_task(manager.trigger_refresh("milestone1", {}))

        # Give task1 time to acquire lock
        await asyncio.sleep(0.05)

        # Try to trigger second refresh while first is running
        result2 = await manager.trigger_refresh("milestone2", {})

        # Second trigger should be queued (not started immediately)
        assert result2["status"] == "queued"
        assert result2["milestone"] == "milestone2"

        # Wait for first task to complete
        result1 = await task1

        # First task should succeed
        assert result1["status"] == "completed_with_queued"
        assert result1["milestone"] == "milestone1"
        assert "primary_result" in result1
        assert "queued_result" in result1


@pytest.mark.asyncio
async def test_queue_collapse(reset_singleton):
    """Test that multiple triggers collapse to single queued refresh."""
    manager = get_manager()

    # Create a slow-running mock process
    mock_proc = MagicMock()
    mock_proc.returncode = 0

    async def slow_communicate():
        await asyncio.sleep(0.2)
        return (b"success", b"")

    mock_proc.communicate = slow_communicate

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        # Start first refresh
        task1 = asyncio.create_task(manager.trigger_refresh("milestone1", {}))

        # Give task1 time to acquire lock
        await asyncio.sleep(0.05)

        # Trigger second refresh (will be queued)
        result2 = await manager.trigger_refresh("milestone2", {})
        assert result2["status"] == "queued"

        # Trigger third refresh (should collapse with second)
        result3 = await manager.trigger_refresh("milestone3", {})
        assert result3["status"] == "collapsed"
        assert result3["milestone"] == "milestone3"

        # Trigger fourth refresh (should also collapse)
        result4 = await manager.trigger_refresh("milestone4", {})
        assert result4["status"] == "collapsed"

        # Wait for first task to complete
        result1 = await task1

        # First task should have executed queued refresh
        assert result1["status"] == "completed_with_queued"


@pytest.mark.asyncio
async def test_concurrent_triggers(reset_singleton):
    """Test concurrent triggers behavior."""
    manager = get_manager()

    # Create a mock process
    mock_proc = MagicMock()
    mock_proc.returncode = 0

    async def slow_communicate():
        await asyncio.sleep(0.1)
        return (b"success", b"")

    mock_proc.communicate = slow_communicate

    call_count = 0

    async def count_calls(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return mock_proc

    with patch("asyncio.create_subprocess_exec", side_effect=count_calls):
        # Fire off 5 concurrent triggers
        tasks = [
            asyncio.create_task(manager.trigger_refresh(f"milestone{i}", {}))
            for i in range(5)
        ]

        results = await asyncio.gather(*tasks)

        # Should have exactly one "success" or "completed_with_queued" result
        # and multiple "queued" or "collapsed" results
        statuses = [r["status"] for r in results]

        # Count status types
        active_count = sum(
            1 for s in statuses if s in ("success", "completed_with_queued")
        )
        queued_count = sum(1 for s in statuses if s == "queued")
        collapsed_count = sum(1 for s in statuses if s == "collapsed")

        # Should have exactly 1 active, at most 1 queued, rest collapsed
        assert active_count == 1
        assert queued_count <= 1
        assert active_count + queued_count + collapsed_count == 5

        # If queued, should have run 2 dbt processes (initial + queued)
        # Otherwise, should have run 1
        if queued_count == 1:
            assert call_count == 2
        else:
            assert call_count == 1


@pytest.mark.asyncio
async def test_context_preservation(reset_singleton):
    """Test that context is preserved in results."""
    manager = get_manager()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"success", b""))

    context = {"ticket_id": "DBC-97", "agent": "grunt"}

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await manager.trigger_refresh("test_milestone", context)

        assert result["context"] == context
        assert result["context"]["ticket_id"] == "DBC-97"
        assert result["context"]["agent"] == "grunt"


@pytest.mark.asyncio
async def test_none_context_handling(reset_singleton):
    """Test that None context is handled gracefully."""
    manager = get_manager()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"success", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
        result = await manager.trigger_refresh("test_milestone", None)

        # Should default to empty dict
        assert result["context"] == {}


@pytest.mark.asyncio
async def test_unexpected_exception(reset_singleton):
    """Test handling of unexpected exceptions."""
    manager = get_manager()

    with patch(
        "asyncio.create_subprocess_exec",
        side_effect=RuntimeError("Unexpected error"),
    ):
        result = await manager.trigger_refresh("test_milestone", {})

        assert result["status"] == "error"
        assert "Unexpected error" in result["error"]


@pytest.mark.asyncio
async def test_manager_initialization(reset_singleton):
    """Test manager initialization state."""
    manager = get_manager()

    # Verify initialized state
    assert manager._lock is not None
    assert isinstance(manager._lock, asyncio.Lock)
    assert manager._pending_refresh is False
    assert manager._project_dir == ".herd/dbt"
    assert manager._profiles_dir == ".herd/dbt"
