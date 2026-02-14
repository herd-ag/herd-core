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
    AgentState,
    AgentStatus,
    PostResult,
    PRState,
    QueryResult,
    SpawnContext,
    SpawnResult,
    ThreadMessage,
    TicketPriority,
    TicketState,
    TransitionResult,
)

__all__ = [
    # Adapter protocols
    "AgentAdapter",
    "StoreAdapter",
    "TicketAdapter",
    "RepoAdapter",
    "NotifyAdapter",
    # Types
    "AgentState",
    "AgentStatus",
    "SpawnContext",
    "SpawnResult",
    "TicketPriority",
    "TicketState",
    "TransitionResult",
    "PRState",
    "PostResult",
    "ThreadMessage",
    "QueryResult",
]
