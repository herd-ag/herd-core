---
status: accepted
date: 2026-02-15
decision-maker: Faust
principle: the runtime IS the framework
scope: architecture
superseded-by: null
---

# MCP server is a default dependency of herd-core, not optional

## Context

HDR-0018 established that the MCP server runtime belongs in herd-core. During the actual migration (DBC-155), the question arose whether to make it an optional extra (`pip install herd-core[mcp]`) or a default dependency (`pip install herd-core`). The Architect decided: default.

## Decision

`herd_mcp` is a default part of `herd-core`. Installing herd-core installs the MCP server and its dependencies (`mcp`, `duckdb`, `aiohttp`, `slack_sdk`). The MCP server is the orchestration runtime — it's not optional because herd-core uses it for orchestration. Adapter packages (Slack, Linear, GitHub, Claude, DuckDB) remain optional under `[adapters]`.

## Consequences

* Good: `pip install herd-core` gives you a working framework out of the box
* Good: No confusion about which extras to install for basic functionality
* Acceptable Tradeoff: herd-core has heavier dependencies than a pure protocol package — but it's a runtime framework, not a library of ABCs
* Good: Clear boundary — framework runtime (default) vs external integrations (optional adapters)
