# The Herd

A governance framework for AI agent teams.

Most multi-agent systems solve execution: spawn an agent, run a task, discard the context. The Herd solves everything above execution — roles, authority, quality gates, decision capture, long-term memory, and the ability to learn from its own process. It is organizational design applied to AI agents, informed by how effective human teams actually work.

> Your agent framework runs the agents. The Herd runs the team.

## Why

Agent frameworks give you functions that call functions. You get orchestration, tool routing, maybe a supervisor loop. What you don't get is a team.

Real teams have structure. Someone decides scope. Someone else reviews quality — independently, not as a rubber stamp. Decisions get recorded so they're not relitigated. Knowledge accumulates across sessions. New members inherit context instead of starting blind. The team measures its own performance and adjusts.

None of this is execution. It's governance. And no agent framework provides it, because they're built around the assumption that agents are stateless workers to be dispatched and discarded.

The Herd rejects that assumption. Agents are team members with defined roles, bounded authority, persistent memory, and accountability. The framework provides the organizational substrate — who can do what, how work flows, how quality is enforced, and how the team gets better over time.

## How It Works

The Herd models real team structure. Nine agents occupy distinct roles:

| Role | Agent | Responsibility |
|------|-------|---------------|
| Leader | **Steve** | Coordinates work, captures decisions, spawns agents. Never codes. |
| Leader | **Leonardo** | Remote-host leader. Manages Metropolis team independently. |
| Builder | **Mason** | Backend craft — code, tests, architecture implementation. |
| Builder | **Fresco** | Frontend craft — UI, design systems, visual implementation. |
| QA | **Wardenstein** | Independent quality review. Rejects PRs that fail standards. |
| Docs | **Scribe** | Documentation — READMEs, guides, decision records. |
| Security | **Vigil** | CI enforcement, security scanning, automated checks. |
| Execution | **Rook** | Simple bounded tasks. Mechanical. No context pane. |
| Data | **Tufte** | Dashboards, analytics, data visualization. |

Roles carry authority boundaries. Leaders coordinate but never write code. QA reviews independently — it does not report to the leader whose work it reviews. Builders build within their assigned scope. These aren't suggestions; they're enforced constraints.

Teams map to physical hosts the way real teams map to offices. Avalon (a MacBook) and Metropolis (a Linux server) each run their own leader and local agents. Cross-location coordination happens through an asynchronous message bus — not shared infrastructure, not synchronous calls. A leader on one host sends a directive to a leader on another, who manages their own team's execution. This is how distributed human teams actually work.

## The Tristore

No single database does everything well. The Herd uses three purpose-built stores behind a unified MCP interface:

**DuckDB — operational and analytical store.** Every ticket, agent spawn, state transition, token count, estimated cost, and sprint metric is recorded as queryable dimensional data. This is the system of record for what happened and what it cost. Slice by project, agent, time period, skill version. Built on Data Vault 2.0 modeling with 87 dbt models (hubs, links, satellites, dimensions, facts). This is how the Herd measures itself.

**LanceDB — semantic memory.** Decisions, session summaries, retrospectives, discovered patterns. Stored as vector embeddings, searchable by concept rather than keyword. An agent asking "what did we decide about authentication?" gets relevant decisions ranked by semantic similarity, not a SQL query that requires knowing the exact column value. This is how the Herd remembers.

**KùzuDB — structural graph.** A property graph connecting tickets to decisions to components to deliveries. Which decisions affect which components. Which agents touched which code. Which QA results relate to which PRs. Graph traversal answers structural questions that neither relational queries nor vector search can: "show me everything downstream of this architectural decision." This is how the Herd reasons about context.

### The compound value

These stores are more powerful together than apart. A single `herd_assume` call — the operation that loads an agent's identity at session start — assembles full context from all three stores plus the filesystem:

1. Role definition and craft standards (filesystem)
2. Relevant architectural decisions (LanceDB, semantic search)
3. Assigned tickets and current sprint state (DuckDB, operational query)
4. Pending messages from other agents (DiskCache message bus)
5. Related graph topology — decisions affecting assigned components (KùzuDB)

Without MCP: 10+ manual operations across 5 systems. With MCP: one tool call.

## MCP Tools

Agents don't interact with stores directly. They call MCP tools and the server routes to the right store. The storage architecture is invisible to agents — they work through a clean tool interface.

The MCP server also provides the cross-host message bus (DiskCache-backed, survives restarts), enabling multi-location coordination without shared infrastructure.

### Tool inventory (20 tools)

