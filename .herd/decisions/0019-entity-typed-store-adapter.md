---
status: accepted
date: 2026-02-14
decision-maker: Faust
principle: backend-agnostic domain model, like an ORM
scope: architecture
superseded-by: null
---

# StoreAdapter uses entity-typed generics, not SQL

## Context

The initial StoreAdapter exposed `execute(sql)` and `insert(table, data)` — methods that assume SQL and leak storage implementation. The Architect pointed out that the store could be anything: DuckDB, SQLite, Oracle, Snowflake, a REST API. The adapter pattern must allow any implementation with a consistent interface for requesting details of anything in the schema.

## Decision

StoreAdapter uses entity-typed generics. Callers pass typed Entity/Event classes, not SQL or table names. The adapter dispatches by type and maps to its backend.

```python
store.get(AgentRecord, "abc-123")          -> AgentRecord | None
store.list(TicketRecord, status="blocked") -> list[TicketRecord]
store.save(agent_record)                   -> "abc-123"
store.append(lifecycle_event)              -> None
store.events(TicketEvent, entity_id="DBC-120") -> list[TicketEvent]
```

Two base classes define the type hierarchy:

- **Entity** (mutable): records with identity, soft deletes, save/get/list/delete. `AgentRecord`, `TicketRecord`, `PRRecord`, `DecisionRecord`, `ReviewRecord`.
- **Event** (frozen): immutable append-only audit trail. `LifecycleEvent`, `TicketEvent`, `PREvent`, `ReviewEvent`, `TokenEvent`.

Six methods on StoreAdapter: `get`, `list`, `save`, `delete`, `append`, `events`. The protocol surface is fixed — new entity types don't add new methods.

## Alternatives Considered

* Generic CRUD with string entity names and dict data — rejected because it loses all type safety. Callers would pass strings and dicts with no IDE help.
* Typed methods per domain entity (get_agent, get_ticket, etc.) — rejected because the Protocol bloats with every new entity. Every new record type means new methods on every adapter.
* Raw SQL interface — rejected because it couples callers to SQL and breaks with non-SQL backends.

## Consequences

* Good: Backend-agnostic. DuckDB, SQLite, Postgres, Snowflake, REST — all implement the same 6 methods.
* Good: Type-safe. `store.get(AgentRecord, id)` returns `AgentRecord | None`, not `dict`.
* Good: Protocol surface is stable. Adding `SprintRecord(Entity)` requires zero changes to StoreAdapter.
* Good: Entity is mutable (working state), Event is frozen (audit trail). Matches the append-only ledger pattern.
* Acceptable tradeoff: Adapters must implement type dispatch internally. More work in the adapter, less in the caller.
* Acceptable tradeoff: `**filters` on list/events is stringly-typed. Could be improved with filter objects later, but kwargs are simple and sufficient for now.
