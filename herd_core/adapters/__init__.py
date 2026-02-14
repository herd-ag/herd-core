"""Adapter protocol interfaces for The Herd.

Each protocol defines a capability boundary that adapter packages implement:

    herd-agent-claude  → AgentAdapter
    herd-store-duckdb  → StoreAdapter
    herd-ticket-linear → TicketAdapter
    herd-repo-github   → RepoAdapter
    herd-notify-slack  → NotifyAdapter

Protocols use structural subtyping (PEP 544) — adapters implement the
interface without inheriting from it.
"""

from herd_core.adapters.agent import AgentAdapter
from herd_core.adapters.notify import NotifyAdapter
from herd_core.adapters.repo import RepoAdapter
from herd_core.adapters.store import StoreAdapter
from herd_core.adapters.tickets import TicketAdapter

__all__ = [
    "AgentAdapter",
    "StoreAdapter",
    "TicketAdapter",
    "RepoAdapter",
    "NotifyAdapter",
]
