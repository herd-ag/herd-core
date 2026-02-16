---
status: accepted
date: 2026-02-15
decision-maker: Faust
principle: Data model matches operational reality
scope: architecture
superseded-by: null
---

# HDR-0034: Project Scoping Dimensions

## Context

The MCP server now runs at host level (`~/herd/`), serving across repositories, not inside a single project. Every operational record — entities, events, semantic memories — needs enough context to answer "where did this happen?" unambiguously.

The current data model captures `project` and `repo` inconsistently. Semantic memory (LanceDB) has `project` and `repo`. The operational store (DuckDB) entities largely lack both. Neither captures host or org. As the herd operates across repos, orgs, and eventually across hosts (Avalon, Metropolis), every record must be fully scoped.

## Decision

Four scoping dimensions are captured at **all levels** — every entity, every event, every memory:

| Dimension | Description | Examples |
|-----------|-------------|----------|
| `org` | GitHub organisation or equivalent | `herd-ag` |
| `team` | Herd team identity per team config | `avalon`, `metropolis` |
| `repo` | Repository name | `herd-core`, `herd-store-duckdb` |
| `host` | Physical/logical host where work occurred | `avalon`, `metropolis` |

### Dimensional Model

In the reporting/analytics layer, these four roll up into a single `dim_project` dimension:

```
dim_project
├── org           # organisation
├── team          # herd team identity
├── repo          # repository
└── host          # execution host
```

All fact tables (token events, ticket events, lifecycle events, review events) carry a foreign key to `dim_project`. This enables slicing any operational metric by org, team, repo, or host — individually or in combination.

### Scope at Each Level

**Operational store (DuckDB via StoreAdapter):**
- All entity types (AgentRecord, TicketRecord, PRRecord, DecisionRecord, ReviewRecord, ModelRecord, SprintRecord) gain `org`, `team`, `repo`, `host` fields.
- All event types (LifecycleEvent, TicketEvent, PREvent, ReviewEvent, TokenEvent) gain the same four fields.

**Semantic memory (LanceDB):**
- The `memories` table already has `project` and `repo`. Add `org`, `team`, `host`. Rename `project` to align if needed (or map in the dimension).

**REST API / MCP tools:**
- Tools that create records should accept or infer these dimensions from environment/config.
- Default values come from deployment config (`HERD_ORG`, `HERD_TEAM`, `HERD_HOST`).

### Team vs Host

Team and host correlate today (Avalon team runs on Avalon host) but are conceptually distinct. Team is the logical identity — who's working. Host is the physical provenance — where the work ran. If Avalon team ever runs on cloud infra, team stays `avalon`, host changes.

## Rationale

Host-level operation is the natural evolution. The herd coordinates work across repos within an org. Without scoping dimensions, a ticket transition in `herd-core` is indistinguishable from one in `herd-store-duckdb`. A token cost on Avalon blends with one on Metropolis. The data becomes ambiguous the moment you operate beyond a single repo.

Capturing all four at all levels (not selectively) keeps the model clean. No guessing which records have which context. Every row is fully qualified. The cost is four extra fields per record — trivial compared to the analytical value.

## Consequences

- Every entity and event type in `herd_core/types.py` needs four new fields
- StoreAdapter implementations must persist and query these fields
- LanceDB memory schema needs `org`, `team`, `host` added
- Deployment config needs `HERD_ORG`, `HERD_TEAM`, `HERD_HOST` env vars
- Existing records will need backfill (default: `org=herd-ag`, `team=avalon`, `host=avalon`)
- Analytics/reporting layer gets `dim_project` as a first-class dimension
- The `dim_project` pattern generalises cleanly if we ever add more scoping (region, environment, etc.)
