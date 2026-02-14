"""
The Herd — Agent team governance framework.

Execution-agnostic roles, authority models, decision capture,
and craft standards for AI agent teams.

https://github.com/dbt-conceptual/herd-core
"""

__version__ = "0.0.1"

from herd_core.adapters import (
    AgentAdapter,
    NotifyAdapter,
    RepoAdapter,
    StoreAdapter,
    TicketAdapter,
)
from herd_core.types import (
    # Base classes
    Entity,
    Event,
    # Enums
    AgentState,
    TicketPriority,
    # Entities
    AgentRecord,
    DecisionRecord,
    PRRecord,
    ReviewRecord,
    TicketRecord,
    # Events
    LifecycleEvent,
    PREvent,
    ReviewEvent,
    TicketEvent,
    TokenEvent,
    # Adapter return types
    PostResult,
    SpawnContext,
    SpawnResult,
    ThreadMessage,
    TransitionResult,
)

__all__ = [
    # Adapter protocols
    "AgentAdapter",
    "StoreAdapter",
    "TicketAdapter",
    "RepoAdapter",
    "NotifyAdapter",
    # Base classes
    "Entity",
    "Event",
    # Enums
    "AgentState",
    "TicketPriority",
    # Entities
    "AgentRecord",
    "TicketRecord",
    "PRRecord",
    "DecisionRecord",
    "ReviewRecord",
    # Events
    "LifecycleEvent",
    "TicketEvent",
    "PREvent",
    "ReviewEvent",
    "TokenEvent",
    # Adapter return types
    "SpawnContext",
    "SpawnResult",
    "TransitionResult",
    "PostResult",
    "ThreadMessage",
]
