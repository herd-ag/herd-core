---
status: accepted
date: 2026-02-14
decision-maker: Faust
principle: adapters do work, core orchestrates
scope: architecture
superseded-by: null
---

# MCP server runtime belongs in herd-core, not a separate package

## Context

During framework extraction, the question arose whether the MCP server (tool registration, adapter composition, config loading) should be its own package (`herd-mcp`) or part of `herd-core`. The name `herd-mcp` was available on PyPI.

## Decision

The MCP server runtime is part of `herd-core`. Adapters handle actual external work only.

The boundary is:
- **herd-core**: Protocol interfaces, shared types, MCP server runtime (tool registration, adapter composition, config loading, orchestration)
- **Adapters**: Each implements exactly one Protocol, talks to exactly one external system. No orchestration logic.

This means `pip install herd-core` gives you a working MCP server — you just plug in adapters for the specific systems you use.

## Alternatives Considered

* Separate `herd-mcp` package — rejected because the MCP server IS the core runtime. Splitting it would create a mandatory dependency that every installation needs anyway, adding packaging ceremony for zero benefit.

## Consequences

* Good: Single `pip install herd-core` gives you the full orchestration layer. Adapters are the only add-ons.
* Good: Clearer mental model — "core orchestrates, adapters integrate."
* Good: One fewer package to maintain, version, and publish.
* Acceptable tradeoff: `herd-core` becomes heavier than a pure interfaces-only package. But it's still lightweight — the MCP server is ~500 lines of Python with no heavy dependencies.
