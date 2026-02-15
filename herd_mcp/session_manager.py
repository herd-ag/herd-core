"""Session manager for Mini-Mao Claude CLI sessions.

Manages thread-to-session mapping and Claude CLI subprocess lifecycle for
Slack-driven Mini-Mao activation.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Session:
    """Represents an active Mini-Mao session.

    Attributes:
        thread_ts: Slack thread timestamp (unique ID).
        process: The Claude CLI subprocess.
        session_id: Claude's session ID for --resume.
        last_activity: Unix timestamp of last activity.
        message_count: Number of messages in session.
        last_response: Last response text from Claude.
    """

    thread_ts: str
    process: asyncio.subprocess.Process
    session_id: str | None
    last_activity: float
    message_count: int
    last_response: str = ""


class SessionManager:
    """Manages Claude CLI sessions for Slack threads.

    Each Slack thread gets its own Claude CLI subprocess. Sessions are tracked
    by thread timestamp and automatically closed on idle timeout or explicit
    shutdown commands.
    """

    def __init__(self, project_path: str, idle_timeout: int = 180) -> None:
        """Initialize the session manager.

        Args:
            project_path: Absolute path to the dbt-conceptual project.
            idle_timeout: Seconds before idle session shutdown (default: 180).
        """
        self.project_path = Path(project_path)
        self.idle_timeout = idle_timeout
        self.sessions: dict[str, Session] = {}
        self._pending_sessions: set[str] = set()  # Track in-progress session creation
        self._idle_check_task: asyncio.Task[None] | None = None

        # Load Mini-Mao role file for system prompt
        role_file_path = self.project_path / ".herd" / "roles" / "mini-mao.md"
        try:
            self._system_prompt = role_file_path.read_text()
        except FileNotFoundError:
            self._system_prompt = (
                "You are Mini-Mao, the Scum Master and Team Lead of The Herd."
            )

        self._system_prompt += "\n\n## Slack Output Formatting\nYou are responding via Slack. Use Slack mrkdwn formatting:\n- *bold* (single asterisks, NOT double)\n- _italic_ (underscores)\n- `code` and ```code blocks```\n- Bullet points with • or -\n- Do NOT use markdown headers (###), markdown tables, or **double asterisks**\n- For emphasis on section titles, use *bold* on its own line\n- Keep responses concise — Slack messages should be scannable"

    async def start(self) -> None:
        """Start the session manager and idle check loop."""
        self._idle_check_task = asyncio.create_task(self._idle_check_loop())

    async def stop(self) -> None:
        """Stop the session manager and close all sessions."""
        if self._idle_check_task:
            self._idle_check_task.cancel()
            try:
                await self._idle_check_task
            except asyncio.CancelledError:
                pass

        await self.close_all()

    async def send_message(self, thread_ts: str, text: str, user_name: str) -> str:
        """Send a message to a session (create if needed).

        Args:
            thread_ts: Slack thread timestamp.
            text: Message text from user.
            user_name: Slack display name of user.

        Returns:
            Assistant's response text.
        """
        # Check for shutdown command
        shutdown_reason = self._is_shutdown_command(text)
        if shutdown_reason:
            response = f"Understood. Going {shutdown_reason}. For the Herd!"
            if thread_ts in self.sessions:
                await self.close_session(thread_ts, reason=shutdown_reason)
            return response

        # Get or create session
        if thread_ts not in self.sessions:
            # Check if session creation is already in progress
            if thread_ts in self._pending_sessions:
                # Another message triggered spawn; wait for it
                while thread_ts in self._pending_sessions:
                    await asyncio.sleep(0.1)
                # Session should exist now; retry
                if thread_ts in self.sessions:
                    session = self.sessions[thread_ts]
                    response = await self._send_to_claude(session, text, user_name)
                    session.last_response = response
                    session.message_count += 1
                else:
                    # Spawn failed; return error
                    return "Error: Failed to create session. Please try again."
            else:
                # Mark session as pending
                self._pending_sessions.add(thread_ts)
                try:
                    session = await self._spawn_claude(thread_ts, text, user_name)
                    self.sessions[thread_ts] = session
                    response = session.last_response
                finally:
                    # Remove from pending
                    self._pending_sessions.discard(thread_ts)
        else:
            session = self.sessions[thread_ts]
            # Send follow-up message to existing session
            response = await self._send_to_claude(session, text, user_name)
            session.last_response = response
            session.message_count += 1

        # Update activity timestamp
        session.last_activity = time.time()

        return response

    async def close_session(self, thread_ts: str, reason: str = "idle") -> None:
        """Close a session and clean up.

        Args:
            thread_ts: Slack thread timestamp.
            reason: Reason for closing (idle, sleep, standdown, terminate).
        """
        if thread_ts not in self.sessions:
            return

        session = self.sessions[thread_ts]

        # Terminate process
        if session.process.returncode is None:
            try:
                session.process.terminate()
                await asyncio.wait_for(session.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                session.process.kill()
                await session.process.wait()

        # Remove from active sessions
        del self.sessions[thread_ts]

    async def close_all(self) -> None:
        """Shutdown all active sessions."""
        thread_ids = list(self.sessions.keys())
        for thread_ts in thread_ids:
            await self.close_session(thread_ts, reason="shutdown")

    async def _spawn_claude(
        self, thread_ts: str, initial_message: str, user_name: str
    ) -> Session:
        """Spawn a new Claude CLI session.

        Args:
            thread_ts: Slack thread timestamp.
            initial_message: First message from user.
            user_name: Slack display name of user.

        Returns:
            New Session object with process and captured session_id.
        """
        # Format the message with user context
        message = f"Message from {user_name}: {initial_message}"

        # Create clean environment without CLAUDECODE to avoid nested session errors
        clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        # Spawn Claude CLI process
        # Use stream-json output to capture session_id
        process = await asyncio.create_subprocess_exec(
            "claude",
            "-p",
            message,
            "--verbose",
            "--system-prompt",
            self._system_prompt,
            "--output-format",
            "stream-json",
            cwd=str(self.project_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=clean_env,
            limit=1024 * 1024,  # 1MB buffer for large stream-json lines
        )

        # Read streaming JSON output to capture session_id and response
        session_id = None
        response_text = ""

        if process.stdout:
            async for line in process.stdout:
                try:
                    data = json.loads(line.decode().strip())
                    if "session_id" in data:
                        session_id = data["session_id"]
                    if data.get("type") == "result" and "result" in data:
                        response_text = data["result"]
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Skip malformed lines
                    pass

        # Wait for process to finish
        await process.wait()

        # Handle empty response
        if not response_text:
            response_text = (
                "No response from Mini-Mao. Check if claude CLI is available."
            )

        # Create session object
        session = Session(
            thread_ts=thread_ts,
            process=process,
            session_id=session_id,
            last_activity=time.time(),
            message_count=1,
            last_response=response_text,
        )

        return session

    async def _send_to_claude(self, session: Session, text: str, user_name: str) -> str:
        """Send a follow-up message to an existing session.

        Args:
            session: Active session object.
            text: Message text from user.
            user_name: Slack display name of user.

        Returns:
            Assistant's response text.
        """
        # Format the message with user context
        message = f"Message from {user_name}: {text}"

        # Spawn new process with --resume
        if not session.session_id:
            # Can't resume without session_id
            return "Error: Session lost (no session_id). Please start a new thread."

        # Create clean environment without CLAUDECODE to avoid nested session errors
        clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        process = await asyncio.create_subprocess_exec(
            "claude",
            "-p",
            message,
            "--verbose",
            "--resume",
            session.session_id,
            "--system-prompt",
            self._system_prompt,
            "--output-format",
            "stream-json",
            cwd=str(self.project_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=clean_env,
            limit=1024 * 1024,  # 1MB buffer for large stream-json lines
        )

        # Read streaming JSON output
        response_text = ""

        if process.stdout:
            async for line in process.stdout:
                try:
                    data = json.loads(line.decode().strip())
                    if data.get("type") == "result" and "result" in data:
                        response_text = data["result"]
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

        # Wait for process to finish
        await process.wait()

        # Handle empty response
        if not response_text:
            response_text = (
                "No response from Mini-Mao. Check if claude CLI is available."
            )

        # Update session process reference (though we don't keep it running)
        session.process = process

        return response_text

    async def _idle_check_loop(self) -> None:
        """Periodically check for idle sessions and close them."""
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds

                now = time.time()
                idle_threads = [
                    thread_ts
                    for thread_ts, session in self.sessions.items()
                    if now - session.last_activity > self.idle_timeout
                ]

                for thread_ts in idle_threads:
                    await self.close_session(thread_ts, reason="idle")

            except asyncio.CancelledError:
                break
            except Exception:
                # Don't let idle check crashes kill the manager
                pass

    def _is_shutdown_command(self, text: str) -> str | None:
        """Check if message is a shutdown command.

        Args:
            text: Message text to check.

        Returns:
            Shutdown reason string or None if not a shutdown command.
        """
        text_lower = text.lower().strip()

        shutdown_phrases = {
            "go to sleep": "to sleep",
            "stand down": "stand down",
            "standdown": "stand down",
            "terminate now": "terminate",
            "terminate": "terminate",
            "shutdown": "shutdown",
        }

        for phrase, reason in shutdown_phrases.items():
            if phrase in text_lower:
                return reason

        return None
