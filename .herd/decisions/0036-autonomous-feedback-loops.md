---
status: accepted
date: 2026-02-15
decision-maker: Faust
principle: AX is a first-class concern (HDR-0029)
scope: architecture
superseded-by: null
---

# HDR-0036: Autonomous Feedback Loops

## Context

HDR-0033 (LanceDB) gives agents memory. HDR-0035 (KùzuDB) gives agents structural awareness. DuckDB gives agents operational facts. The infrastructure is in place — three embedded stores capturing different dimensions of every operational event.

What's missing is agency. The stores accumulate data, but nothing closes the loop. Wardenstein rejects a PR and Mason fixes it, but nobody records why in a way that prevents the same mistake next time. Steve writes spawn briefs, but there's no signal on which brief patterns produce first-attempt success. Sessions end without capturing what would have made them more productive.

The system has memory but doesn't learn.

## Decision

Five autonomous feedback loops that close themselves without architect intervention. Each loop follows the same pattern: operational event → store signal → future context enrichment.

### Loop 1: Rejection → Pattern → Prevention

When Wardenstein rejects a PR, the review findings already auto-shadow to LanceDB as `pattern` memories (HDR-0033). The missing piece: spawn context doesn't query those patterns.

**Change**: When `spawn` assembles agent context, include a `herd_recall` for rejection patterns relevant to the work area. The graph (HDR-0035) enables precision: traverse from the ticket being worked on to related files, then recall patterns for those files specifically.

**Result**: "This file has had 3 rejections for missing type hints" becomes automatic spawn context. Mason stops making the same mistakes. The quality gate teaches, not just blocks.

### Loop 2: Spawn Context Quality Tracking

Track the correlation between spawn brief content and outcome. Two data points already exist in DuckDB: spawn events (what Steve sent) and review events (first-attempt success vs iterations). The graph connects them: `SPAWNED_BY` + `ASSIGNED_TO` + `REVIEWS` gives the full pipeline per ticket.

**Change**: When `transition(to_status="done")` fires, compute a spawn-to-completion metric: number of review iterations, time to completion, first-review verdict. Store as a `pattern` memory tagged to the spawn brief's work area.

**Result**: Steve can query `herd_recall("successful spawn patterns for adapter refactoring")` and get templates that worked. Brief quality compounds across sessions.

### Loop 3: Agent Self-Reflection

Add a required reflection field to ticket completion. Not AX friction from the architect's perspective — from the agent's own assessment.

**Change**: `transition(to_status="done")` requires a `reflection` note parameter. The note auto-shadows to LanceDB as a `pattern` memory tagged to the work area. Future spawns for similar work recall those patterns.

**Result**: Mason says "I didn't have the test fixtures and had to discover them." Next spawn for similar work includes test fixture locations automatically. The agent writes instructions for its own future incarnation.

### Loop 4: Wardenstein as Learning Engine

Every Wardenstein review generates structured findings with categories and severities. These already shadow to LanceDB as patterns. The accumulated patterns represent an empirical craft standard — what "good" looks like in this codebase, learned from observation.

**Change**: `assume_role` for any agent includes a `herd_recall("quality patterns for {work_area}")` in context. Not a static `craft-learned.md` file (files get stale), but a live recall that always surfaces the freshest patterns.

**Result**: The quality bar rises without anyone updating documentation. Wardenstein's judgment propagates through the system via the memory store. New agents inherit accumulated craft knowledge on first spawn.

### Loop 5: Cross-Session Goal Tracking

Some objectives span multiple sessions: "improve test coverage to 90%", "eliminate all raw SQL from tools." Sessions are discrete but goals are continuous.

**Change**: Add a `Goal` node type to the graph (HDR-0035). Tickets connect to Goals via `CONTRIBUTES_TO` edges. Progress metrics from DuckDB (measurable outcomes) become timestamped properties on edges.

**Result**: Leonardo's morning summary becomes: "Test coverage: 74% → 81% over last three sessions. Four files remaining." The graph tracks progress toward goals across sessions, agents, and repos.

## Implementation Order

1. **Spawn context enrichment** (Loop 1) — Lowest effort, highest impact. Add `herd_recall` for rejection patterns to spawn context assembly. Requires only a change to `spawn.py`.

2. **Required reflection on completion** (Loop 3) — Simple schema change to `transition`. Add `reflection` parameter, shadow to LanceDB. Spawn context includes relevant reflections.

3. **Spawn quality tracking** (Loop 2) — Compute spawn-to-completion metrics in `transition(done)`. Store as pattern memory. Requires graph traversal to link spawn → ticket → review chain.

4. **Live craft recall in assume** (Loop 4) — Add `herd_recall` for quality patterns to `assume_role` context assembly. Straightforward once patterns are accumulating from loops 1-3.

5. **Goal tracking** (Loop 5) — Add Goal node type to graph schema. Add `CONTRIBUTES_TO` edge type. Enrich Leonardo summary with goal progress queries.

## Rationale

Infrastructure without feedback loops is a data warehouse. The three stores capture every operational signal, but without loops that close, agents never improve. Each loop follows the same pattern: the system already generates the signal (reviews, spawns, transitions), it already stores the signal (auto-shadow to LanceDB/KùzuDB), it just doesn't feed the signal back into future actions.

The key insight: every loop uses existing auto-shadow writes. No new write paths are needed. The only changes are read-path enrichments — adding `herd_recall` calls to spawn, assume, and transition. The infrastructure built in HDR-0033 and HDR-0035 pays off here.

## Consequences

- `spawn` tool gains rejection pattern recall in context assembly
- `transition(done)` gains required `reflection` parameter and spawn quality metrics
- `assume_role` gains live craft pattern recall
- Graph schema gains `Goal` node type and `CONTRIBUTES_TO` edge type
- Agent context becomes richer and more targeted with each session
- Quality improvements compound without architect intervention
- The system develops institutional memory that survives agent session boundaries
