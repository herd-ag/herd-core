# The Herd -- System Overview

## What This Is

The Herd is a multi-agent AI development team. Eight specialized agents -- each with a defined role, craft standards, and operational constraints -- build software under the direction of a human Architect.

This is not a framework. It is not a prompt library. It is a working team that ships production code.

The Herd operates as a standalone governance framework (herd-core) that any project can consume. It provides execution-agnostic roles, authority models, decision capture, craft standards, and an MCP server for operational tracking. The framework is project-agnostic -- bring your own codebase and plug in through typed adapter protocols.

That distinction matters. The value in this arrangement is not that AI writes code faster. The value is that the Architect operates at the architectural layer -- design, governance, quality judgment -- while the agents provide consistent execution against governed standards. The Architect reviews for drift, not syntax.

## The Principle Hierarchy

Four levels govern every decision in The Herd, in strict order of precedence:

**Principles** come first. Why we build something matters more than how. A principle like "bidirectional by default" or "fail fast, fail clearly" overrides any implementation convenience.

**Capabilities** come second. What the system can do flows from the principles, not from what's technically easy.

**Implementation** is third. How we build it -- the code patterns, the testing strategy, the data model -- serves the capabilities.

**Technology** is last. The specific tools (Python, DuckDB, Evidence.dev, dbt) are choices of convenience. They are replaceable. The principles are not.

This hierarchy is explicit because AI agents are eager to jump to implementation. The hierarchy forces the question: does this serve a principle, or does it just feel productive?

## The Architect

Faust is the sole decision-maker. Not a committee. Not a consensus process. One person who designs, prioritizes, reviews, and merges.

The Architect does not write code. The Architect writes decisions. Those decisions are captured as Herd Decision Records (HDRs) -- lightweight architectural records that document what was decided, why, and what principle governed the choice.

The Architect's review posture is fundamentally different from traditional code review. The question is not "is this syntactically correct?" -- that is the test suite's job. The question is "does this align with the architecture?" Structural drift is the failure mode, not bugs.

## Steve

Steve is the Avalon leader. Orchestration, not architecture. Steve tracks state, drafts tickets, spawns agents, captures decisions, and reports status.

Steve never codes. Steve never decides. When the temptation arises to "just fix it" -- and it does, especially after three failed agent spawns -- Steve spawns a fourth with corrected context. The coordination role is the role.

This constraint exists because coordination and implementation are different cognitive modes. Mixing them degrades both.

## How Work Flows

The lifecycle is: Linear ticket, agent assignment, feature branch, implementation, PR, QA review by Wardenstein, Architect merge.

Every PR goes through QA. No exceptions. Every agent works on a feature branch. No agent pushes to main. The Architect is the sole merge authority.

This is not ceremony for ceremony's sake. These constraints exist because agents are fast, confident, and sometimes wrong. The gates catch what speed misses.

---

## Project Structure

The `.herd/` directory contains all Herd infrastructure. When consumed as a package via `pip install herd-core`, the `.herd/` directory ships with the package and provides default content. Consuming projects can override any file by placing their own version in their project's `.herd/` directory.

### Repository Layout

```
herd-core/
  herd_core/                # Core framework (types, adapters, config, queries)
  herd_mcp/                 # MCP server (13 tools, DuckDB backend)
  .herd/                    # Herd agent infrastructure (ships with package)
    STATUS.md               # Current state of all work
    craft.md                # Quality standards by role (v0.5)
    roles/                  # Agent role definitions
      steve.md
      leonardo.md
      mason.md
      fresco.md
      scribe.md
      wardenstein.md
      vigil.md
      rook.md
      gauss.md              # Inactive
    decisions/              # Herd Decision Records (HDRs 0001-0027)
    templates/              # Standardized templates for handoffs, reviews, etc.
    handoffs/               # Active work handoff files
    sessions/               # Session logs and intro markers
    docs/                   # System documentation
  tests/                    # pytest test suite
  scripts/                  # Utility scripts (seed_db.py, etc.)
  .env.example              # Environment variable template
  CLAUDE.md                 # Project guidelines for Claude Code
```

### Key Files

| File | Purpose |
|------|---------|
| `.herd/STATUS.md` | Current state of all active work, blocks, and backlogs |
| `.herd/craft.md` | Craft standards for each agent role (v0.5) |
| `CLAUDE.md` | Project conventions, pre-commit checklist, design decisions |
| `.herd/decisions/*.md` | Captured architectural decisions (HDRs 0001-0027) |
| `.env.example` | Environment variable template for secrets and config |
| `pyproject.toml` | Package configuration, dependencies, build settings |

### Herd MCP Server

The Herd MCP Server is a DuckDB-backed operational tracking system that provides 13 tools for agent coordination, ticket lifecycle management, decision recording, and token cost analytics. It runs as an MCP stdio server (default), REST API, or Slack daemon.

The database uses Data Vault 2.0 modeling (HDR-0007) with a medallion architecture:

- **Bronze**: Source extraction and staging
- **Silver**: Data Vault (hubs, satellites, links) for temporal history
- **Gold**: Dimensional model (dimensions and facts) for querying

Evidence.dev dashboards (HDR-0008) sit on top, providing operational visibility to the Architect.

### Agent Roster

| Agent | Role | Model | Status |
|-------|------|-------|--------|
| Steve | Avalon Leader (Orchestration, Judgment) | Opus | Active |
| Leonardo | Metropolis Leader (Governance, Always-On Ops) | Opus | Active |
| Wardenstein | QA Sentinel (Deep Reasoning, Pattern Intuition) | Opus | Active |
| Scribe | Documentation Executor (Synthesis, Voice) | Opus | Active |
| Mason | Backend Executor (Structured Implementation) | Sonnet | Active |
| Fresco | Frontend Executor (Component Building) | Sonnet | Active |
| Vigil | Automated QA (Mechanical Pass/Fail) | Haiku | Active |
| Rook | Mechanical Executor (Bulk Operations) | Haiku | Active |

Model assignment follows HDR-0004 with trust-level naming (HDR-0024): Opus for agents that interpret, judge, or synthesize (personal names). Sonnet for agents that execute against governed standards. Haiku for purely mechanical agents (archetype names -- no judgment required).
