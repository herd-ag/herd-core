"""Agent execution adapter protocol.

Implemented by: herd-agent-claude (reference), or any agent engine.

Responsible for spawning isolated agent instances, tracking their lifecycle,
and providing the full context envelope required by Herd governance.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from herd_core.types import AgentStatus, SpawnContext, SpawnResult


@runtime_checkable
class AgentAdapter(Protocol):
    """Spawns and manages agent instances.

    Each spawn creates an isolated execution environment (e.g., a git worktree)
    with full context: role definition, craft standards, project guidelines,
    and skill definitions. Partial context spawns violate Herd governance.
    """

    def spawn(
        self,
        role: str,
        ticket_id: str,
        context: SpawnContext,
        *,
        model: str | None = None,
    ) -> SpawnResult:
        """Spawn an agent instance with full context.

        Args:
            role: Agent role code (e.g., "grunt", "pikasso", "wardenstein").
            ticket_id: Ticket identifier for this assignment.
            context: Complete context envelope. Must not be partial.
            model: Optional model override. Defaults to role's configured model.

        Returns:
            SpawnResult with instance_id, worktree path, and branch name.
        """
        ...

    def get_status(self, instance_id: str) -> AgentStatus:
        """Get current status of an agent instance."""
        ...

    def stop(self, instance_id: str) -> None:
        """Stop a running agent instance."""
        ...
