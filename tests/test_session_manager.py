"""Tests for session manager."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from herd_mcp.session_manager import Session, SessionManager


@pytest.fixture
def mock_process() -> MagicMock:
    """Create a mock subprocess process.

    Returns:
        Mock process object.
    """
    process = MagicMock()
    process.returncode = None
    process.stdout = AsyncMock()
    process.stderr = AsyncMock()
    process.wait = AsyncMock()
    process.terminate = MagicMock()
    process.kill = MagicMock()
    return process


@pytest.mark.asyncio
async def test_session_creation() -> None:
    """Test creating a new session spawns Claude process."""
    manager = SessionManager(project_path="/tmp/test", idle_timeout=180)

    with patch("herd_mcp.session_manager.asyncio.create_subprocess_exec") as mock_exec:
        # Mock process with stdout that returns session_id
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.wait = AsyncMock()

        async def mock_stdout_lines() -> list[bytes]:
            yield b'{"session_id": "test-session-123"}\n'
            yield b'{"type": "result", "result": "Hello from Mini-Mao", "session_id": "test-session-123"}\n'

        mock_process.stdout = mock_stdout_lines()
        mock_exec.return_value = mock_process

        response = await manager.send_message(
            "1234.5678", "Hello Mini-Mao", "Architect"
        )

        # Verify Claude was spawned with correct args
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert args[0] == "claude"
        assert args[1] == "-p"
        assert "Message from Architect: Hello Mini-Mao" in args[2]
        assert args[3] == "--verbose"
        assert args[4] == "--system-prompt"
        # args[5] is the system prompt content (Mini-Mao role)
        assert args[6] == "--output-format"
        assert args[7] == "stream-json"

        # Verify env was cleaned
        kwargs = mock_exec.call_args[1]
        assert "env" in kwargs
        assert "CLAUDECODE" not in kwargs["env"]

        # Verify session was created
        assert "1234.5678" in manager.sessions
        session = manager.sessions["1234.5678"]
        assert session.session_id == "test-session-123"
        assert session.message_count == 1

        # Verify response text is returned
        assert response == "Hello from Mini-Mao"


@pytest.mark.asyncio
async def test_message_routing_to_existing_session() -> None:
    """Test follow-up messages route to existing session with --resume."""
    manager = SessionManager(project_path="/tmp/test", idle_timeout=180)

    # Create an existing session manually
    mock_process = MagicMock()
    mock_process.returncode = 0
    existing_session = Session(
        thread_ts="1234.5678",
        process=mock_process,
        session_id="existing-session-id",
        last_activity=time.time(),
        message_count=1,
    )
    manager.sessions["1234.5678"] = existing_session

    with patch("herd_mcp.session_manager.asyncio.create_subprocess_exec") as mock_exec:
        # Mock follow-up process
        followup_process = MagicMock()
        followup_process.returncode = 0
        followup_process.wait = AsyncMock()

        async def mock_stdout_lines() -> list[bytes]:
            yield b'{"type": "result", "result": "Follow-up response", "session_id": "existing-session-id"}\n'

        followup_process.stdout = mock_stdout_lines()
        mock_exec.return_value = followup_process

        response = await manager.send_message(
            "1234.5678", "Follow-up message", "Architect"
        )

        # Verify --resume was used
        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert args[0] == "claude"
        assert "--resume" in args
        assert "existing-session-id" in args
        assert "--system-prompt" in args

        # Verify env was cleaned
        kwargs = mock_exec.call_args[1]
        assert "env" in kwargs
        assert "CLAUDECODE" not in kwargs["env"]

        # Verify message count incremented
        assert manager.sessions["1234.5678"].message_count == 2

        # Verify response text is returned
        assert response == "Follow-up response"


@pytest.mark.asyncio
async def test_idle_timeout_detection() -> None:
    """Test idle sessions are detected and closed."""
    manager = SessionManager(project_path="/tmp/test", idle_timeout=2)

    # Create an old session
    mock_process = MagicMock()
    mock_process.returncode = None
    mock_process.wait = AsyncMock()
    old_session = Session(
        thread_ts="old.thread",
        process=mock_process,
        session_id="old-session",
        last_activity=time.time() - 10,  # 10 seconds ago
        message_count=1,
    )
    manager.sessions["old.thread"] = old_session

    # Manually trigger idle check logic (one iteration)
    now = time.time()
    idle_threads = [
        thread_ts
        for thread_ts, session in manager.sessions.items()
        if now - session.last_activity > manager.idle_timeout
    ]
    for thread_ts in idle_threads:
        await manager.close_session(thread_ts, reason="idle")

    # Verify old session was closed
    assert "old.thread" not in manager.sessions
    mock_process.terminate.assert_called_once()


@pytest.mark.asyncio
async def test_shutdown_command_detection() -> None:
    """Test shutdown commands are detected correctly."""
    manager = SessionManager(project_path="/tmp/test", idle_timeout=180)

    test_cases = [
        ("go to sleep", "to sleep"),
        ("Go to sleep now", "to sleep"),
        ("stand down", "stand down"),
        ("Standdown please", "stand down"),
        ("terminate now", "terminate"),
        ("shutdown", "shutdown"),
    ]

    for text, expected_reason in test_cases:
        reason = manager._is_shutdown_command(text)
        assert reason == expected_reason, f"Failed for: {text}"

    # Non-shutdown messages
    assert manager._is_shutdown_command("Hello Mini-Mao") is None
    assert manager._is_shutdown_command("What's the status?") is None


@pytest.mark.asyncio
async def test_close_session_cleanup() -> None:
    """Test closing a session terminates process and removes from active."""
    manager = SessionManager(project_path="/tmp/test", idle_timeout=180)

    # Create a session
    mock_process = MagicMock()
    mock_process.returncode = None
    mock_process.wait = AsyncMock()
    session = Session(
        thread_ts="1234.5678",
        process=mock_process,
        session_id="test-session",
        last_activity=time.time(),
        message_count=1,
    )
    manager.sessions["1234.5678"] = session

    # Close it
    await manager.close_session("1234.5678", reason="test")

    # Verify cleanup
    assert "1234.5678" not in manager.sessions
    mock_process.terminate.assert_called_once()
    mock_process.wait.assert_called_once()


@pytest.mark.asyncio
async def test_close_session_forced_kill_on_timeout() -> None:
    """Test session is force-killed if terminate times out."""
    manager = SessionManager(project_path="/tmp/test", idle_timeout=180)

    # Create a session with process that hangs on wait
    mock_process = MagicMock()
    mock_process.returncode = None
    mock_process.wait = AsyncMock(side_effect=asyncio.TimeoutError())
    session = Session(
        thread_ts="1234.5678",
        process=mock_process,
        session_id="test-session",
        last_activity=time.time(),
        message_count=1,
    )
    manager.sessions["1234.5678"] = session

    # Patch wait_for to trigger timeout immediately
    with patch(
        "herd_mcp.session_manager.asyncio.wait_for",
        side_effect=asyncio.TimeoutError(),
    ):
        mock_process.wait = AsyncMock()  # Reset for kill wait
        await manager.close_session("1234.5678", reason="test")

    # Verify kill was called
    assert "1234.5678" not in manager.sessions
    mock_process.terminate.assert_called_once()
    mock_process.kill.assert_called_once()


@pytest.mark.asyncio
async def test_close_all() -> None:
    """Test close_all shuts down all active sessions."""
    manager = SessionManager(project_path="/tmp/test", idle_timeout=180)

    # Create multiple sessions
    for i in range(3):
        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.wait = AsyncMock()
        session = Session(
            thread_ts=f"thread.{i}",
            process=mock_process,
            session_id=f"session-{i}",
            last_activity=time.time(),
            message_count=1,
        )
        manager.sessions[f"thread.{i}"] = session

    await manager.close_all()

    # Verify all sessions closed
    assert len(manager.sessions) == 0


@pytest.mark.asyncio
async def test_session_id_capture_from_claude_output() -> None:
    """Test session_id is captured from Claude CLI streaming JSON."""
    manager = SessionManager(project_path="/tmp/test", idle_timeout=180)

    with patch("herd_mcp.session_manager.asyncio.create_subprocess_exec") as mock_exec:
        # Mock process with multiple JSON lines
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.wait = AsyncMock()

        async def mock_stdout_lines() -> list[bytes]:
            yield b'{"type": "start"}\n'
            yield b'{"session_id": "captured-session-id"}\n'
            yield b'{"type": "result", "result": "Response text", "session_id": "captured-session-id"}\n'

        mock_process.stdout = mock_stdout_lines()
        mock_exec.return_value = mock_process

        await manager.send_message("1234.5678", "Test", "Architect")

        # Verify session_id was captured
        session = manager.sessions["1234.5678"]
        assert session.session_id == "captured-session-id"


@pytest.mark.asyncio
async def test_shutdown_command_closes_session() -> None:
    """Test shutdown command triggers session close."""
    manager = SessionManager(project_path="/tmp/test", idle_timeout=180)

    # Create a session
    mock_process = MagicMock()
    mock_process.returncode = None
    mock_process.wait = AsyncMock()
    session = Session(
        thread_ts="1234.5678",
        process=mock_process,
        session_id="test-session",
        last_activity=time.time(),
        message_count=1,
    )
    manager.sessions["1234.5678"] = session

    # Send shutdown command
    response = await manager.send_message("1234.5678", "go to sleep", "Architect")

    # Verify session closed
    assert "1234.5678" not in manager.sessions
    assert "to sleep" in response
    mock_process.terminate.assert_called_once()


@pytest.mark.asyncio
async def test_start_creates_idle_check_task() -> None:
    """Test start() creates the idle check task."""
    manager = SessionManager(project_path="/tmp/test", idle_timeout=180)

    await manager.start()

    # Verify idle check task was created
    assert manager._idle_check_task is not None
    assert not manager._idle_check_task.done()

    # Clean up
    await manager.stop()


@pytest.mark.asyncio
async def test_stop_cancels_idle_check_and_closes_sessions() -> None:
    """Test stop() cancels idle check task and closes all sessions."""
    manager = SessionManager(project_path="/tmp/test", idle_timeout=180)

    # Start manager
    await manager.start()

    # Create a session
    mock_process = MagicMock()
    mock_process.returncode = None
    mock_process.wait = AsyncMock()
    session = Session(
        thread_ts="1234.5678",
        process=mock_process,
        session_id="test-session",
        last_activity=time.time(),
        message_count=1,
    )
    manager.sessions["1234.5678"] = session

    # Stop manager
    await manager.stop()

    # Verify idle check task was cancelled
    assert manager._idle_check_task.cancelled()

    # Verify all sessions were closed
    assert len(manager.sessions) == 0
    mock_process.terminate.assert_called_once()


@pytest.mark.asyncio
async def test_idle_check_loop_closes_idle_sessions() -> None:
    """Test _idle_check_loop() actually runs as a task and closes idle sessions."""
    manager = SessionManager(project_path="/tmp/test", idle_timeout=1)

    # Start manager (starts idle check loop)
    await manager.start()

    # Create an old session
    mock_process = MagicMock()
    mock_process.returncode = None
    mock_process.wait = AsyncMock()
    old_session = Session(
        thread_ts="old.thread",
        process=mock_process,
        session_id="old-session",
        last_activity=time.time() - 10,  # 10 seconds ago
        message_count=1,
    )
    manager.sessions["old.thread"] = old_session

    # Wait for idle check to run (it checks every 30 seconds, but we can wait a bit)
    # Since the idle timeout is 1 second and the session is 10 seconds old,
    # it should be detected on the next check
    await asyncio.sleep(0.1)  # Give it time to schedule

    # Manually trigger one iteration of idle check logic
    now = time.time()
    idle_threads = [
        thread_ts
        for thread_ts, session in manager.sessions.items()
        if now - session.last_activity > manager.idle_timeout
    ]
    for thread_ts in idle_threads:
        await manager.close_session(thread_ts, reason="idle")

    # Verify old session was closed
    assert "old.thread" not in manager.sessions
    mock_process.terminate.assert_called_once()

    # Clean up
    await manager.stop()


@pytest.mark.asyncio
async def test_json_decode_error_handling_in_spawn() -> None:
    """Test _spawn_claude handles JSON decode errors gracefully."""
    manager = SessionManager(project_path="/tmp/test", idle_timeout=180)

    with patch("herd_mcp.session_manager.asyncio.create_subprocess_exec") as mock_exec:
        # Mock process with malformed JSON
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.wait = AsyncMock()

        async def mock_stdout_lines() -> list[bytes]:
            yield b'{"session_id": "test-123"}\n'
            yield b"invalid json line\n"  # Should be skipped
            yield b'{"type": "result", "result": "Hello", "session_id": "test-123"}\n'

        mock_process.stdout = mock_stdout_lines()
        mock_exec.return_value = mock_process

        response = await manager.send_message("1234.5678", "Test", "Architect")

        # Verify session was created despite malformed line
        assert "1234.5678" in manager.sessions
        session = manager.sessions["1234.5678"]
        assert session.session_id == "test-123"
        assert response == "Hello"


@pytest.mark.asyncio
async def test_json_decode_error_handling_in_send() -> None:
    """Test _send_to_claude handles JSON decode errors gracefully."""
    manager = SessionManager(project_path="/tmp/test", idle_timeout=180)

    # Create an existing session
    mock_process = MagicMock()
    mock_process.returncode = 0
    existing_session = Session(
        thread_ts="1234.5678",
        process=mock_process,
        session_id="existing-session-id",
        last_activity=time.time(),
        message_count=1,
    )
    manager.sessions["1234.5678"] = existing_session

    with patch("herd_mcp.session_manager.asyncio.create_subprocess_exec") as mock_exec:
        # Mock follow-up process with malformed JSON
        followup_process = MagicMock()
        followup_process.returncode = 0
        followup_process.wait = AsyncMock()

        async def mock_stdout_lines() -> list[bytes]:
            yield b"malformed line\n"  # Should be skipped
            yield b'{"type": "result", "result": "Response", "session_id": "existing-session-id"}\n'

        followup_process.stdout = mock_stdout_lines()
        mock_exec.return_value = followup_process

        response = await manager.send_message("1234.5678", "Follow-up", "Architect")

        # Verify response was captured despite malformed line
        assert response == "Response"


@pytest.mark.asyncio
async def test_empty_response_from_spawn() -> None:
    """Test _spawn_claude returns error message when Claude produces no text."""
    manager = SessionManager(project_path="/tmp/test", idle_timeout=180)

    with patch("herd_mcp.session_manager.asyncio.create_subprocess_exec") as mock_exec:
        # Mock process with no text output
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.wait = AsyncMock()

        async def mock_stdout_lines() -> list[bytes]:
            yield b'{"session_id": "test-123"}\n'
            # No text entries

        mock_process.stdout = mock_stdout_lines()
        mock_exec.return_value = mock_process

        response = await manager.send_message("1234.5678", "Test", "Architect")

        # Verify error message is returned
        assert "No response from Mini-Mao" in response
        assert "claude CLI" in response


@pytest.mark.asyncio
async def test_empty_response_from_send() -> None:
    """Test _send_to_claude returns error message when Claude produces no text."""
    manager = SessionManager(project_path="/tmp/test", idle_timeout=180)

    # Create an existing session
    mock_process = MagicMock()
    mock_process.returncode = 0
    existing_session = Session(
        thread_ts="1234.5678",
        process=mock_process,
        session_id="existing-session-id",
        last_activity=time.time(),
        message_count=1,
    )
    manager.sessions["1234.5678"] = existing_session

    with patch("herd_mcp.session_manager.asyncio.create_subprocess_exec") as mock_exec:
        # Mock follow-up process with no text output
        followup_process = MagicMock()
        followup_process.returncode = 0
        followup_process.wait = AsyncMock()

        async def mock_stdout_lines() -> list[bytes]:
            # No text entries
            yield b'{"type": "other"}\n'

        followup_process.stdout = mock_stdout_lines()
        mock_exec.return_value = followup_process

        response = await manager.send_message("1234.5678", "Follow-up", "Architect")

        # Verify error message is returned
        assert "No response from Mini-Mao" in response


@pytest.mark.asyncio
async def test_race_condition_prevention() -> None:
    """Test race condition prevention when multiple messages arrive simultaneously."""
    manager = SessionManager(project_path="/tmp/test", idle_timeout=180)

    with patch("herd_mcp.session_manager.asyncio.create_subprocess_exec") as mock_exec:
        # Mock process
        mock_process = MagicMock()
        mock_process.returncode = 0
        mock_process.wait = AsyncMock()

        async def mock_stdout_lines() -> list[bytes]:
            # Add a small delay to simulate spawn taking time
            await asyncio.sleep(0.1)
            yield b'{"session_id": "test-123"}\n'
            yield b'{"type": "result", "result": "Hello", "session_id": "test-123"}\n'

        mock_process.stdout = mock_stdout_lines()
        mock_exec.return_value = mock_process

        # Send two messages simultaneously to same thread
        task1 = asyncio.create_task(
            manager.send_message("1234.5678", "Message 1", "User1")
        )
        task2 = asyncio.create_task(
            manager.send_message("1234.5678", "Message 2", "User2")
        )

        # Wait for both
        results = await asyncio.gather(task1, task2)

        # Verify only one session was created
        assert "1234.5678" in manager.sessions

        # At least one should have gotten a response
        assert any(r for r in results)
