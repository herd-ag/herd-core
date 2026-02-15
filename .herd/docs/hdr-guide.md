# Herd Decision Records Guide

## What an HDR Is

A Herd Decision Record captures an Architect decision as a byproduct of working. Not a formal process. Not a committee artifact. A lightweight record of what was decided, why, and which principle governed the choice.

HDRs exist because decisions are the most valuable output of architecture work -- and the most likely to be lost. Code captures *what*. Tests capture *behavior*. HDRs capture *why*.

The format is adapted from MADR 4.0 (Markdown Any Decision Records). The adaptation strips the ceremony and keeps the payload.

---

## Template Format

HDRs live in `.herd/decisions/` with filenames following the pattern `NNNN-short-title.md`.

### Front Matter

```yaml
---
status: accepted
date: YYYY-MM-DD
decision-maker: Faust
principle: governing principle
scope: cli | ui | governance | workflow | architecture | herd | branding
superseded-by: null
---
```

| Field | Description |
|-------|-------------|
| `status` | `accepted`, `superseded`, or `rejected` |
| `date` | Date the decision was made |
| `decision-maker` | Always `Faust` (the Architect) |
| `principle` | The governing principle (e.g., "Unix philosophy", "bidirectional by default", "fail fast, fail clearly") |
| `scope` | Which area of the project this affects |
| `superseded-by` | HDR number if this decision has been replaced, otherwise `null` |

### Body Sections

```markdown
# Short title: problem to solution

## Context
1-3 sentences. What situation or question triggered this decision?

## Decision
What was decided and why. Written in the Architect's voice -- direct, principle-driven.

## Alternatives Considered
Optional. Only populated when alternatives were naturally mentioned.

## Consequences
What follows from this decision. Each consequence labeled: Good, Bad, or Acceptable Tradeoff.
```

The **Decision** section is the core payload. It should read like the Architect said it. Do not paraphrase into corporate-speak. "If you don't want stubs, don't run sync" is better than "Users who do not wish to generate stubs should refrain from executing the sync command."

---

## Capture Modes

Steve operates in two modes when detecting decisions.

### Mode 1: Silent Capture

When the decision signal is clear, Steve captures it immediately without interrupting the session:

1. Detect the decision signal in the Architect's response
2. Determine the next sequence number
3. Draft the HDR using the template
4. Write to `.herd/decisions/NNNN-short-title.md`
5. Post to `#herd-feed`
6. Continue the session

### Mode 2: Prompt the Architect

When a response sounds like it might contain a decision but is not stated as one, Steve asks:

> That sounds like it could be an architectural decision -- should I capture an HDR?
> "Brief summary of what was heard"

If yes, capture it. If no, move on. Do not ask twice about the same topic.

---

## Detection Heuristics

Steve listens for these signals:

| Signal | Example | Action |
|--------|---------|--------|
| Principle invocation | "We do X because Unix philosophy" | Capture with principle field |
| Explicit reasoning | "Remove the flag because sync should be bidirectional" | Capture -- extract the "because" |
| Rejection + alternative | "Don't use ABC, use Protocol patterns because..." | Capture with Alternatives section |
| Directive with rationale | "One command, one behavior, predictable outcome" | Capture -- the rationale IS the decision |
| Precedent setting | "From now on, all validators use..." | Capture -- high priority, affects future work |

### What NOT to Capture

- Style preferences without reasoning -- belongs in `craft.md`
- Task assignments -- belongs in Linear
- "Yes, do that" without reasoning -- approval, not a decision
- Questions or thinking-out-loud -- not decided yet

---

## Supersession

When a new decision supersedes an old one:

1. Update the old HDR's front matter: set `status: superseded` and `superseded-by: NNNN`
2. Create the new HDR with a note in the Context section referencing the old one

---

## Sequence Numbers

- Never reuse a number
- Never renumber existing HDRs
- Gaps are fine (deleted HDRs leave gaps)
- Determine the next number by checking existing files in `.herd/decisions/`

---

## Existing HDRs

Twenty-nine decisions have been captured as of the project's current state. The table below shows the original fourteen; see `.herd/decisions/` for the complete set (HDRs 0001-0029).

| HDR | Title | Scope | Principle |
|-----|-------|-------|-----------|
| 0001 | Remove `--create-stubs` flag -- sync is bidirectional by default | cli | bidirectional by default |
| 0002 | `conceptual.yml` is the single source of truth | architecture | Principles > Capabilities |
| 0003 | 100% AI-generated codebase | herd | informed ownership |
| 0004 | Opus for interpreters, Sonnet for executors | herd | Principles > Capabilities |
| 0005 | QA review before merge -- always | workflow | fail fast, fail clearly |
| 0006 | Never push to main -- all work on feature branches | workflow | fail fast, fail clearly |
| 0007 | Data Vault 2.0 for Herd MCP analytics | architecture | Principles > Capabilities |
| 0008 | Evidence.dev for Herd dashboards | architecture | Unix philosophy |
| 0009 | All agents must be aware of MCP and docs, and report inconsistencies | herd | fail fast, fail clearly |
| 0010 | Herd MCP is the single pane of glass for ticket operations | architecture | Unix philosophy |
| 0011 | Herd MCP must be the single pane for all common agent flows | architecture | Unix philosophy |
| 0012 | The Herd will be extracted into a standalone, reusable framework | herd | Principles > Capabilities |
| 0013 | Agent Decision Records flow through Slack for human feedback | workflow | informed ownership |
| 0014 | Backfill HerdDB with historical data from Linear and GitHub | architecture | Principles > Capabilities |

### HDR-0001: Remove --create-stubs flag

The `sync` command had a `--create-stubs` flag that made its behavior context-dependent. The flag was removed. Sync is bidirectional by default -- it always creates stubs. One command, one behavior, predictable outcome.

### HDR-0002: conceptual.yml is the single source of truth

The conceptual model lives in a single `conceptual.yml` file. Everything flows from it -- stubs, governance, validation, diagrams, coverage. Git-versioned, diffs cleanly, requires no special tooling.

### HDR-0003: 100% AI-generated codebase

Every line of code is AI-generated. The Architect designs, decides, and reviews. Agents implement. This is a deliberate experiment in AI-assisted development where the Architect's value is in design decisions and quality judgment.

### HDR-0004: Opus for interpreters, Sonnet for executors

Agents that interpret, judge, or synthesize (Steve, Wardenstein, Scribe) run on Opus. Agents that execute against governed standards (Mason, Fresco) run on Sonnet. Haiku for purely mechanical agents (Vigil, Rook).

### HDR-0005: QA before merge -- always

Every PR goes through Wardenstein before merge. No exceptions. Triggered by an incident where the coordinator merged PRs without QA, interpreting "approve as needed" as blanket merge authority.

### HDR-0006: Never push to main

No agent pushes to main. All work on feature branches. Triggered by an incident where an agent pushed directly to main, bypassing PR flow and QA. Enforced through spawn prompts.

### HDR-0007: Data Vault 2.0 for Herd MCP analytics

The Herd MCP Server uses Data Vault 2.0 modeling with DuckDB. Hubs for business keys, satellites with SCD Type 2, links for relationships. Insert-only ledger pattern with content-addressable versioning. Medallion architecture (bronze, silver, gold).

### HDR-0008: Evidence.dev for Herd dashboards

Evidence.dev (SQL + Markdown) for operational dashboards instead of custom React frontend. Dashboards are code -- versioned in git, reviewed in PRs, deployed as static pages.
