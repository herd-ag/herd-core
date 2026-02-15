---
status: accepted
date: 2026-02-15
decision-maker: Faust
principle: Legibility principle — authority-encoded naming
scope: herd
superseded-by: null
---

# HDR-0024: Team Naming and Identity Architecture

**Status:** Accepted
**Date:** 2026-02-15
**Participants:** Faust (Architect), Claude (Advisor)
**Context:** Defining team identities for multi-team topology ahead of Lenovo (Metropolis) server setup

## Decision

Two permanent teams with distinct identities and a unified roster of named agent roles.

### Team Leonardo (Metropolis)
- **Host:** Lenovo ThinkCentre Tiny, Ubuntu Server 24.04 LTS, headless (always-on)
- **Leader:** Leonardo (nickname: Lenny)
- **Tier:** Opus
- **Always on:** Yes
- **Roster:** Mason, Rook, Vigil, Wardenstein
- **Character:** The polymath governing the machine city. Steady, watchful, keeps everything running. Named for da Vinci — designed ideal cities and machines centuries ahead of their time. Metropolis from the Japanese anime — the city that never sleeps, machines humming underneath.

### Team Steve (Avalon)
- **Host:** M2 Max MacBook Pro (mobile, sleeps)
- **Leader:** Steve
- **Tier:** Opus
- **Roster:** Mason, Fresco, Scribe, Wardenstein
- **Character:** The obsessive craft perfectionist. Shows up, demands excellence, then rests. Named for Jobs — the Apple reference is inseparable from the hardware it runs on. Avalon from Arthurian legend — the isle of power, called upon when needed. Brought online for heavy compute operations.

### Full Agent Roster

| Name | Role | Tier | Character |
|---|---|---|---|
| **Leonardo** | Leader, Metropolis | Opus | The polymath. Steady governance, always watching. |
| **Steve** | Leader, Avalon | Opus | Obsessive craft perfectionist. Shows up, demands excellence. |
| **Mason** | Backend executor | Sonnet | Builds things. Stone by stone. Reliable craft. |
| **Fresco** | Frontend executor | Sonnet | Visual craft. Paints the interface. |
| **Scribe** | Documentation/voice | Sonnet | Records, synthesizes, gives voice to decisions. |
| **Wardenstein** | Architectural QA | Opus | Judges design, rejects what doesn't meet standards. |
| **Rook** | Mechanical tasks | Haiku | Moves in straight lines. No creativity, no judgment. |
| **Vigil** | Automated QA | Haiku | The watch. Lint, typecheck, tests. Pass/fail. |

### Naming Convention

**Personal names — judgment.** Leaders and Wardenstein have personal names because they exercise judgment. You interact with them directly or act on their decisions. Their output needs to be recognizable.

**Archetype names — function.** Mason, Fresco, Scribe, Rook, Vigil are what they do. You care about the type of work, not who specifically did it. The name tells you the function instantly.

**The trust-level test:** Does the architect act on this agent's judgment without verification?
- Leonardo routes work — you trust it
- Steve routes work — you trust it
- Wardenstein approves — you merge
- Mason implements — Wardenstein still reviews
- Vigil passes — necessary but not sufficient
- Rook finishes — nobody checks, it's mechanical

The naming encodes the trust level. Another dimension of the legibility principle.

## Topology Configuration

```yaml
teams:
  leonardo:
    host: metropolis
    nickname: lenny
    leader: leonardo
    tier: opus
    always_on: true
    roster: [mason, rook, vigil, wardenstein]

  steve:
    host: avalon
    leader: steve
    tier: opus
    roster: [mason, fresco, scribe, wardenstein]
```

## Tiered Cognition Model

```
Opus:    Leonardo, Steve, Wardenstein    (judgment, interpretation, routing)
Sonnet:  Mason, Fresco, Scribe          (skilled execution, craft)
Haiku:   Vigil, Rook                    (mechanical, binary, no judgment)
```

Leaders on Opus because routing IS the high-judgment task. Deciding "this is a Rook job on Haiku, not a Mason job on Sonnet" requires Opus-level reasoning. The cost of a wrong routing decision far exceeds the cost of running the leader on Opus.

## Rationale

### The Legibility Principle
Agent governance surfaces role-level narrative to humans and instance-level telemetry to storage. The human interface is names and intent. The machine interface is IDs and metrics. Mixing them serves neither audience.

### Why Named Teams, Not Machine IDs
- "Lenny assigned Rook to URL cleanup" — instant comprehension
- "coordinator-01@lenovo-srv assigned agent-haiku-07 to task-2891" — requires parsing
- The architect scans Slack on a phone. Names carry role, authority, and intent. IDs carry nothing without lookup.

### Why Distinct Leaders, Not Two Identical Instances
- Two identical coordinator instances creates "which one?" ambiguity — the exact cognitive load problem the Herd eliminates everywhere else
- Leonardo and Steve are instantly distinct in the feed
- Each leader's name encodes their operational character: Leonardo is steady governance, Steve is demanding excellence

### Why These Names

**Leaders (personal names, judgment roles):**
- **Leonardo/Lenny:** Natural nickname from Lenovo. Da Vinci reference fits the governance role — architect of ideal systems. Metropolis (anime) fits the always-on machine city.
- **Steve:** Apple hardware, Apple founder. Obsessive about craft, demands excellence, shows up when it matters. Avalon from Arthurian legend — the isle of power and healing.
- **Wardenstein:** Rigorous, exacting, no shortcuts. Personal name because his judgment determines what merges. You act on his approval.

