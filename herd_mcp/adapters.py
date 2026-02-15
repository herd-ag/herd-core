"""Adapter registry for dependency injection into MCP tools.

This module provides a registry that holds all adapter instances used by
the Herd MCP server. Adapters provide protocol-based interfaces to external
systems (Slack, Linear, Git, etc.) following the herd-core adapter protocols.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from herd_core.adapters.agent import AgentAdapter
    from herd_core.adapters.notify import NotifyAdapter
    from herd_core.adapters.repo import RepoAdapter
    from herd_core.adapters.store import StoreAdapter
    from herd_core.adapters.tickets import TicketAdapter


@dataclass
class AdapterRegistry:
    """Holds adapter instances for dependency injection into tools.

    Attributes:
        notify: Notification adapter (Slack, etc).
        tickets: Ticket adapter (Linear, etc).
        repo: Repository adapter (Git, etc).
        agent: Agent adapter (Claude, etc).
        store: Data store adapter (DuckDB, etc).
    """

    notify: NotifyAdapter | None = None
    tickets: TicketAdapter | None = None
    repo: RepoAdapter | None = None
    agent: AgentAdapter | None = None
    store: StoreAdapter | None = None
