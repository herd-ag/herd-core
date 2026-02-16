---
status: accepted
date: 2026-02-15
decision-maker: Faust
principle: protocol-based adapter interfaces (HDR-0017)
scope: architecture
superseded-by: null
---

# HDR-0031: Operational Store Is Adapter, Semantic Store Is Core

## Context

herd-core currently has `duckdb>=1.0` as a core dependency and `herd_mcp/db.py` connects to DuckDB directly. Meanwhile, herd-store-duckdb exists as an adapter implementing the `StoreAdapter` protocol. This creates redundancy and prevents swapping the operational backend.

## Decision

**Operational store is an adapter concern.** herd-core interacts with it exclusively through the `StoreAdapter` protocol. The default implementation is herd-store-duckdb, but someone could create herd-store-oracle, herd-store-postgres, or any other backend. Core doesn't know or care about the underlying engine.

**Semantic store (LanceDB) is core.** Conversation memory, decision context, and semantic search are core capabilities that ship with herd-core. `lancedb` is a core dependency.

**Config rolls up to core and pushes down.** `HERD_DB_PATH` lives in core's `.env` and is passed to whatever store adapter is installed at runtime. The adapter receives its config from core — it doesn't read `.env` itself.

## Required Changes

1. Remove `duckdb` from herd-core's `pyproject.toml` dependencies
2. Add `lancedb` to herd-core's `pyproject.toml` dependencies
3. Refactor `herd_mcp/db.py` to use `StoreAdapter` protocol instead of direct DuckDB connection
4. Move schema.sql and DuckDB-specific code to herd-store-duckdb
5. MCP server instantiates the store adapter at startup, passing config down

## Consequences

- Core is truly backend-agnostic for operational storage
- Swapping operational backends requires only installing a different adapter package
- LanceDB semantic store is always available — no optional dependency dance
- The MCP server's tight coupling to DuckDB is broken
- herd-store-duckdb becomes the canonical home for all DuckDB-specific code
