# HDR-0039: The Herd Checkin

**Status:** Accepted
**Date:** 2026-02-16
**Decider:** Faust Eriksen
**Supersedes:** HDR-0038 piggyback delivery and stdin injection (addressing scheme and herd_send retained)

## Context

Agents work in isolation between spawn and completion. HDR-0038 proposed piggyback message delivery — messages riding on MCP tool responses. This is flawed: thinking gaps (10-45s between tool calls), attention splitting (messages buried in tool results), idle gaps, and no broader situational awareness. Tools should return tool results. Period.

## Decision

Introduce `herd_checkin` as the sole communication and awareness mechanism. One tool. One surface. Four functions:

1. **Heartbeat** — hub records checkin timestamp. Agent is alive.
2. **Messages** — drains pending messages. Typed as `directive`, `inform`, or `flag`.
3. **Context Pane** — compressed, graph-filtered projection of relevant Herd activity via KùzuDB.
4. **Status Report** — agent contributes to collective awareness. Pull and push in one round trip.

### The Call

```python
herd_checkin(status="validation layer done, starting unit tests")
```

### The Response

```json
{
  "messages": [...],
  "context": "mason.002: schema migration in progress...",
  "heartbeat_ack": true
}
```

### When to Check In

At meaningful transitions, not mechanical intervals. Phase completions, before state-changing actions, when blocked, before completion, on approach change. A typical session produces 4-8 checkins.

### Agent Tiers

| Tier | Agents | Context Budget | Message Types | Notes |
|------|--------|---------------|---------------|-------|
| Leader | Steve, Leonardo | 500 tokens | all | Full team visibility |
| Senior | Wardenstein, Scribe, Tufte | 300 tokens | all | Structurally filtered |
| Execution | Mason, Fresco | 200 tokens | all | Direct dependencies only |
| Mechanical | Rook, Vigil | 0 tokens | directive only | Report and receive orders |

### Message Types

- **directive** — from leader/Architect, requires behavioral change
- **inform** — contextual information, no required action (not sent to mechanical)
- **flag** — issue identified by QA/review, requires attention at next pause

### Heartbeat Monitoring

- < 120s: active
- 120-300s: possibly in deep work
- > 300s: `(stale)` — leader should notice
- > 600s: `(unresponsive)` — leader should investigate

Thresholds are configurable per deployment.

### Addressing

Retained from HDR-0038: `agentName.Instance@Team`, `@anyone`, `@everyone`. Location dimension deferred to future HDR when multi-location is active.

### Data Structures

**Checkin Registry** (in-memory dict): latest status per agent instance.
**Message Queue** (in-memory dict of lists): pending messages per recipient.
Both ephemeral. Server restart clears them. Correct — checkin state is transient coordination.

## What This Replaces

- HDR-0038 piggyback delivery — eliminated
- HDR-0038 stdin injection — eliminated
- Separate heartbeat mechanism — absorbed into checkin
- Separate context/awareness system — absorbed into checkin

## What This Retains from HDR-0038

- Addressing scheme (`agentName.Instance@Team`)
- `herd_send` tool (write path for messages)
- Message queue data structure
- `MECHANICAL_AGENTS` and `LEADER_AGENTS` constants

## What This Does NOT Replace

- DuckDB — durable state
- LanceDB — semantic memory
- KùzuDB — structural graph (read by context pane, not written by checkin)
- herd_send — write path for messages
- herd_log — durable event recording

## Implementation Scope (v1)

Per Architect decision during review:
- Defer location dimension in addressing (keep HDR-0038 scheme)
- Defer team.yaml configuration cascade
- Defer central team definitions
- 300s stale threshold, configurable
- Context pane reads KùzuDB when edges exist, returns null when sparse

## Consequences

- One new MCP tool: `herd_checkin`
- Piggyback middleware removed from server.py
- Stdin injection removed from bus.py
- Role files updated with checkin guidance and tier config
- Agents gain situational awareness proportional to work coupling
