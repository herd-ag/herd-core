---
status: accepted
date: 2026-02-15
decision-maker: Faust
principle: deployment consistency
scope: architecture
superseded-by: null
---

# Deployment consistency: two install modes with content path fallback

## Context

herd-core needs to be safe to use as a dependency even during active development. Consuming projects (like dbt-conceptual) install herd-core for its MCP server, role files, and craft standards. But if herd-core is changing daily, how do you get reproducible installs while still allowing tight development loops?

## Decision

Two install modes. Content path fallback chain. Secrets in `.env` with `python-dotenv` as an optional dependency.

**Install modes:**
- **Dev editable**: `pip install -e "/path/to/herd-core[adapters,env]"` -- for active development. Changes take effect immediately.
- **Stable tag pin**: `pip install "herd-core[adapters] @ git+https://github.com/herd-ag/herd-core@v0.2.0"` -- for reproducible installs. Pinned to a specific release.

**Content path resolution** (`get_herd_content_path()`):
1. Project root `.herd/` -- project-specific overrides
2. Package root `.herd/` -- canonical defaults from herd-core install

This means consuming projects can override any role file, craft standard, or template by placing their own version in their project's `.herd/` directory. A bare `pip install` gives working defaults out of the box.

**Secret management:**
- `.env.example` in the repo as a template (committed)
- `.env` for actual secrets (gitignored, never committed)
- `python-dotenv` as an optional dependency (`env` extra)
- Loaded at server startup in `__main__.py`

## Alternatives Considered

* Single install mode (editable only) -- rejected because consuming projects need reproducible installs for CI and production
* Bundling secrets in `.mcp.json` env blocks -- rejected because this scatters secrets across config files and they can accidentally be committed
* Making `python-dotenv` a hard dependency -- rejected because it is only needed for development and local running, not for the framework's core functionality

## Consequences

* Good -- Consuming projects get working defaults from a bare install without copying files
* Good -- Project-level overrides take precedence, so customization is clean and non-invasive
* Good -- Secrets stay in one place (`.env`) and are never committed
* Acceptable Tradeoff -- Two install modes require documentation and user awareness of which to use
* Acceptable Tradeoff -- The fallback chain means you need to know which `.herd/` is being read (project vs package)
