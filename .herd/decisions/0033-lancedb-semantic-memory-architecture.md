---
status: accepted
date: 2026-02-15
decision-maker: Faust
principle: AX is a first-class concern (HDR-0029)
scope: architecture
superseded-by: null
---

# HDR-0033: LanceDB Semantic Memory Architecture

## Context

Agents start each session from scratch — reading flat markdown files (STATUS.md, session logs, HDRs) with no semantic understanding of previous conversations. This creates friction: keyword-searchable files miss conceptual connections, session files grow stale, and cross-session context is lost.

The semantic store (LanceDB, HDR-0025) was designed for this. Time to define its schema and role.

## Decision

LanceDB stores agent-queryable memory as a single `memories` table with metadata filters. Markdown files remain the human-readable system of record.

### Schema

```
memories table
├── id              # uuid
├── project         # "herd", "dbt-conceptual", ...
├── repo            # "herd-core", null for cross-repo
├── session_id      # "steve-2026-02-15"
├── agent           # "steve", "mason", "wardenstein"
├── memory_type     # session_summary | decision_context | pattern | preference | thread
├── content         # the actual text
├── vector          # embedding for semantic search
├── created_at      # timestamp
└── metadata        # flexible json (hdr_number, ticket_id, principle, etc.)
```

### Memory Types

- **session_summary**: What happened in a session. Replaces flat session files for agent consumption.
- **decision_context**: The discussion around an HDR — why option B beat option A, what was rejected and why. The HDR is the verdict; this is the trial transcript.
- **pattern**: Recurring observations. "Mason needs explicit file lists in spawn context." Accumulated over multiple sessions.
- **preference**: Architect style and choices. "Faust prefers presenting tension and letting him resolve." Learnable over time.
- **thread**: Multi-session topics that aren't formal HDRs. Ongoing discussions, evolving ideas.

### Dual-Format Principle

HDRs stay as markdown in `.herd/decisions/` — in git, reviewable, diffable, human-readable. The same content plus surrounding context gets pushed to LanceDB for agent recall. If they ever disagree, markdown wins.

Some content lives only in LanceDB: session summaries, observed patterns, preferences. These serve agents, not humans.

### Query Interface

The MCP server exposes a `herd_recall` tool (or similar) that agents call to search memory semantically. Queries support metadata filters:

- `"config architecture"` filtered by `project="herd"` — surfaces env var discussion context
- `"mason spawn failures"` filtered by `agent="steve"` — surfaces coordination patterns
- `"storage decisions"` with no filter — surfaces HDR-0025, 0031 context across sessions

## Rationale

AX is a first-class concern (HDR-0029). If agents start every session re-reading the same files and losing cross-session context, the experience is broken. Semantic search finds related conversations even without shared vocabulary — "config architecture" surfaces HDR-0030 even if those words never appeared in the original discussion.

The flat hierarchy (single table, metadata filters) matches LanceDB's strengths: vector similarity search with predicate filtering. Nested structures add complexity without benefit.

## Consequences

- Agents get richer context at session start — semantic search replaces keyword grep
- Session files and MEMORY.md become bootstrapping mechanisms, not the primary recall layer
- An embedding pipeline is required — needs architectural decision on local vs API embeddings
- The MCP server gains a new tool (`herd_recall`) for memory queries
- LanceDB becomes the institutional memory of the Herd — knowledge compounds across sessions
