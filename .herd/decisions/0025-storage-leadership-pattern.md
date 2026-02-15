---
status: accepted
date: 2026-02-15
decision-maker: Faust
principle: Single source of truth — no sync, no drift
scope: architecture
superseded-by: null
---

# HDR-0025: Storage Leadership Pattern

**Status:** Accepted
**Date:** 2026-02-15
**Participants:** Faust (Architect), Claude (Advisor)
**Context:** Defining storage architecture for multi-team topology ahead of Metropolis setup

## Decision

One team owns all shared storage. Other teams access via MCP. No sync, no drift, no cloud dependency.

### Architecture

```
Avalon       ----MCP---->   Metropolis
(Steve)                     (Leonardo)
                            DuckDB + LanceDB
You          ----MCP---->   MCP Server
(any device)
```

### Configuration

```yaml
storage:
  leader: metropolis
  engines:
    operational: duckdb    # telemetry, costs, HDRs, tickets
    semantic: lancedb      # conversation memory, decision context
  protocol: mcp
  backup:
    target: /mnt/nas/herd-backup  # or any mount point
    schedule: daily
    retain: 30
```

### Dual Store Architecture

**DuckDB (operational):** Structured data. Telemetry, token costs, agent sessions, ticket state, HDRs, velocity metrics. Queryable by SQL. Feeds dashboards and analytics.

**LanceDB (semantic):** Vector embeddings. Conversation summaries, decision context, strategic thinking, methodology evolution. Queryable by semantic similarity. Feeds Advisor and leader context loading.

Both embedded. Both file-based. Both on Metropolis. Both built on Apache Arrow — enabling zero-copy data exchange between stores when needed.

## Rationale

### Single Source of Truth
Two DuckDB files on two machines is a merge nightmare. Which has the latest HDR? Which token log is complete? One storage leader eliminates sync conflicts entirely.

### No Drift
Avalon goes offline for a week. When it comes back, nothing to reconcile. It queries Metropolis and gets current state.

### No Cloud Dependency
Self-hosted on Metropolis means institutional memory lives on hardware you control. MotherDuck remains available as an adapter option for globally distributed teams, but is not required for the default deployment.

### Offline Mode Not Applicable
No internet means no Claude API means no agents spawning. The offline scenario cannot occur because the execution layer depends on connectivity. This eliminates the need for local caching, write queues, or eventual consistency patterns.

### Why LanceDB for Semantic Store
- Embedded, serverless — same philosophy as DuckDB
- Built on Apache Arrow — native interop with DuckDB
- SQL query interface via DataFusion — familiar to data architects
- Automatic versioning — conversation summaries evolve over time
- Disk-based with near-memory performance — fits Metropolis resource constraints
- Multimodal support — text, images, diagrams if needed later

### Why Not Alternatives
- **ChromaDB:** Requires server process, no Arrow integration, no versioning, no SQL interface
- **Elasticsearch:** Massive overhead for this use case
- **DuckDB FTS only:** Keyword search misses conceptual connections. Semantic search finds related conversations even without shared vocabulary
- **Recoll:** Desktop-oriented, file-focused, not designed for programmatic storage

### Backup as Built-In, Not Afterthought

The Herd handles backup as nightly housekeeping. Rook-level work — copy files, timestamp, prune. No cron, no rsync, no sysadmin knowledge. The target is intentionally just a path — NAS, USB drive, network share, S3 bucket. Whatever the user already has.

Manual checkpoint available: `herd backup now` for snapshots before risky operations.

### MotherDuck as Optional Adapter

Same StoreAdapter protocol (HDR-0020). Same entity-typed generics. Caller never knows which backend. The adapter handles routing. Self-hosted for sovereignty. Cloud for distribution. Both supported. Neither required.

## Implementation Required

1. Configure DuckDB on Metropolis as storage leader
2. Set up LanceDB on Metropolis for semantic store
3. MCP endpoints for both stores (read/write)
4. Backup automation (daily schedule, retention policy)
5. `herd backup now` CLI command for manual snapshots
6. Service token auth for Avalon-to-Metropolis MCP calls
7. Conversation summary indexing pipeline (Rook extracts, LanceDB stores)

## Consequences

- All storage lives on Metropolis. Single backup target. Single source of truth.
- Avalon agents write through MCP. Small network latency on home LAN — irrelevant.
- LanceDB enables semantic search across conversation history — "find discussions about governance" matches even if the word "governance" was never used.
- Arrow interop allows cross-store analytics: correlate strategic conversations (LanceDB) with implementation costs (DuckDB).
- New teams joining the topology just point at Metropolis MCP. No local storage setup.
- If Metropolis goes down, all storage is unavailable — acceptable because agents can't run without internet anyway.
