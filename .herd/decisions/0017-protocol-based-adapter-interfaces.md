---
status: accepted
date: 2026-02-14
decision-maker: Faust
principle: modularity, structural subtyping over inheritance
scope: architecture
superseded-by: null
---

# Adapter interfaces use Protocol (structural subtyping), not ABC inheritance

## Context

The Herd is being extracted from dbt-conceptual into a standalone framework (HDR-0012). The framework needs adapter interfaces that external packages implement: agent execution (Claude), storage (DuckDB), tickets (Linear), repository (GitHub), notifications (Slack). The question was how to define these interfaces — ABC with required inheritance, or Protocol with structural subtyping.

## Decision

All adapter interfaces use `typing.Protocol` with `@runtime_checkable`. Adapter packages implement the interface without importing or inheriting from it — they just match the shape.

Five adapter protocols defined in `herd_core.adapters`:

| Protocol | Implemented by | Responsibility |
|----------|---------------|----------------|
| `AgentAdapter` | herd-agent-claude | Spawn, monitor, stop agent instances |
| `StoreAdapter` | herd-store-duckdb | Persist and query operational data |
| `TicketAdapter` | herd-ticket-linear | Ticket lifecycle and transitions |
| `RepoAdapter` | herd-repo-github | Branches, worktrees, PRs, reviews |
| `NotifyAdapter` | herd-notify-slack | Channel posts and thread conversations |

Shared data types are frozen dataclasses in `herd_core.types` — immutable by default, matching the append-only ledger pattern already established in the operational schema.

## Alternatives Considered

* ABC (Abstract Base Class) inheritance — rejected because it forces adapter packages to import and subclass from herd-core. Protocol allows structural subtyping: if it quacks like an AgentAdapter, it is one. This also makes testing trivial — any object with the right methods works.

* Bare function signatures without a Protocol wrapper — rejected because runtime_checkable Protocols allow `isinstance()` validation at adapter registration time, catching misconfigured adapters early.

## Consequences

* Good: Adapter packages can be developed and tested independently — no import dependency on herd-core at runtime (only for type checking).
* Good: Third parties can write adapters (e.g., herd-ticket-jira, herd-agent-codex) without coupling to our class hierarchy.
* Good: `@runtime_checkable` catches interface mismatches at registration, not at first call.
* Acceptable tradeoff: Protocols can't enforce constructor signatures — adapter initialization is convention, not contract.
* Good: Frozen dataclasses for return types prevent accidental mutation and match the immutable-ledger philosophy.
