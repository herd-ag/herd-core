---
status: accepted
date: 2026-02-15
decision-maker: Faust
principle: operational simplicity
---

# HDR-0030: Environment Config Rolls Up to Core

## Context

herd-core defines five adapter protocols, each implemented by a separate repo (herd-notify-slack, herd-ticket-linear, etc.). The question: where do adapter-specific environment variables (API keys, tokens) live?

## Decision

All environment config lives in herd-core's `.env`. Users install herd-core with the adapters they want; secrets and config live in one place, not scattered across adapter repos.

Adapter repos document what env vars they need. Core is the aggregation point.

`HERD_AGENT_NAME` is per-spawn, not project-level. It is injected by Steve at agent spawn time and does not belong in `.env`.

## Alternatives Considered

**Vars in adapter repos**: Each adapter repo owns its own `.env`. Rejected — creates operational friction (five files to manage) for no real benefit. The MCP server in core already consumes all these services directly.

## Consequences

- One `.env` to manage per deployment
- `.env.example` in core documents all adapter vars with source annotations
- Adapter repos include a note pointing to core for runtime config
