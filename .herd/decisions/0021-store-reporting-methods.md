---
status: accepted
date: 2026-02-15
decision-maker: Faust
principle: the adapter serves the domain
scope: architecture
superseded-by: null
---

# StoreAdapter gets reporting methods — no raw SQL in tools

## Context

Phase 2 MCP wiring (DBC-146, DBC-148, DBC-149) wired all 5 adapters into 12 tools. Simple CRUD mapped cleanly to StoreAdapter's generic methods (get, list, save, append). But complex aggregate queries in metrics.py and status.py couldn't use the StoreAdapter — they stayed as raw DuckDB SQL with "kept as raw SQL" comments. Mini-Mao flagged this as a sign of incomplete abstraction: one implementation per protocol, and the abstraction doesn't cover the hard queries.

## Decision

The StoreAdapter protocol in herd-core gets explicit reporting methods. The store owns the data, the store serves the reports. These are specific, known domain operations — not generic query building. The MCP tools call typed methods (`store.agent_performance(period)`, `store.token_costs(group_by)`), and each StoreAdapter implementation (DuckDB, Postgres, SQLite) provides its own backend-native queries.

No raw SQL in tool code. No query builder abstraction. Just an interface with the reporting methods the domain needs, and implementations that know how to serve them.

## Alternatives Considered

* Named queries / query catalog (`store.query("agent_performance", **params)`) — rejected because stringly-typed, no IDE support, no type safety on return values
* Query builder / specification pattern (`store.aggregate(Event, group_by=..., measure=...)`) — rejected because accidental complexity, reinventing SQL badly

## Consequences

- Good: Zero raw SQL in MCP tool code — full backend portability
- Good: Typed methods with known signatures — IDE completion, static analysis
- Good: Each implementation optimizes queries for its backend (DuckDB analytics vs Postgres window functions)
- Good: Eliminates the "one implementation" problem — the reporting interface IS the second dimension of polymorphism
- Acceptable Tradeoff: More methods on StoreAdapter protocol — but these are genuine domain operations, not abstraction overhead
