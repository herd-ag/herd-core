---
status: accepted
date: 2026-02-16
decision-maker: Faust
principle: experiential learning, longitudinal awareness
scope: memory architecture
superseded-by: null
---

# HDR-0043: System Observations as Memory Type — "State of the Herd"

## Context

The Herd memory system captures what happened (session_summary), what was decided (decision_context), what we learned (lesson, HDR-0042), and reusable approaches (pattern). Missing: periodic holistic assessments of how the entire system is operating. Six months from now, we need to look back and see the arc — what went well, what surprised us, what introduced friction, what improved.

## Decision

Add `memory_type: observation` to the semantic memory taxonomy. Observations are versioned "State of the Herd" snapshots — evaluative assessments of the Herd's operational health at a point in time.

Observations are written by **team leaders** (Steve, Leonardo) who have the system-wide view. They cover:

- What's working well and why
- What's not working or introducing friction
- What's changed since the last observation
- What surprised us (positively or negatively)
- Current AX/DX friction points
- Capability inventory (tools, stores, agents, integrations)
- Open questions or emerging tensions

### Natural Triggers

- After significant capability lands (new store, public endpoint, new adapter)
- At sprint boundaries
- When the Architect asks "how are we doing?"
- When enough time or data has accumulated to see patterns (monthly minimum)

**Not triggered by:** routine sessions, minor bug fixes, individual ticket completions. Observations are infrequent and high-signal.

### Querying

`herd_recall("how has the Herd evolved")` or `herd_recall("AX friction over time")` surfaces the timeline of observations, enabling longitudinal analysis of system maturity.

## Memory Taxonomy (Complete)

| Type | What | Who | When | Level |
|---|---|---|---|---|
| `session_summary` | What happened | Any agent | Session end | Tactical |
| `decision_context` | What was decided | Steve (for Architect) | Real-time | Architectural |
| `pattern` | How to do X | Any agent | When confirmed | Reference |
| `preference` | How we like things | Architect | When stated | Reference |
| `lesson` | What we learned | Agents + Leaders | After surprise | Tactical |
| `observation` | State of the Herd | Leaders | Periodic | Strategic |

## Alternatives Considered

- Dashboard metrics only — rejected. Metrics show what happened, not how it felt or what it means. Observations add the evaluative layer that numbers can't capture.
- Session summaries as proxy — rejected. Too granular, too frequent. Observations are deliberate assessments, not automatic logs.
- Architect-only observations — rejected. Leaders write them because they're in the system daily. Architect reviews and adds perspective, but the first-person operational view comes from Steve and Leonardo.

## Consequences

- Six-month retrospectives become trivial — query observations, see the full arc
- System maturity is trackable across time, not just felt
- Friction points that persist across multiple observations become visible patterns (candidate for tickets)
- Improvements that land successfully are documented, not forgotten
- Combined with lessons (HDR-0042), creates a complete learning loop: lessons are tactical (per-session), observations are strategic (per-period)
