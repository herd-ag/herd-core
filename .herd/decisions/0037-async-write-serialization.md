---
status: accepted
date: 2026-02-15
decision-maker: Faust
principle: AX is a first-class concern (HDR-0029)
scope: architecture
superseded-by: null
---

# HDR-0037: Async Write Serialization

## Context

DuckDB is single-writer. The MCP server is the sole write interface — all agents on all hosts write through MCP (either stdio or REST). But within the MCP server process, concurrent tool invocations can collide on DuckDB's write lock. Agent hits `herd_assign` while another agent's `herd_transition` is mid-write. Lock contention. Agent gets an error. AX degrades.

The three-store architecture (HDR-0031, HDR-0033, HDR-0035) makes this worse: every tool invocation now writes to DuckDB, then shadows to LanceDB, then shadows to KuzuDB. More write surface, more contention windows.

## Decision

Serialize all DuckDB writes through an `asyncio.Lock` in the MCP server process. No queue. No cache. No new infrastructure.

### Implementation

A single `asyncio.Lock` instance in the adapter registry or server module. Every `store.save()` and `store.append()` call acquires the lock before writing. Within a single tool invocation, writes are sequential (they already are). Between concurrent tool invocations, the lock serializes access.

```python
# In herd_mcp/server.py or adapters.py
_duckdb_write_lock = asyncio.Lock()

# Usage in tools (wrapper pattern)
async with _duckdb_write_lock:
    store.save(record)
    store.append(event)
```

### Why Not a Queue

A queue with fire-and-forget writes would require a write-through cache for read-after-write consistency. We traced every tool's code path and found exactly one write-then-read-same-entity pattern: the Linear auto-register flow in spawn.py, transition.py, and assign.py (`store.save(ticket)` then `store.get(TicketRecord, ticket_id)`). A cache adds complexity (invalidation, TTL, memory bounds, crash recovery) for a problem that the lock solves trivially.

### Why Not Queue-for-Events-Only

`store.append()` (events) could safely be fire-and-forget since no tool reads events back immediately after writing them. But splitting save/append into different consistency models adds cognitive load for zero practical benefit at current scale. The lock handles both uniformly.

### Scope

- DuckDB writes only. LanceDB and KuzuDB are already contention-free (LanceDB uses append-only Lance format, KuzuDB uses per-connection isolation).
- The lock lives in the MCP server process. It serializes concurrent tool invocations within that process.
- External processes (CLI scripts, notebooks) should not write to DuckDB directly — they go through the MCP REST API, which funnels through the same lock.

### Forward Compatibility

If write volume grows to the point where lock contention itself becomes the bottleneck (many agents, high-frequency events), the lock can be upgraded to an `asyncio.Queue` with a background drain worker. The queue would handle `store.append()` (events) with fire-and-forget semantics while `store.save()` (entities) stays locked for read-after-write safety. But at current scale (< 10 concurrent agents), the lock is sufficient.

## Rationale

The MCP server is already the architectural serialization point. Every agent writes through it. The missing piece was internal serialization within the server process itself. An `asyncio.Lock` is the minimum viable solution: zero infrastructure, zero dependencies, zero cache invalidation, zero data loss risk. It turns DuckDB's single-writer limitation from an agent-visible error into an invisible wait.

## Consequences

- New `asyncio.Lock` instance for DuckDB write serialization
- All `store.save()` and `store.append()` calls wrapped in `async with` lock acquisition
- Concurrent tool invocations wait (microseconds) rather than fail with lock errors
- No impact on read operations — reads remain concurrent
- No impact on LanceDB or KuzuDB writes
- External scripts must use REST API for writes (not direct DuckDB access)
- Upgrade path to queue-based writes exists if scale demands it
