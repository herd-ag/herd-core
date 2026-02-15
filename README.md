# The Herd

**Agent team governance framework.**

Execution-agnostic roles, authority models, decision capture, and craft
standards for AI agent teams.

> Your agent framework runs the agents. The Herd runs the team.

## Status

Alpha release (0.2.0). A functioning governance framework with MCP server,
DuckDB-backed operational tracking, .env secret management, content path
resolution, and typed adapter protocols. Eight agents. Thirteen MCP tools.
Tests and CI in place.

## Installation

### Development (editable)

For active development or consuming projects that co-evolve with herd-core:

```bash
pip install -e "/path/to/herd-core[adapters,env]"
```

### Stable (pinned to release tag)

For projects that need a reproducible install:

```bash
pip install "herd-core[adapters] @ git+https://github.com/herd-ag/herd-core@v0.2.0"
```

Requires Python 3.11+.

### Dependencies

| Package | Purpose |
|---------|---------|
| `mcp>=1.0` | Model Context Protocol server |
| `duckdb>=1.0` | Operational database |
| `aiohttp>=3.9` | Async HTTP for REST API |
| `slack_sdk>=3.27` | Slack integration |

Optional extras:

| Extra | Packages |
|-------|----------|
| `env` | `python-dotenv>=1.0` -- loads `.env` files automatically |
| `dev` | `pytest`, `ruff`, `black`, `mypy` -- development tooling |
| `adapters` | All five adapter packages (store, agent, ticket, repo, notify) |

## What is The Herd?

The Herd is a governance framework for AI agent teams. Most agent frameworks
handle execution -- spawning agents, routing messages, managing tool calls.
The Herd handles everything above that: who can do what, how quality is
enforced, how decisions are captured, and how the team operates as a unit.

It is execution-agnostic. Bring your own agent engine (Claude Code, Codex,
CrewAI, or anything else) and plug it in through a typed adapter protocol.

## Environment Setup

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Required variables:

| Variable | Description |
|----------|-------------|
| `HERD_SLACK_TOKEN` | Slack bot token (`xoxb-...`) |
| `LINEAR_API_KEY` | Linear API key (`lin_api_...`) |
| `HERD_AGENT_NAME` | Agent identity code (e.g., `mason`, `steve`) |
| `HERD_DB_PATH` | Database path (default: `.herd/herddb.duckdb`) |

The `.env` file is gitignored and never committed. When `python-dotenv` is
installed (via the `env` extra), values are loaded automatically at server
startup.

## MCP Server

The Herd MCP Server provides 13 tools for operational tracking and team
coordination. Agents interact through MCP tool calls; the server records
all activity to DuckDB and optionally posts to Slack.

### Configuration

Add to your `.mcp.json`:

```json
{
  "mcpServers": {
    "herd": {
      "command": "python3",
      "args": ["-m", "herd_mcp"],
      "env": {
        "HERD_AGENT_NAME": "mason",
        "HERD_DB_PATH": ".herd/herddb.duckdb"
      }
    }
  }
}
```

### Run Modes

| Command | Mode |
|---------|------|
| `python -m herd_mcp` | MCP stdio server (default) |
| `python -m herd_mcp serve` | REST API server |
| `python -m herd_mcp slack` | Daemon with REST API + Slack Socket Mode |

### Tools

| Tool | Purpose |
|------|---------|
| `herd_log` | Post to Slack + log activity |
| `herd_status` | Query agent status, sprint, blockers |
| `herd_spawn` | Register new agent instances |
| `herd_assign` | Assign tickets to agents |
| `herd_transition` | Move tickets between states |
| `herd_review` | Submit QA review findings |
| `herd_metrics` | Query operational metrics |
| `herd_catchup` | Summary of recent activity |
| `herd_decommission` | Permanently decommission agent |
| `herd_standdown` | Temporarily stand down agent |
| `herd_harvest_tokens` | Record token usage and costs |
| `herd_record_decision` | Record agent decision to DuckDB + Slack |
| `herd_assume` | Load agent identity with full context |

See `.herd/docs/mcp-server.md` for the full tool reference.

## Architecture

The Herd uses a **protocol-based adapter design** with five capability
boundaries. Each adapter is a `@runtime_checkable` Protocol (PEP 544),
so implementations use structural subtyping -- no inheritance required.

The type system has two hierarchies:

- **Entity** -- mutable domain records with identity, timestamps, and soft
  deletes. Persisted via `StoreAdapter.save()`, retrieved via `.get()` and
  `.list()`.
- **Event** -- immutable, append-only audit trail records. Written once via
  `StoreAdapter.append()`, never updated or deleted.

### Content Path Resolution

`get_herd_content_path()` resolves `.herd/` content with a two-step fallback:

1. **Project root** `.herd/` -- project-specific overrides
2. **Package root** `.herd/` -- canonical defaults from herd-core install

