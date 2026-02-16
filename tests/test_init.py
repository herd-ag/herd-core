"""Tests for herd_core package-level imports and metadata."""

from __future__ import annotations

import herd_core


class TestPackageMetadata:
    """Test package version and metadata."""

    def test_version_is_0_0_1(self) -> None:
        """Package version should be 0.0.1."""
        assert herd_core.__version__ == "0.0.1"


class TestPublicAPI:
    """Test that all __all__ exports are importable."""

    def test_adapter_protocols_importable(self) -> None:
        """All adapter protocols should be importable from herd_core."""
        from herd_core import (
            AgentAdapter,
            NotifyAdapter,
            RepoAdapter,
            StoreAdapter,
            TicketAdapter,
        )

        # Verify they're runtime_checkable protocols by testing isinstance() works
        class Dummy:
            pass

        dummy = Dummy()
        assert not isinstance(dummy, AgentAdapter)
        assert not isinstance(dummy, StoreAdapter)
        assert not isinstance(dummy, TicketAdapter)
        assert not isinstance(dummy, RepoAdapter)
        assert not isinstance(dummy, NotifyAdapter)

    def test_config_importable(self) -> None:
        """HerdConfig should be importable from herd_core."""
        from herd_core import HerdConfig

        assert HerdConfig is not None

    def test_queries_importable(self) -> None:
        """OperationalQueries should be importable from herd_core."""
        from herd_core import OperationalQueries

        assert OperationalQueries is not None

    def test_base_classes_importable(self) -> None:
        """Base classes Entity and Event should be importable."""
        from herd_core import Entity, Event

        assert Entity is not None
        assert Event is not None

    def test_enums_importable(self) -> None:
        """Enums AgentState and TicketPriority should be importable."""
        from herd_core import AgentState, TicketPriority

        assert AgentState is not None
        assert TicketPriority is not None

    def test_entity_types_importable(self) -> None:
        """All 7 entity types should be importable."""
        from herd_core import (
            AgentRecord,
            DecisionRecord,
            ModelRecord,
            PRRecord,
            ReviewRecord,
            SprintRecord,
            TicketRecord,
        )

        assert AgentRecord is not None
        assert DecisionRecord is not None
        assert ModelRecord is not None
        assert PRRecord is not None
        assert ReviewRecord is not None
        assert SprintRecord is not None
        assert TicketRecord is not None

    def test_event_types_importable(self) -> None:
        """All 5 event types should be importable."""
        from herd_core import (
            LifecycleEvent,
            PREvent,
            ReviewEvent,
            TicketEvent,
            TokenEvent,
        )

        assert LifecycleEvent is not None
        assert PREvent is not None
        assert ReviewEvent is not None
        assert TicketEvent is not None
        assert TokenEvent is not None

    def test_return_types_importable(self) -> None:
        """All 6 adapter return types should be importable."""
        from herd_core import (
            CommitInfo,
            PostResult,
            SpawnContext,
            SpawnResult,
            ThreadMessage,
            TransitionResult,
        )

        assert CommitInfo is not None
        assert PostResult is not None
        assert SpawnContext is not None
        assert SpawnResult is not None
        assert ThreadMessage is not None
        assert TransitionResult is not None

    def test_all_exports_count(self) -> None:
        """Should have exactly 29 exports in __all__."""
        assert len(herd_core.__all__) == 29
