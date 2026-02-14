"""Herd configuration system.

Externalizes project-specific settings that adapters and the MCP server
need at runtime: ticket state mappings, channel defaults, model assignments,
worktree paths, etc.

Configuration can be loaded from:
- A herd.toml or herd.yml file in the project root
- Environment variables (HERD_*)
- Programmatic construction

This module defines the schema. Loading is adapter-independent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TicketConfig:
    """Ticket system configuration."""

    team_id: str = ""
    project_id: str = ""
    state_mapping: dict[str, str] = field(default_factory=dict)
    """Maps logical status names to backend-specific IDs.

    Example (Linear):
        {"backlog": "f98ff170-...", "in_progress": "77631f63-...", "done": "42bad6cf-..."}
    """


@dataclass
class NotifyConfig:
    """Notification system configuration."""

    default_channel: str = ""
    channels: dict[str, str] = field(default_factory=dict)
    """Maps logical channel names to backend-specific IDs.

    Example (Slack):
        {"feed": "#herd-feed", "blocked": "#herd-blocked", "decisions": "#herd-decisions"}
    """


@dataclass
class AgentConfig:
    """Agent execution configuration."""

    worktree_root: str = "/private/tmp"
    branch_prefix: str = "herd"
    default_model: str = ""
    role_models: dict[str, str] = field(default_factory=dict)
    """Maps role codes to default model codes.

    Example:
        {"grunt": "claude-sonnet-4-5", "wardenstein": "claude-opus-4-6"}
    """


@dataclass
class StoreConfig:
    """Storage configuration."""

    backend: str = "duckdb"
    path: str = ""
    schema: str = "herd"
    extra: dict[str, Any] = field(default_factory=dict)
    """Backend-specific settings.

    Example (DuckDB): {"path": ".herd/herddb.duckdb"}
    Example (MotherDuck): {"connection": "md:herd_prod"}
    """


@dataclass
class RepoConfig:
    """Repository configuration."""

    owner: str = ""
    name: str = ""
    default_base: str = "main"


@dataclass
class HerdConfig:
    """Top-level Herd configuration.

    Single source of truth for all project-specific settings that the
    framework and adapters need. Eliminates hard-coded values in tool
    implementations.

    Load from file:
        config = HerdConfig.from_file("herd.toml")

    Or construct programmatically:
        config = HerdConfig(
            project="dbt-conceptual",
            tickets=TicketConfig(team_id="b8dc3e4b", ...),
            ...
        )
    """

    project: str = ""
    tickets: TicketConfig = field(default_factory=TicketConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    agents: AgentConfig = field(default_factory=AgentConfig)
    store: StoreConfig = field(default_factory=StoreConfig)
    repo: RepoConfig = field(default_factory=RepoConfig)
