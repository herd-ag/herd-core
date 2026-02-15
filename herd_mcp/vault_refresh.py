"""Vault refresh manager for milestone-triggered dbt runs.

This module implements the VaultRefreshManager singleton that handles
async mutex-based dbt runs triggered by milestone events (agent completions,
PR merges, reviews, etc.). The manager ensures only one dbt run executes at
a time, queues at most one pending run, and collapses redundant triggers.
"""

from __future__ import annotations

import asyncio
import logging
from typing import ClassVar

logger = logging.getLogger(__name__)


class VaultRefreshManager:
    """Singleton manager for milestone-triggered dbt vault refreshes.

    This class uses an async mutex (asyncio.Lock) to ensure:
    1. Only one dbt run executes at a time
    2. At most one run is queued when a run is in progress
    3. Redundant triggers during execution are idempotently collapsed

    Milestones that trigger refreshes:
    - Agent completion (status transition to 'done')
    - PR created or merged
    - Review submitted
    - Agent decommissioned
    - Sprint boundary transitions
    """

    _instance: ClassVar[VaultRefreshManager | None] = None
    _lock: asyncio.Lock
    _running: bool
    _pending_refresh: bool
    _pending_context: dict | None
    _project_dir: str
    _profiles_dir: str

    def __new__(cls) -> VaultRefreshManager:
        """Singleton pattern - ensure only one instance exists."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Initialize the manager state."""
        self._lock = asyncio.Lock()
        self._running = False
        self._pending_refresh = False
        self._pending_context = None
        self._project_dir = ".herd/dbt"
        self._profiles_dir = ".herd/dbt"
        logger.info("VaultRefreshManager initialized")

    async def trigger_refresh(
        self, milestone: str, context: dict | None = None
    ) -> dict:
        """Trigger a vault refresh for a milestone event.

        This method implements the async mutex pattern:
        - If no run is active, starts immediately
        - If a run is active, marks one refresh as pending
        - Multiple triggers during active run collapse to single pending refresh

        Args:
            milestone: The milestone type (e.g., 'agent_completed', 'pr_merged', 'review_submitted')
            context: Optional context dict with details about the milestone event

        Returns:
            Dict with refresh status and execution details
        """
        context = context or {}

        # Check if already running (no TOCTOU race - single flag check)
        if self._running:
            # A refresh is already running
            if not self._pending_refresh:
                self._pending_refresh = True
                self._pending_context = context  # A1: Preserve queued context
                logger.info(
                    f"Vault refresh in progress, queued refresh for milestone: {milestone}",
                    extra={"milestone": milestone, "context": context},
                )
                return {
                    "status": "queued",
                    "milestone": milestone,
                    "message": "Refresh queued - run already in progress",
                }
            else:
                # Collapse redundant trigger (keep most recent context)
                self._pending_context = context
                logger.info(
                    f"Vault refresh already queued, collapsed trigger for milestone: {milestone}",
                    extra={"milestone": milestone, "context": context},
                )
                return {
                    "status": "collapsed",
                    "milestone": milestone,
                    "message": "Trigger collapsed - refresh already queued",
                }

        # Acquire lock and run refresh
        async with self._lock:
            self._running = True
            try:
                result = await self._execute_refresh(milestone, context)

                # If a refresh was queued during execution, run it now
                while self._pending_refresh:
                    self._pending_refresh = False
                    queued_context = self._pending_context
                    self._pending_context = None
                    logger.info("Executing queued vault refresh")
                    queued_result = await self._execute_refresh(
                        "queued_refresh", queued_context or {}
                    )
                    result = {
                        "status": "completed_with_queued",
                        "milestone": milestone,
                        "primary_result": result,
                        "queued_result": queued_result,
                    }

                return result
            finally:
                self._running = False  # A2: Always reset in finally

    async def _execute_refresh(self, milestone: str, context: dict) -> dict:
        """Execute the dbt run subprocess.

        Args:
            milestone: The milestone type triggering the refresh
            context: Context dict with event details

        Returns:
            Dict with execution results
        """
        logger.info(
            f"Starting vault refresh for milestone: {milestone}",
            extra={"milestone": milestone, "context": context},
        )

        # Build dbt run command
        cmd = [
            "dbt",
            "run",
            "--project-dir",
            self._project_dir,
            "--profiles-dir",
            self._profiles_dir,
        ]

        try:
            # Run dbt in subprocess (use asyncio.create_subprocess_exec for true async)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await proc.communicate()

            stdout_str = stdout.decode() if stdout else ""
            stderr_str = stderr.decode() if stderr else ""

            if proc.returncode == 0:
                logger.info(
                    f"Vault refresh completed successfully for milestone: {milestone}",
                    extra={"milestone": milestone, "returncode": proc.returncode},
                )
                return {
                    "status": "success",
                    "milestone": milestone,
                    "returncode": proc.returncode,
                    "stdout": stdout_str,
                    "context": context,
                }
            else:
                logger.error(
                    f"Vault refresh failed for milestone: {milestone}",
                    extra={
                        "milestone": milestone,
                        "returncode": proc.returncode,
                        "stderr": stderr_str,
                    },
                )
                return {
                    "status": "error",
                    "milestone": milestone,
                    "returncode": proc.returncode,
                    "stdout": stdout_str,
                    "stderr": stderr_str,
                    "context": context,
                }

        except FileNotFoundError:
            logger.error("dbt command not found - is dbt installed?")
            return {
                "status": "error",
                "milestone": milestone,
                "error": "dbt command not found",
                "message": "dbt is not installed or not in PATH",
                "context": context,
            }
        except Exception as e:
            logger.error(
                f"Unexpected error during vault refresh: {e}",
                extra={"milestone": milestone, "error": str(e)},
            )
            return {
                "status": "error",
                "milestone": milestone,
                "error": str(e),
                "context": context,
            }


def get_manager() -> VaultRefreshManager:
    """Get the singleton VaultRefreshManager instance.

    Returns:
        The singleton VaultRefreshManager instance
    """
    return VaultRefreshManager()
