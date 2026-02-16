"""Tests for adapter protocol definitions and runtime_checkable behavior."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from herd_core.adapters import (
    AgentAdapter,
    NotifyAdapter,
    RepoAdapter,
    StoreAdapter,
    TicketAdapter,
)
from herd_core.types import (
    AgentRecord,
    CommitInfo,
    Entity,
    Event,
    PostResult,
    PRRecord,
    SpawnContext,
    SpawnResult,
    ThreadMessage,
    TicketRecord,
    TransitionResult,
)


class TestStoreAdapterProtocol:
    """Test StoreAdapter protocol conformance checking."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """StoreAdapter should be @runtime_checkable."""

        # Verify protocol works with isinstance() - that's what @runtime_checkable enables
        class Dummy:
            pass

        assert not isinstance(Dummy(), StoreAdapter)

    def test_conforming_implementation_passes(self) -> None:
        """isinstance() check passes for conforming implementation."""

        class ConformingStore:
            """Minimal StoreAdapter implementation."""

            def get(self, entity_type: type[Entity], id: str) -> Entity | None:
                return None

            def list(self, entity_type: type[Entity], **filters: Any) -> list[Entity]:
                return []

            def save(self, record: Entity) -> str:
                return record.id

            def delete(self, entity_type: type[Entity], id: str) -> None:
                pass

            def append(self, event: Event) -> None:
                pass

            def count(self, entity_type: type[Entity], **filters: Any) -> int:
                return 0

            def events(self, event_type: type[Event], **filters: Any) -> list[Event]:
                return []

        store = ConformingStore()
        assert isinstance(store, StoreAdapter)

    def test_non_conforming_implementation_fails(self) -> None:
        """isinstance() check fails for non-conforming implementation."""

        class NonConformingStore:
            """Missing methods — does NOT implement StoreAdapter."""

            def get(self, entity_type: type[Entity], id: str) -> Entity | None:
                return None

            # Missing other methods

        store = NonConformingStore()
        assert not isinstance(store, StoreAdapter)


class TestTicketAdapterProtocol:
    """Test TicketAdapter protocol conformance checking."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """TicketAdapter should be @runtime_checkable."""

        # Verify protocol works with isinstance() - that's what @runtime_checkable enables
        class Dummy:
            pass

        assert not isinstance(Dummy(), TicketAdapter)

    def test_conforming_implementation_passes(self) -> None:
        """isinstance() check passes for conforming implementation."""

        class ConformingTickets:
            """Minimal TicketAdapter implementation."""

            def get(self, ticket_id: str) -> TicketRecord:
                return TicketRecord(id=ticket_id)

            def create(
                self,
                title: str,
                **kwargs: Any,
            ) -> str:
                return "DBC-001"

            def update(self, ticket_id: str, **fields: Any) -> None:
                pass

            def transition(
                self,
                ticket_id: str,
                to_status: str,
                **kwargs: Any,
            ) -> TransitionResult:
                return TransitionResult(
                    ticket_id=ticket_id,
                    previous_status="backlog",
                    new_status=to_status,
                    event_type="transition",
                )

            def add_comment(self, ticket_id: str, body: str) -> None:
                pass

            def list_tickets(self, **filters: Any) -> list[TicketRecord]:
                return []

        tickets = ConformingTickets()
        assert isinstance(tickets, TicketAdapter)

    def test_non_conforming_implementation_fails(self) -> None:
        """isinstance() check fails for non-conforming implementation."""

        class NonConformingTickets:
            """Missing methods."""

            def get(self, ticket_id: str) -> TicketRecord:
                return TicketRecord(id=ticket_id)

        tickets = NonConformingTickets()
        assert not isinstance(tickets, TicketAdapter)


class TestAgentAdapterProtocol:
    """Test AgentAdapter protocol conformance checking."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """AgentAdapter should be @runtime_checkable."""

        # Verify protocol works with isinstance() - that's what @runtime_checkable enables
        class Dummy:
            pass

        assert not isinstance(Dummy(), AgentAdapter)

    def test_conforming_implementation_passes(self) -> None:
        """isinstance() check passes for conforming implementation."""

        class ConformingAgent:
            """Minimal AgentAdapter implementation."""

            def spawn(
                self,
                role: str,
                ticket_id: str,
                context: SpawnContext,
                **kwargs: Any,
            ) -> SpawnResult:
                return SpawnResult(
                    instance_id="agent-001",
                    agent=role,
                    ticket_id=ticket_id,
                    model="test-model",
                    worktree="/tmp/test",
                    branch="test-branch",
                    spawned_at=datetime.now(timezone.utc),
                )

            def get_status(self, instance_id: str) -> AgentRecord:
                return AgentRecord(id=instance_id)

            def stop(self, instance_id: str) -> None:
                pass

        agent = ConformingAgent()
        assert isinstance(agent, AgentAdapter)

    def test_non_conforming_implementation_fails(self) -> None:
        """isinstance() check fails for non-conforming implementation."""

        class NonConformingAgent:
            """Missing methods."""

            def spawn(
                self,
                role: str,
                ticket_id: str,
                context: SpawnContext,
                **kwargs: Any,
            ) -> SpawnResult:
                return SpawnResult(
                    instance_id="agent-001",
                    agent=role,
                    ticket_id=ticket_id,
                    model="test-model",
                    worktree="/tmp/test",
                    branch="test-branch",
                    spawned_at=datetime.now(timezone.utc),
                )

        agent = NonConformingAgent()
        assert not isinstance(agent, AgentAdapter)


class TestRepoAdapterProtocol:
    """Test RepoAdapter protocol conformance checking."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """RepoAdapter should be @runtime_checkable."""

        # Verify protocol works with isinstance() - that's what @runtime_checkable enables
        class Dummy:
            pass

        assert not isinstance(Dummy(), RepoAdapter)

    def test_conforming_implementation_passes(self) -> None:
        """isinstance() check passes for conforming implementation."""

        class ConformingRepo:
            """Minimal RepoAdapter implementation."""

            def create_branch(self, name: str, **kwargs: Any) -> str:
                return name

            def create_worktree(self, branch: str, path: str) -> str:
                return path

            def remove_worktree(self, path: str) -> None:
                pass

            def push(self, branch: str) -> None:
                pass

            def create_pr(
                self,
                title: str,
                body: str,
                **kwargs: Any,
            ) -> str:
                return "pr-001"

            def get_pr(self, pr_id: str) -> PRRecord:
                return PRRecord(id=pr_id)

            def merge_pr(self, pr_id: str) -> None:
                pass

            def add_pr_comment(self, pr_id: str, body: str) -> None:
                pass

            def get_log(self, **kwargs: Any) -> list[CommitInfo]:
                return []

        repo = ConformingRepo()
        assert isinstance(repo, RepoAdapter)

    def test_non_conforming_implementation_fails(self) -> None:
        """isinstance() check fails for non-conforming implementation."""

        class NonConformingRepo:
            """Missing methods."""

            def create_branch(self, name: str, **kwargs: Any) -> str:
                return name

        repo = NonConformingRepo()
        assert not isinstance(repo, RepoAdapter)


class TestNotifyAdapterProtocol:
    """Test NotifyAdapter protocol conformance checking."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """NotifyAdapter should be @runtime_checkable."""

        # Verify protocol works with isinstance() - that's what @runtime_checkable enables
        class Dummy:
            pass

        assert not isinstance(Dummy(), NotifyAdapter)

    def test_conforming_implementation_passes(self) -> None:
        """isinstance() check passes for conforming implementation."""

        class ConformingNotify:
            """Minimal NotifyAdapter implementation."""

            def post(
                self,
                message: str,
                **kwargs: Any,
            ) -> PostResult:
                return PostResult(
                    message_id="msg-001",
                    channel="#test",
                    timestamp="1234567890",
                )

            def post_thread(
                self,
                thread_id: str,
                message: str,
                **kwargs: Any,
            ) -> PostResult:
                return PostResult(
                    message_id="msg-002",
                    channel="#test",
                    timestamp="1234567891",
                )

            def get_thread_replies(
                self,
                channel: str,
                thread_id: str,
            ) -> list[ThreadMessage]:
                return []

            def search(
                self,
                query: str,
                **kwargs: Any,
            ) -> list[ThreadMessage]:
                return []

        notify = ConformingNotify()
        assert isinstance(notify, NotifyAdapter)

    def test_non_conforming_implementation_fails(self) -> None:
        """isinstance() check fails for non-conforming implementation."""

        class NonConformingNotify:
            """Missing methods."""

            def post(
                self,
                message: str,
                **kwargs: Any,
            ) -> PostResult:
                return PostResult(
                    message_id="msg-001",
                    channel="#test",
                    timestamp="1234567890",
                )

        notify = NonConformingNotify()
        assert not isinstance(notify, NotifyAdapter)
