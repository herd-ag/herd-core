---
status: accepted
date: 2026-02-15
decision-maker: Faust
principle: three experience dimensions
scope: herd
superseded-by: null
---

# Three experience dimensions: UX, DX, AX as explicit concerns

## Context

The Herd builds software that serves three distinct audiences: end users (UX), the developer/architect running the herd (DX), and the agents themselves (AX). Without explicit framing, these dimensions collapse into a single "make it work" mindset that optimizes for none of them.

## Decision

UX, DX, and AX are all first-class concerns. Each role has explicit experience priorities.

**UX** (end user experience): Fresco's paramount concern. Every interactive element needs loading, empty, and error states. Accessibility is non-negotiable. The user never sees the agent -- they see the product.

**DX** (developer/architect experience): Steve owns this. The Architect's experience running the herd -- spawning agents, reading briefs, reviewing PRs, making decisions -- must be efficient and low-friction. Mason and Leonardo balance DX with AX in their implementation work.

**AX** (agent experience): A new concern. Are we making agent work harder than it needs to be? Vigil and Wardenstein factor AX into QA -- if a spawn prompt is unnecessarily complex, if a tool requires redundant input, if a workflow creates friction for agents, that is a defect.

The hierarchy is not fixed. It depends on context:
- Building user-facing features: UX > DX > AX
- Building agent infrastructure: AX > DX > UX
- Building developer tooling: DX > AX > UX

## Consequences

* Good -- Each role has explicit experience priorities rather than implicit assumptions
* Good -- AX becomes a first-class concern, which means agent ergonomics improve over time
* Good -- The hierarchy provides a decision framework when experience priorities conflict
* Acceptable Tradeoff -- Three dimensions mean three sets of quality criteria to evaluate
