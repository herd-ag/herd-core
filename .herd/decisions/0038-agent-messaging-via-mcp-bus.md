# HDR-0038: Agent Messaging via MCP Message Bus

**Status:** Accepted
**Date:** 2026-02-16
**Decider:** Faust Eriksen

## Context

Spawned agents communicate through Slack and leader mediation. No direct agent-to-agent messaging exists. Cross-team and cross-host coordination requires manual intervention through Steve or Leonardo. The MCP server is already the central hub all agents connect to via streamable-HTTP (HDR rest-server-removal). The `agentName.Instance@Team` addressing scheme emerged naturally from existing data model fields (`AgentRecord.agent`, `AgentRecord.id`, `Entity.team` from HDR-0034).

## Decision

Implement an in-memory message bus inside the MCP server process.

### Addressing: `agentName.Instance@Team`

| Address | Example | Delivers to |
|---|---|---|
| `agent` | `mason` | Any active Mason instance, any team |
| `agent@team` | `mason@avalon` | Any active Mason on Avalon |
| `agent.instance@team` | `mason.inst-a3f7b2c1@avalon` | Exact instance |
| `@anyone` | `@anyone` | First non-mechanical agent to read |
| `@anyone@team` | `@anyone@avalon` | First non-mechanical agent on Avalon |
| `@everyone` | `@everyone` | All active agents, all teams |
| `@everyone@team` | `@everyone@avalon` | All active agents on Avalon |

Any segment can be omitted for broader addressing. More specific = narrower delivery.

`@anyone` excludes mechanical agents (Rook, Vigil). Want a mechanical executor? Name it explicitly.

### Delivery Modes

**Passive (piggyback):** Every MCP tool response includes a `_pending_messages` field if the calling agent has unread messages. Agent calls `herd_transition`, gets their response back plus Mason's question. Zero extra calls. Latency = time until agent's next MCP tool call (typically seconds).

**Active (stdin injection):** For `priority: urgent` messages to local agents. The spawn tool retains the subprocess stdin handle. MCP server writes the message to stdin — agent sees it as immediate input. Latency = milliseconds.

### Single Hub

One MCP server. No federation. All agents connect regardless of host. Cross-host is just HTTP — Metropolis agents point to Avalon's MCP URL or vice versa. If the hub goes dark, comms go dark. Acceptable failure mode — equivalent to "battery died."

### Leader Visibility

Team leaders (Steve, Leonardo, or any future leader) see all messages addressed to their team scope. `@avalon` traffic is visible to Steve. `@leonardo` traffic is visible to Leonardo. Structural, not bolted on.

### Ephemeral Messages

Messages live in-memory only. MCP restart = messages lost. No persistence needed. If you didn't get the message, ask again. Same as real life.

## Alternatives Considered

- **RabbitMQ / NATS** — Proper pub/sub with topic routing. AMQP routing keys map perfectly to the addressing scheme. But adds an external service to install and maintain on resource-constrained hosts (Metropolis: 16GB). Rejected for operational overhead.
- **Per-instance direct ports** — Each agent opens a listener, registers in DuckDB. Rejected because Claude Code CLI processes are request-response — they can't maintain a background listener.
- **Redis pub/sub** — Lightweight but still another service. Fire-and-forget semantics match our requirements, but not worth the dependency.
- **DuckDB message table** — Persistence not needed, adds write overhead on every send/receive, and DuckDB single-writer means all messages route through MCP anyway.

## Consequences

- One new MCP tool: `herd_send`
- Piggyback middleware on all tool responses
- Spawn must populate `team` field on AgentRecord (currently empty)
- Spawn must retain subprocess stdin handle (currently fire-and-forget)
- Spawn payload must include instance ID so agents can self-identify
- Team topology is `1+` — addressing scheme supports any number of teams
- ~200 lines of implementation

## Principles

- Naming is architecture. `agentName.Instance@Team` isn't a convention — it's the routing logic.
- Infrastructure should emerge from what exists, not be imported.
- Governance is structural. Authority boundaries are in the addressing scheme, not in policy documents.