This means consuming projects can override any role file, craft standard, or
template by placing their own version in their `.herd/` directory. A bare
`pip install` gives working defaults out of the box.

### Packages

| Package | Purpose | Adapter |
|---------|---------|---------|
| `herd-core` | Framework interfaces, types, config, queries, MCP server | -- |
| `herd-store-duckdb` | DuckDB/MotherDuck persistence + dbt schema + Evidence dashboards | StoreAdapter |
| `herd-agent-claude` | Claude Code CLI execution | AgentAdapter |
| `herd-ticket-linear` | Linear.app ticket lifecycle | TicketAdapter |
| `herd-repo-github` | GitHub PRs, branches, commits | RepoAdapter |
| `herd-notify-slack` | Slack messaging | NotifyAdapter |

## Quick Start

```python
from herd_core import (
    HerdConfig,
    AgentRecord,
    TicketRecord,
    LifecycleEvent,
    AgentState,
    TicketPriority,
    OperationalQueries,
    StoreAdapter,
)

# Configure the project
config = HerdConfig(project="my-project")

# Entities are mutable domain records with identity
agent = AgentRecord(
    id="agent-001",
    agent="mason",
    model="claude-sonnet-4-5",
    ticket_id="PROJ-42",
    state=AgentState.RUNNING,
    branch="herd/mason/proj-42-fix-auth",
)

ticket = TicketRecord(
    id="PROJ-42",
    title="Fix authentication flow",
    status="in_progress",
    priority=TicketPriority.HIGH,
    labels=["bug", "auth"],
)

# Events are immutable audit trail records
event = LifecycleEvent(
    entity_id="agent-001",
    event_type="started",
    instance_id="agent-001",
    detail="Agent spawned on PROJ-42",
)

# The query layer composes StoreAdapter calls into typed results
def run_queries(store: StoreAdapter) -> None:
    queries = OperationalQueries(store)
    active = queries.active_agents()
    timeline = queries.ticket_timeline("PROJ-42")
    costs = queries.cost_summary()
    blocked = queries.blocked_tickets()
```

## Type Inventory

All 29 public exports from `herd_core`:

| Category | Types |
|----------|-------|
| Entities (7) | `AgentRecord`, `TicketRecord`, `PRRecord`, `DecisionRecord`, `ReviewRecord`, `ModelRecord`, `SprintRecord` |
| Events (5) | `LifecycleEvent`, `TicketEvent`, `PREvent`, `ReviewEvent`, `TokenEvent` |
| Enums (2) | `AgentState`, `TicketPriority` |
| Base classes (2) | `Entity`, `Event` |
| Return types (6) | `SpawnContext`, `SpawnResult`, `TransitionResult`, `PostResult`, `ThreadMessage`, `CommitInfo` |
| Config (1) | `HerdConfig` (with `TicketConfig`, `NotifyConfig`, `AgentConfig`, `StoreConfig`, `RepoConfig`) |
| Protocols (5) | `StoreAdapter`, `AgentAdapter`, `TicketAdapter`, `RepoAdapter`, `NotifyAdapter` |
| Queries (1) | `OperationalQueries` |

## Adapter Protocol Example

Adapters implement the protocol structurally -- no base class needed.
Here is a minimal `StoreAdapter` skeleton:

```python
from __future__ import annotations

from typing import Any, TypeVar

from herd_core import Entity, Event, StoreAdapter

E = TypeVar("E", bound=Entity)


class MyStore:
    """A custom store backend. Implements StoreAdapter structurally."""

    def get(self, entity_type: type[E], id: str) -> E | None:
        ...  # Look up by type and id

    def list(self, entity_type: type[E], **filters: Any) -> list[E]:
        ...  # Query with field-value filters

    def save(self, record: Entity) -> str:
        ...  # Upsert, return id

    def delete(self, entity_type: type[E], id: str) -> None:
        ...  # Soft-delete (set deleted_at)

    def append(self, event: Event) -> None:
        ...  # Append-only, never update

    def count(self, entity_type: type[E], **filters: Any) -> int:
        ...  # Count matching records

    def events(self, event_type: type[Event], **filters: Any) -> list[Event]:
        ...  # Query the activity ledger


# Structural subtyping -- no inheritance, just matching signatures
assert isinstance(MyStore(), StoreAdapter)
```

All five adapter protocols follow this pattern. See
[`herd_core/adapters/`](herd_core/adapters/) for the full protocol
definitions.

## Version History

| Version | Date | Summary |
|---------|------|---------|
| 0.2.0 | 2026-02-15 | MCP server, .env support, content path resolution, roster rename (HDR-0024) |
| 0.1.0 | 2026-02-13 | Fixture rename, Vigil CI, helper/assume_role ports, role/HDR sync |
| 0.0.1 | 2026-02-11 | Initial release -- type system, adapter protocols, config, queries |

## License

MIT
