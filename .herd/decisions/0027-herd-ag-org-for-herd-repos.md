---
status: accepted
date: 2026-02-14
decision-maker: Faust
principle: separation of concerns
scope: branding | architecture
superseded-by: null
---

# Herd infrastructure repos move to herd-ag org

## Context

The Herd's infrastructure packages (herd-core, adapters, MCP server) currently live under the `dbt-conceptual` GitHub org alongside the main dbt-conceptual project. As the Herd grows into its own system, the Architect created a dedicated GitHub org: `herd-ag` (Herd Agent Governance). The naming is deliberate — AG, not AI. A level above.

## Decision

All Herd infrastructure repos transfer to `github.com/herd-ag/`:

- `herd-core` — protocols, types, domain model
- `herd-notify-slack` — NotifyAdapter implementation
- `herd-ticket-linear` — TicketAdapter implementation
- `herd-repo-github` — RepoAdapter implementation
- `herd-agent-claude` — AgentAdapter implementation
- `herd-store-duckdb` — StoreAdapter implementation

The `dbt-conceptual/dbt-conceptual` repo stays where it is. The Herd operates on dbt-conceptual but isn't defined by it. The MCP server (`.herd/mcp/`) stays in dbt-conceptual for now — it's the integration point between the Herd and the project it operates on.

## Consequences

- Good: Clean separation between the governed project and the governance infrastructure
- Good: herd-ag org can have its own CI, permissions, and contributor model
- Good: Adapter packages become genuinely independent — installable from `herd-ag/` without dbt-conceptual context
- Acceptable Tradeoff: All pyproject.toml git+https URLs need updating across all repos
- Acceptable Tradeoff: GitHub redirects handle old URLs temporarily, but explicit updates are cleaner