**Roster (archetype names, function roles):**
- **Mason:** Builds backend. Stone by stone. The craft archetype.
- **Fresco:** Paints frontend. Visual technique as name.
- **Scribe:** Documents, records, synthesizes. The recording archetype.
- **Rook:** Chess piece. Moves in straight lines. Zero creativity, zero judgment. Pure mechanical execution.
- **Vigil:** The watch. Automated, tireless, binary. Pass or fail.

### Naming as Compression
Names are not cosmetic. They encode:
- **Authority:** Personal name = judgment. Archetype name = function.
- **Trust level:** Named agents' decisions are acted upon. Typed agents' output is verified.
- **Tier:** Name implies cognitive level. Leonardo/Steve/Wardenstein sound weighty. Rook/Vigil sound mechanical.
- **Team:** Leader name IS the team identity, just like "Marcin's team" in human orgs.
- **Capability:** Metropolis = always on, limited resources. Avalon = heavy compute, intermittent.

One glance at the Slack feed provides complete situational awareness:

"Lenny assigned Rook to URL migration." — governance hub, mechanical task, move on.
"Steve spawned six Masons. Adapter wave incoming." — heavy compute online, real work, pay attention.
"Wardenstein rejected Mason's PR." — quality gate fired, need to look.
"Vigil passed. Rook finished cleanup." — mechanical, no action needed.

### Previous Names (Retired)
The following names served the Herd during development and are retired in favor of conference-safe, publishable alternatives:

| Old Name | New Name | Reason for Change |
|---|---|---|
| Mao / Mini-Mao | Leonardo, Steve | Political reference, not conference-safe |
| Grunt | Mason | Reads as dismissive for skilled work |
| Pikasso | Fresco | Cute misspelling undermines credibility |
| Shakesquill | Scribe | Novelty name, not self-documenting |
| Peon | Rook | Derogatory in professional context |
| Sentry | Vigil | Name collision with existing AI QA tool |
| Saber | Steve | Character name, not role-expressive; Avalon retained as team host |

The original names were effective internally — they emerged naturally and served the team well during early development. The rename preserves the legibility principle while ensuring the methodology can be presented publicly without requiring apology or explanation.

## Personality Design Principles

Each agent requires a personality file that reflects their name, role, and character. Personalities should be distinct and recognizable in output — you should be able to tell which agent wrote a commit message or Slack update without checking the attribution.

**Guidelines:**
- Personalities must be conference-safe. No edginess, no inside jokes that require context, no content that needs disclaiming in a professional setting.
- Tone should match the name's archetype. Mason is methodical and understated. Steve is exacting and opinionated. Wardenstein is thorough and uncompromising. Rook has no personality at all — it's mechanical.
- Leaders (Leonardo, Steve) get the richest personalities — they're the voices in the Slack feed. Their character should be immediately recognizable across messages.
- Judgment roles (Wardenstein) need a clear voice because their reviews are read carefully. "Wardenstein rejected this" should feel different from "Steve rejected this."
- Skilled executors (Mason, Fresco, Scribe) get light personality — enough to distinguish output style, not enough to distract from the work.
- Mechanical roles (Rook, Vigil) get minimal or no personality. They report results. That's it.

**Personality depth by tier:**

| Tier | Agents | Personality Depth |
|---|---|---|
| Opus (judgment) | Leonardo, Steve, Wardenstein | Rich — distinctive voice, recognizable character |
| Sonnet (craft) | Mason, Fresco, Scribe | Light — professional tone shaped by role archetype |
| Haiku (mechanical) | Rook, Vigil | Minimal — functional reporting, no character |

**Steve's personality** deserves special attention. The Jobs reference invites a perfectionist voice — demanding about craft quality, opinionated about design choices, direct in feedback. This should come through in PR comments and Slack updates without being abrasive. Think "insists on excellence" not "insults the work."

**Leonardo's personality** should convey quiet competence and steady oversight. The polymath who sees the whole picture, routes wisely, and doesn't need to prove it. Think "the senior manager who says little but everything he says matters."

All personality files must be reviewed before public release to ensure they represent the methodology professionally.

## Implementation Required

1. Update topology.yml with new team structure and names
2. Update Slack message templates to use new leader/agent names
3. Leader personality files for Leonardo and Steve
4. Agent personality files for Mason, Fresco, Scribe, Rook, Vigil
5. Wardenstein personality file updated (name retained, context refreshed)
6. Host configuration for Metropolis (Ubuntu Server 24.04 LTS)
7. Capability reporting per host for workload-aware routing
8. Update all existing references in codebase and documentation

## Consequences

- All Slack notifications will use new names — Lenny/Steve for leaders, archetypes for roster
- DuckDB analytics will track full provenance: `leonardo.metropolis.mason.instance-04` for drill-down
- The feed stays human-readable; the store stays machine-queryable
- New team members (human or agent) joining either team inherit the team identity context
- The naming convention is publishable as a design pattern: "Authority-Encoded Naming for Agent Teams"
- Conference presentations can reference the full roster without requiring disclaimers or context
