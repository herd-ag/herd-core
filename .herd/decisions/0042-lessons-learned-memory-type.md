---
status: accepted
date: 2026-02-16
decision-maker: Faust
principle: experiential learning, AX
scope: memory architecture
superseded-by: null
---

# HDR-0042: Lessons Learned as Memory Type

## Context

The Herd memory system captures what happened (session_summary), what was decided (decision_context), and reusable approaches (pattern). Missing: the reflective layer — what agents learned from doing the work. Not the decision, not the summary, but the meta-insight: "we tried X, learned Y, next time do Z."

## Decision

Add `memory_type: lesson` to the semantic memory taxonomy. Lessons are written by:

1. **Executing agents** at session wrapup — first-person experience. "The brief was missing context X, which caused Y. Next time include Z."
2. **Team leaders** (Steve, Leonardo) from their coordination perspective — cross-agent observations. "Parallel Masons on separate repos worked clean. Same repo caused conflicts."

Lessons are stored via `herd_remember(memory_type="lesson")` and surfaced via `herd_recall`. No mandatory retrospective format — agents write a lesson when something surprised them, positively or negatively. Routine sessions with nothing to teach produce no lessons.

The trigger is surprise, not ceremony. If nothing was learned, write nothing.

## Alternatives Considered

- Mandatory session-end retrospectives — rejected. Creates filler on routine sessions.
- Separate `retrospective` memory type — rejected. "Lesson" is more precise and action-oriented.
- Leader-only lessons — rejected. Executing agents have first-person experience that leaders can't observe.

## Consequences

- Agents get smarter across sessions — `herd_recall("DuckDB adapter lessons")` surfaces hard-won experience
- Spawn briefs improve over time as leaders learn what context agents actually need
- AX friction gets captured systematically instead of silently repeating
- Two perspectives (agent + leader) provide both tactical and strategic learning
- Lightweight — no new tools, no new protocol, just a new memory_type value on existing `herd_remember`
