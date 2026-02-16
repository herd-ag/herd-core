---
status: accepted
date: 2026-02-15
decision-maker: Faust
principle: explicit over abstract
scope: architecture
superseded-by: null
---

# HDR-0032: Adapter Env Var Naming Convention

## Context

With five adapter protocols and config rolling up to core (HDR-0030), we need a naming convention for environment variables that scales as new adapters are added.

## Decision

Adapter-specific naming: `HERD_<PROTOCOL>_<ADAPTER>_<VAR>`.

Examples:
- `HERD_STORE_DUCKDB_PATH` — not `HERD_STORE_PATH`
- `HERD_NOTIFY_SLACK_TOKEN` — not `HERD_NOTIFY_TOKEN`
- `HERD_TICKET_LINEAR_API_KEY` — not `HERD_TICKET_API_KEY`
- `HERD_REPO_GITHUB_TOKEN` — not `HERD_REPO_TOKEN`

No adapter vars are mandatory in core. Which vars exist depends on which adapters are installed.

## Rationale

Different adapters for the same protocol need fundamentally different config shapes. Slack needs a bot token. Teams needs client ID + client secret + tenant ID. Abstracting to `HERD_NOTIFY_TOKEN` leaks the moment the next adapter doesn't fit the mold.

The protocol abstraction lives in the code (`StoreAdapter`, `NotifyAdapter`). Env var names are the adapter's concern — they should be explicit about what backend they configure.

## Alternatives Considered

**Protocol-level naming** (`HERD_NOTIFY_TOKEN`): Rejected — false abstraction. Config shape varies by backend. The var names would need to change anyway when the next adapter has different requirements.

## Consequences

- Var names are self-documenting — you know exactly what adapter consumes them
- When swapping adapters, you swap vars — this is expected, since you're also swapping the package
- `.env.example` in core documents all known adapter vars, organized by protocol
- New adapters add their vars to `.env.example` with the same naming pattern
