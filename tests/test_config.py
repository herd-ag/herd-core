"""Tests for herd_core.config module — configuration dataclasses."""

from __future__ import annotations

from herd_core.config import (
    AgentConfig,
    HerdConfig,
    NotifyConfig,
    RepoConfig,
    StoreConfig,
    TicketConfig,
)


class TestTicketConfig:
    """Test TicketConfig dataclass."""

    def test_default_construction(self) -> None:
        """TicketConfig constructs with empty defaults."""
        config = TicketConfig()
        assert config.team_id == ""
        assert config.project_id == ""
        assert config.state_mapping == {}

    def test_state_mapping_accepts_dict(self) -> None:
        """TicketConfig.state_mapping accepts and stores dict."""
        mapping = {
            "backlog": "f98ff170-87bd-4a1c-badc-4b67cd37edec",
            "in_progress": "77631f63-b27b-45a5-8b04-f9f82b4facde",
            "done": "42bad6cf-cfb7-4dd2-9dc4-c0c3014bfc5f",
        }
        config = TicketConfig(state_mapping=mapping)
        assert config.state_mapping == mapping
        assert config.state_mapping["backlog"] == "f98ff170-87bd-4a1c-badc-4b67cd37edec"


class TestNotifyConfig:
    """Test NotifyConfig dataclass."""

    def test_default_construction(self) -> None:
        """NotifyConfig constructs with empty defaults."""
        config = NotifyConfig()
        assert config.default_channel == ""
        assert config.channels == {}

    def test_channels_accepts_dict(self) -> None:
        """NotifyConfig.channels accepts and stores dict."""
        channels = {
            "feed": "#herd-feed",
            "blocked": "#herd-blocked",
            "decisions": "#herd-decisions",
        }
        config = NotifyConfig(channels=channels)
        assert config.channels == channels
        assert config.channels["feed"] == "#herd-feed"


class TestAgentConfig:
    """Test AgentConfig dataclass."""

    def test_default_construction(self) -> None:
        """AgentConfig constructs with defaults."""
        config = AgentConfig()
        assert config.worktree_root == "/private/tmp"
        assert config.branch_prefix == "herd"
        assert config.default_model == ""
        assert config.role_models == {}

    def test_role_models_accepts_dict(self) -> None:
        """AgentConfig.role_models accepts and stores dict."""
        models = {
            "mason": "claude-sonnet-4-5",
            "wardenstein": "claude-opus-4-6",
            "fresco": "claude-sonnet-4-5",
        }
        config = AgentConfig(role_models=models)
        assert config.role_models == models
        assert config.role_models["mason"] == "claude-sonnet-4-5"


class TestStoreConfig:
    """Test StoreConfig dataclass."""

    def test_default_construction(self) -> None:
        """StoreConfig constructs with defaults."""
        config = StoreConfig()
        assert config.backend == "duckdb"
        assert config.path == ""
        assert config.schema == "herd"
        assert config.extra == {}

    def test_extra_accepts_backend_specific_settings(self) -> None:
        """StoreConfig.extra accepts backend-specific settings."""
        config = StoreConfig(extra={"path": ".herd/herddb.duckdb"})
        assert config.extra["path"] == ".herd/herddb.duckdb"


class TestRepoConfig:
    """Test RepoConfig dataclass."""

    def test_default_construction(self) -> None:
        """RepoConfig constructs with defaults."""
        config = RepoConfig()
        assert config.owner == ""
        assert config.name == ""
        assert config.default_base == "main"


class TestHerdConfig:
    """Test HerdConfig top-level configuration."""

    def test_default_construction(self) -> None:
        """HerdConfig constructs with all sub-config defaults."""
        config = HerdConfig()
        assert config.project == ""
        assert isinstance(config.tickets, TicketConfig)
        assert isinstance(config.notify, NotifyConfig)
        assert isinstance(config.agents, AgentConfig)
        assert isinstance(config.store, StoreConfig)
        assert isinstance(config.repo, RepoConfig)

    def test_composes_all_subconfigs(self) -> None:
        """HerdConfig composes all sub-configs."""
        config = HerdConfig(
            project="dbt-conceptual",
            tickets=TicketConfig(team_id="b8dc3e4b"),
            notify=NotifyConfig(default_channel="#herd-feed"),
            agents=AgentConfig(worktree_root="/private/tmp"),
            store=StoreConfig(backend="duckdb", schema="herd"),
            repo=RepoConfig(owner="dbt-conceptual", name="herd-core"),
        )
        assert config.project == "dbt-conceptual"
        assert config.tickets.team_id == "b8dc3e4b"
        assert config.notify.default_channel == "#herd-feed"
        assert config.agents.worktree_root == "/private/tmp"
        assert config.store.backend == "duckdb"
        assert config.repo.owner == "dbt-conceptual"