| Tool | Purpose |
|------|---------|
| `herd_assume` | Load agent identity with full tristore context |
| `herd_checkin` | Heartbeat + read pending messages + context pane |
| `herd_catchup` | Summary of activity since last session |
| `herd_spawn` | Register new agent instances |
| `herd_assign` | Assign tickets to agents |
| `herd_transition` | Move tickets between states |
| `herd_review` | Submit QA review findings |
| `herd_create_ticket` | Create new tickets in Linear |
| `herd_list_tickets` | Query tickets with filters |
| `herd_log` | Post to Slack + log activity |
| `herd_status` | Query agent status, sprint, blockers |
| `herd_metrics` | Query operational metrics |
| `herd_harvest_tokens` | Record token usage and costs |
| `herd_record_decision` | Capture decision to DuckDB + LanceDB + Slack |
| `herd_remember` | Store memory (session summary, pattern, retrospective) |
| `herd_recall` | Semantic search over stored memories |
| `herd_graph` | Query or mutate the KùzuDB structural graph |
| `herd_send` | Send message to another agent (async bus) |
| `herd_decommission` | Permanently decommission agent |
| `herd_standdown` | Temporarily stand down agent |

## Feedback Loops

The Herd doesn't just execute — it learns how it executes best.

Agents file retrospectives when they encounter friction, skill gaps, or discover patterns worth preserving. Leaders synthesize these into session reports stored as semantic memory. Over time, retrospective data tunes the system: which skills to load per task type, which context to recall per ticket category, which spawn patterns produce the least rework.

Every token spent, every QA rejection, every blocked ticket is recorded as dimensional data in DuckDB. The analytical layer (dbt models, Evidence.dev dashboards) surfaces trends — cost per agent, rework rate, velocity by sprint. The team measures itself with the same rigor it applies to the code it produces.

## Getting Started

### Installation

**Development (editable):**

```bash
pip install -e "/path/to/herd-core[adapters,env]"
```

**Stable (pinned to release):**

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
| `env` | `python-dotenv>=1.0` — loads `.env` files automatically |
| `dev` | `pytest`, `ruff`, `black`, `mypy` — development tooling |
| `adapters` | All five adapter packages (store, agent, ticket, repo, notify) |

### Environment

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `HERD_SLACK_TOKEN` | Slack bot token (`xoxb-...`) |
| `LINEAR_API_KEY` | Linear API key (`lin_api_...`) |
| `HERD_AGENT_NAME` | Agent identity code (e.g., `mason`, `steve`) |
| `HERD_DB_PATH` | Database path (default: `.herd/herddb.duckdb`) |

The `.env` file is gitignored and never committed.

### MCP Server Configuration

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

Run modes:

| Command | Mode |
|---------|------|
| `python -m herd_mcp` | Streamable HTTP server (default) |
| `python -m herd_mcp --stdio` | Stdio mode (debugging) |
| `python -m herd_mcp slack` | Daemon with Slack Socket Mode |

### Quick Start

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

## Architecture

### Execution-agnostic by design

The Herd doesn't run agents. It governs them. Bring Claude Code, Codex, CrewAI, or anything else — plug in through typed adapter protocols (PEP 544 structural subtyping). The governance layer is independent of the execution engine.

Five adapter protocols define the capability boundaries:

| Package | Purpose | Adapter |
|---------|---------|---------|
| `herd-core` | Framework interfaces, types, config, queries, MCP server | — |
| `herd-store-duckdb` | DuckDB/MotherDuck persistence + dbt schema + Evidence dashboards | `StoreAdapter` |
| `herd-agent-claude` | Claude Code CLI execution | `AgentAdapter` |
| `herd-ticket-linear` | Linear.app ticket lifecycle | `TicketAdapter` |
| `herd-repo-github` | GitHub PRs, branches, commits | `RepoAdapter` |
| `herd-notify-slack` | Slack messaging | `NotifyAdapter` |

Each adapter is a `@runtime_checkable` Protocol — implementations use structural subtyping, no inheritance required. Swap DuckDB for Postgres, Linear for Jira, Slack for Discord. The governance framework doesn't change.

### Adapter protocol example

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

All five protocols follow this pattern. See [`herd_core/adapters/`](herd_core/adapters/) for the full definitions.

### Content path resolution

`get_herd_content_path()` resolves `.herd/` content with a two-step fallback:

1. **Project root** `.herd/` — project-specific overrides
2. **Package root** `.herd/` — canonical defaults from herd-core install

Consuming projects can override any role file, craft standard, or template by placing their own version in their `.herd/` directory.

### Type inventory

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

## Status & Roadmap

**Current:** v0.2.0 (alpha). Nine agents. Twenty MCP tools. Tristore architecture operational. DuckDB analytics with 87 dbt models. Evidence.dev dashboards. DiskCache-backed persistent message bus. CI and QA gates enforced.

**What's coming:** GitBook documentation site. MotherDuck cloud sync for cross-host analytics. Expanded retrospective-driven tuning. Additional adapter implementations.

## Version History

| Version | Date | Summary |
|---------|------|---------|
| 0.2.0 | 2026-02-15 | MCP server, .env support, content path resolution, roster rename (HDR-0024) |
| 0.1.0 | 2026-02-13 | Fixture rename, Vigil CI, helper/assume_role ports, role/HDR sync |
| 0.0.1 | 2026-02-11 | Initial release — type system, adapter protocols, config, queries |

## License

MIT
