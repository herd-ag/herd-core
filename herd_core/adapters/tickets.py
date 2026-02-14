"""Ticket lifecycle adapter protocol.

Implemented by: herd-ticket-linear (reference), or any project management tool.

Responsible for creating, updating, and transitioning tickets through their
lifecycle. Every state change is recorded as an activity event for auditability.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from herd_core.types import TicketState, TransitionResult


@runtime_checkable
class TicketAdapter(Protocol):
    """Manages ticket lifecycle in an external project management system.

    Design principles:
    - Auto-registration: if a ticket_id is valid in the external system but
      not yet in the local store, fetch and register it automatically.
    - Every transition is an auditable event, not just a field update.
    - Blocking is a first-class concept with blocker references.
    """

    def get(self, ticket_id: str) -> TicketState:
        """Fetch current state of a ticket."""
        ...

    def create(
        self,
        title: str,
        *,
        description: str | None = None,
        team_id: str | None = None,
        project_id: str | None = None,
        priority: int | None = None,
        labels: list[str] | None = None,
        **kwargs: Any,
    ) -> str:
        """Create a new ticket. Returns the ticket identifier."""
        ...

    def update(self, ticket_id: str, **fields: Any) -> None:
        """Update ticket fields (title, description, labels, etc.)."""
        ...

    def transition(
        self,
        ticket_id: str,
        to_status: str,
        *,
        note: str | None = None,
        blocked_by: list[str] | None = None,
    ) -> TransitionResult:
        """Transition a ticket to a new status.

        Args:
            ticket_id: Ticket identifier.
            to_status: Target status name or ID.
            note: Optional note explaining the transition.
            blocked_by: Ticket IDs that block this one (for "blocked" transitions).

        Returns:
            TransitionResult with previous/new status and elapsed time.
        """
        ...

    def add_comment(self, ticket_id: str, body: str) -> None:
        """Add a comment to a ticket."""
        ...

    def list_tickets(self, **filters: Any) -> list[TicketState]:
        """List tickets matching filters (status, assignee, project, etc.)."""
        ...
