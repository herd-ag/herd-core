---
status: accepted
date: 2026-02-15
decision-maker: Faust
principle: AX is a first-class concern (HDR-0029)
scope: architecture
superseded-by: null
---

# HDR-0035: Structural Graph Store (KùzuDB)

## Context

The herd now has two stores: DuckDB for operational facts (what happened, when, how much) and LanceDB for semantic memory (what's similar, what does it mean). Neither can answer structural questions: what's connected to what, what depends on what, what breaks if something changes.

These are graph traversal problems. "Show me the decision lineage for HDR-0033" requires multi-hop path following through supersedes/depends_on chains. "Who has context on the MCP server?" requires traversing agent-to-file-to-decision edges, not keyword matching. "What breaks if I change types.py?" requires impact analysis across dependency edges. No amount of SQL joins or vector similarity replaces graph traversal for these queries.

Additionally, agents currently load context by globbing markdown files (`.herd/decisions/*.md`, `.herd/handoffs/*.md`, `.herd/STATUS.md`). This is expensive (all files dumped into context), imprecise (no structural relevance filtering), and stale (STATUS.md requires manual maintenance). The three-store architecture enables targeted context loading: structurally relevant (graph), semantically relevant (LanceDB), operationally current (DuckDB).

## Decision

KùzuDB is the structural graph store. It lives in herd-core alongside LanceDB — structural knowledge is a core governance concern, not a pluggable adapter.

### Three-Store Architecture

```
DuckDB (operational)   → facts, events, state machines     → adapter concern
LanceDB (semantic)     → meaning, similarity, recall        → core concern
KùzuDB (structural)    → connections, dependencies, lineage → core concern
```

All embedded. All file-based. All Arrow-native. Same MCP layer in front. Same auto-shadow pattern feeding all three.

### Why KùzuDB

- Embedded, file-based — same deployment model as DuckDB and LanceDB
- Cypher query language — agents already think in structured queries
- Arrow-native — data flows between all three stores without serialization
- No server process — opens from disk, same as the other two stores

### Graph Schema

**Node types:**

| Node | Properties | Source |
|------|-----------|--------|
| `Decision` | id, title, date, status, scope, principle | HDR markdown + record_decision events |
| `Agent` | id, code, role, status, team, host | spawn + lifecycle events |
| `Ticket` | id, title, status, priority | assign + transition events |
| `File` | path, repo | Git diff parsing in review tool |
| `Repository` | name, org | Configuration |
| `Session` | id, agent, started_at | catchup + assume events |
| `Concept` | name | Extracted from HDR tags, ticket labels, decision topics |

**Edge types:**

| Edge | From → To | Properties | Created By |
|------|-----------|-----------|------------|
| `DECIDES` | Agent → Decision | timestamp | record_decision |
| `IMPLEMENTS` | Ticket → Decision | timestamp | record_decision (when ticket_code provided) |
| `TOUCHES` | Agent → File | timestamp, session_id | Git diff parsing in review |
| `REVIEWS` | Agent → Ticket | timestamp, verdict, finding_count | review |
| `SUPERSEDES` | Decision → Decision | timestamp | record_decision (manual or detected) |
| `DEPENDS_ON` | Decision → Decision | timestamp | record_decision |
| `SPAWNED_BY` | Agent → Agent | timestamp | spawn |
| `ASSIGNED_TO` | Ticket → Agent | timestamp | assign |
| `BLOCKED_BY` | Ticket → Ticket | timestamp | transition (to blocked) |
| `COMPLETED_BY` | Ticket → Agent | timestamp | transition (to done) |
| `BELONGS_TO` | File → Repository | — | Git diff parsing |
| `TAGGED_WITH` | any → Concept | — | Extracted from content |

All edges carry `created_at` for temporal graph queries.

### Auto-Shadow Writes

Same pattern as LanceDB (HDR-0033). Operational tool fires → side effect writes to graph. Failures never break primary operations.

| Tool | Graph Shadow |
|------|-------------|
| `record_decision` | Create Decision node. `DECIDES` edge from agent. `IMPLEMENTS` edge from ticket if ticket_code. `SUPERSEDES`/`DEPENDS_ON` edges if referenced. |
| `review` | Create `REVIEWS` edge from agent to ticket. Parse git diff for File nodes and `TOUCHES` edges. `BELONGS_TO` edges for files to repos. |
| `transition` | Update Ticket node status. `COMPLETED_BY` edge on done. `BLOCKED_BY` edge on blocked. |
| `assign` | Create/update Ticket node. `ASSIGNED_TO` edge from ticket to agent. |
| `spawn` | Create Agent node. `SPAWNED_BY` edge to parent agent. |

### File Touch Logging

File nodes are populated via git diff parsing in the review tool — no separate agent call needed. When a review is submitted for a PR, the tool parses the diff to extract changed files, creates File nodes, and adds `TOUCHES` edges from the authoring agent. This keeps file graph population automatic and agent-burden-free.

### Read Enrichments

| Tool | Graph Enrichment |
|------|-----------------|
| `catchup` | Structural neighbors of recently changed items. "While you were away, these connected decisions/files/tickets also moved." |
| `review` | Impact surface. "These other files and decisions are structurally connected to what this PR touches." |
| `record_decision` | Decision lineage. Traverse `SUPERSEDES`/`DEPENDS_ON` chains to show full provenance. |
| `status` | Topology summary: orphan decisions (no `IMPLEMENTS`), most-connected nodes, disconnected subgraphs. |
| `assume_role` | Targeted context: traverse from agent's current assignments to structurally connected decisions, files, and sessions. Replaces HDR file glob. |

### Context Loading Rewire

`assume_role` and `catchup` currently glob `.herd/decisions/*.md`, `.herd/handoffs/*.md`, and read `.herd/STATUS.md`. With three stores:

**HDR discovery** shifts from file glob to:
- Graph: decisions structurally connected to current assignments (via `IMPLEMENTS`, `DEPENDS_ON`, `SUPERSEDES` traversal)
- LanceDB: decisions semantically relevant to current work context

**Handoff discovery** shifts from file glob to:
- LanceDB: `session_summary` memories from relevant agents/timeframes (already available)

**STATUS.md** shifts from manual file to:
- Auto-generated from three-store queries: DuckDB for current ticket/agent state, graph for structural topology, LanceDB for recent narrative context

**Git log in assume** shifts from raw subprocess to:
- Graph traversal for recent file changes structurally connected to agent's work

Static files (roles, craft standards, CLAUDE.md) remain file-based — they're configuration, not operational data.

### MCP Tool

One new tool: `herd_graph` — Cypher query interface against KùzuDB.

```
herd_graph(query: str, params: dict | None) → dict
```

Corresponding REST endpoint: `POST /api/graph`

Agents ask structural questions in Cypher, get graph answers. The tool handles connection management, parameter binding, and result formatting.

### Storage

- File location: `herd_mcp/graph.py` (parallel to `herd_mcp/memory.py`)
- Data path: `HERD_KUZU_PATH` env var, default `data/herd.kuzu` under project path
- Follows HDR-0032 naming convention

### Concept Nodes

Optional but high-value. Decisions, tickets, and sessions can be tagged with Concept nodes (`storage`, `auth`, `mcp-protocol`). This gives automatic topic clustering complementary to LanceDB vector similarity — structural relatedness ("tagged with the same concept") vs semantic relatedness ("similar in meaning").

Concepts are extracted from HDR scope/principle fields, ticket labels, and decision topics. No manual tagging required.

## Rationale

Three fundamentally different questions require three different stores. Trying to force graph traversal into SQL joins or vector similarity produces wrong answers and brittle queries. KùzuDB completes the architecture with the same embedded, file-based, Arrow-native philosophy as the other two stores.

The context loading rewire is equally important. Agents currently waste tokens loading everything and hoping the relevant bits are in there. Three-store context loading is precision targeting: graph for structure, LanceDB for meaning, DuckDB for current state. Less tokens, more signal, faster startup. This is the AX promise of HDR-0029 made concrete.

## Consequences

- Third embedded store added to herd-core (KùzuDB alongside LanceDB)
- New dependency: `kuzu` Python package
- New MCP tool: `herd_graph` with REST endpoint
- Six existing tools gain graph auto-shadow writes
- Five existing tools gain graph read enrichments
- `assume_role` and `catchup` shift from file-based to store-based context loading
- STATUS.md becomes auto-generated, not manually maintained
- File nodes populated automatically via git diff parsing — zero agent burden
- Bootstrap script needed to populate graph from existing HDRs, agents, and tickets
- `HERD_KUZU_PATH` added to deployment config
