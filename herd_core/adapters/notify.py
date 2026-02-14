"""Notification adapter protocol.

Implemented by: herd-notify-slack (reference), or any messaging platform.

Responsible for posting agent activity, status updates, decision records,
and escalations. Supports thread-based conversations for bidirectional
communication (e.g., Architect responding to agent posts).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from herd_core.types import PostResult, ThreadMessage


@runtime_checkable
class NotifyAdapter(Protocol):
    """Posts notifications and manages threaded conversations.

    Design principles:
    - Agent identity (username, icon) is set per-post, not per-connection.
    - Messages are auto-classified by content for the activity ledger.
    - Thread replies enable bidirectional Architect ↔ Agent communication.
    - No external SDK required — stdlib HTTP is sufficient.
    """

    def post(
        self,
        message: str,
        *,
        channel: str | None = None,
        username: str | None = None,
        icon: str | None = None,
    ) -> PostResult:
        """Post a message to a channel.

        Args:
            message: Message content.
            channel: Target channel. Defaults to the primary feed channel.
            username: Display name for this post.
            icon: Emoji icon for this post (e.g., ":hammer:").

        Returns:
            PostResult with message_id and timestamp.
        """
        ...

    def post_thread(
        self,
        thread_id: str,
        message: str,
        *,
        channel: str | None = None,
    ) -> PostResult:
        """Reply to an existing thread."""
        ...

    def get_thread_replies(
        self,
        channel: str,
        thread_id: str,
    ) -> list[ThreadMessage]:
        """Fetch all replies in a thread (excluding the parent message)."""
        ...
