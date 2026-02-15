---
status: accepted
date: 2026-02-15
decision-maker: Faust
principle: pragmatic minimums
scope: architecture
superseded-by: null
---

# Python 3.11 is the floor — everywhere

## Context

CLAUDE.md specified Python 3.9+ for dbt-conceptual. The herd-ag repos were on 3.10+. Architect observed 3.11 is the current production floor at work. No reason to carry compatibility burden for versions below that.

## Decision

Python 3.11 is the minimum across all repos — both dbt-conceptual and herd-ag. No exceptions. Update pyproject.toml, CI matrices, and CLAUDE.md accordingly.

## Consequences

- Good: Can use 3.11+ features (ExceptionGroup, TaskGroup, tomllib, StrEnum)
- Good: Simpler CI matrices, fewer version-specific workarounds
- Good: Consistent floor across the entire ecosystem
- Acceptable Tradeoff: Drops 3.9 and 3.10 users — acceptable for internal tooling
