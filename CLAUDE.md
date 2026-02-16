# CLAUDE.md — herd-core

## What This Is

herd-core is the governance framework for The Herd, a multi-agent AI development team. It provides execution-agnostic roles, authority models, decision capture, craft standards, and an MCP server for operational tracking.

## Project Structure

```
herd_core/          # Core framework: types, adapter protocols, config, queries
herd_mcp/           # MCP server: 13 tools, DuckDB backend, REST API, Slack daemon
.herd/              # Agent infrastructure (roles, decisions, craft, docs, sessions)
tests/              # pytest test suite
scripts/            # Utility scripts
```

## Adapter Protocol Mapping

herd-core defines five adapter protocols. Each has a dedicated implementation repo:

| Protocol | Adapter Repo | Description |
|----------|-------------|-------------|
| `AgentAdapter` | herd-agent-claude | Execution via Claude Code CLI |
| `StoreAdapter` | herd-store-duckdb | DuckDB + MotherDuck storage |
| `TicketAdapter` | herd-ticket-linear | Linear ticket lifecycle |
| `RepoAdapter` | herd-repo-github | GitHub repository operations |
| `NotifyAdapter` | herd-notify-slack | Slack notifications |

Protocols use structural subtyping (PEP 544). Adapters implement the interface without inheriting.

## Development

### Python

- **Floor**: Python 3.11 (HDR-0022)
- **Build**: Hatchling
- **Version**: 0.2.0

### Dependencies

Core: `mcp>=1.0`, `duckdb>=1.0`, `aiohttp>=3.9`, `slack_sdk>=3.27`
Dev: `pytest`, `pytest-asyncio`, `ruff`, `black`, `mypy`

### Pre-Commit Checklist

Before every PR:

```bash
pytest
ruff check .
black --check .
mypy herd_core herd_mcp
```

All four must pass. Wardenstein rejects PRs that fail any of these.

### Code Conventions

- Type hints on all public functions. No `Any` in public APIs.
- Docstrings on all public functions.
- Imports: stdlib, blank line, third-party, blank line, local. Alphabetical within groups.
- Error messages must be diagnostic: what went wrong, what was expected, where to look.
- One logical change per commit. Commit body explains why, not what.
- No wildcard imports. No bare `except:`. No `except Exception: pass`.

### Branching

- `main` is protected. No agent pushes to main (HDR-0006).
- Feature branches: `herd/<agent>/<ticket-id>-<short-description>`
- Merges via PR only, after Wardenstein QA passes.

## Key Design Decisions

- Data Vault 2.0 modeling for the MCP database (HDR-0007)
- Evidence.dev for dashboards (HDR-0008)
- Protocol-based adapter interfaces (HDR-0017)
- MCP server is core, not an adapter (HDR-0018)
- Entity-typed store adapter pattern (HDR-0019)
- Herd repos under herd-ag GitHub org (HDR-0027)

## Environment

Copy `.env.example` to `.env` and fill in values. `.env` is gitignored.

Required: `HERD_SLACK_TOKEN`, `LINEAR_API_KEY`
Agent config: `HERD_AGENT_NAME`, `HERD_DB_PATH`

## Current State

v0.2.0 released. No active work. Clean slate.
