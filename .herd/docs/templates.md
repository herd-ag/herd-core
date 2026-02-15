# Templates Reference

The Herd uses 8 standardized templates in `.herd/templates/`. Each serves a specific purpose in the coordination workflow.

---

## 1. HDR Template

**File**: `.herd/templates/hdr.md`
**Purpose**: Capture Architect architectural decisions as Herd Decision Records.
**Used by**: Steve

### Key Fields

| Field | Description |
|-------|-------------|
| `status` | `accepted`, `superseded`, or `rejected` |
| `date` | Date of the decision (YYYY-MM-DD) |
| `decision-maker` | Always `Faust` |
| `principle` | The governing principle for this decision |
| `scope` | Area affected: cli, ui, governance, workflow, architecture, herd, branding |
| `superseded-by` | HDR number if replaced, otherwise `null` |

Body sections: Context, Decision, Alternatives Considered (optional), Consequences.

### Usage

Steve detects a decision signal in the Architect's response and drafts an HDR using this template. The Decision section should use the Architect's own words where possible. See `hdr-guide.md` for the full capture protocol.

---

## 2. Handoff Template

**File**: `.herd/templates/handoff.md`
**Purpose**: Transfer work context between agents (implementation to QA, implementation to docs).
**Used by**: Mason, Fresco (creating); Wardenstein, Scribe (receiving)

### Key Fields

| Field | Description |
|-------|-------------|
| `From` | Originating agent name and role |
| `To` | Receiving agent name and role |
| `Date` | Handoff date |
| `Branch` | Git branch name |

Body sections: Summary, What Changed (code and test changes by file), Testing (status of pytest/ruff/black/mypy), QA Notes (what to test, known issues).

### Usage

Implementing agents create a handoff at `.herd/handoffs/<ticket-id>.md` before submitting their PR. The "QA Notes" section tells Wardenstein what to focus on. The handoff may also include a "What to document" section for Scribe.

---

## 3. Session Template

**File**: `.herd/templates/session.md`
**Purpose**: Capture end-of-session state for continuity across sessions.
**Used by**: All agents

### Key Fields

| Field | Description |
|-------|-------------|
| Agent name | Which agent wrote this session file |
| Session date | YYYY-MM-DD |

Body sections: What I Worked On, Current State (branch, last commit, status), What's Left, Context for Next Session.

### Usage

At the end of every session, each agent writes a session file to `.herd/sessions/<agent>-<date>.md`. The next session starts by reading this file to restore context. This prevents knowledge loss across session boundaries.

---

## 4. QA Review Template

**File**: `.herd/templates/qa-review.md`
**Purpose**: Standardize Wardenstein's QA review output.
**Used by**: Wardenstein

### Key Fields

| Field | Description |
|-------|-------------|
| `Reviewed by` | Always `Wardenstein` |
| `PR` | PR number |
| `Date` | Review date |
| `Verdict` | `QA PASS` or `QA FAIL` |

Body sections: Summary, Test Results (suite status, coverage %, new tests), Findings (specific issues with file:line references for failures), Missing Coverage, Required Fixes (for failures only), Follow-up Suggestions (non-blocking).

### Usage

Wardenstein uses this template to structure the QA review. The full review is posted as a comment on the GitHub PR (via `gh api`). For QA FAIL, every rejection includes: what is wrong, why it matters, and what needs to change.

---

## 5. Ticket Draft Template

**File**: `.herd/templates/ticket-draft.md`
**Purpose**: Standardize Linear ticket creation from Architect bullet points.
**Used by**: Steve

### Key Fields

| Field | Description |
|-------|-------------|
| Title | `<type>(<scope>): <description>` |
| Types | feat, fix, refactor, chore, docs, test |
| Scopes | cli, governance, scanner, parser, validator, exporter, server, frontend, mcp, deploy, herd |

Body sections: Description (one paragraph max), Acceptance Criteria (observable, testable), Labels (role + type), Dependencies, Files Likely Affected.

### Usage

When the Architect provides bullet-point priorities, Steve drafts tickets using this template. The Architect reviews and activates -- Steve drafts but never activates. The "Files Likely Affected" field helps Steve detect ownership conflicts when multiple agents work in parallel.

---

## 6. Escalation Template

**File**: `.herd/templates/escalation.md`
**Purpose**: Structure escalations to the Architect when agents are blocked.
**Used by**: Steve (on behalf of blocked agents)

### Key Fields

| Field | Description |
|-------|-------------|
| `From` | Agent name raising the escalation |
| `Date` | Escalation date |
| `Blocking` | What work is blocked |

Body sections: Question (specific decision needed), Context (who, what, why), Options (table with pros/cons), Impact of Delay (who is idle, what cascades).

### Usage

When an agent is blocked on an Architect decision, Steve creates an escalation using this template. The escalation must be complete -- "Mason is blocked" is not useful. "Mason is blocked on DBC-42: needs Architect decision on whether governance is optional or required. Options: optional (backward compatible) vs required (breaking change). Blocking QA handoff." is useful.

---

## 7. Daily Brief Template

**File**: `.herd/templates/daily-brief.md`
**Purpose**: Structure Steve's morning status report for the Architect.
**Used by**: Steve

### Key Fields

| Field | Description |
|-------|-------------|
| Date | Brief date |
| Generated by | Always Steve |

Body sections: Active Work (table: ticket, agent, state, notes), Blocked (table: ticket, agent, blocked on, since), Pending Architect Review (table: ticket, PR, submitted), Stale Handoffs (>24h), Decisions Captured (HDRs since last brief), Recommendations (options, not decisions).

### Usage

Steve generates this at session start after reading STATUS.md, handoffs, session files, and git log. The brief is structured, not narrative -- the Architect scans for decisions that need making, not for prose.

---

## 8. Spawn Checklist Template

**File**: `.herd/templates/spawn-checklist.md`
**Purpose**: Verify that every agent spawn includes all required context.
**Used by**: Steve

### Key Fields

| Field | Description |
|-------|-------------|
| Agent Name | Which agent is being spawned |
| Ticket | Ticket ID, title, and description |
| Branch | `herd/<agent>/<ticket-id>-<short>` |
| Worktree | `/private/tmp/<agent>-<ticket-id>` if using worktree |

### Pre-Spawn Checklist

- Role file read and included
- Craft standards section included
- CLAUDE.md project guidelines included
- Slack token included
- Session start protocol instructed
- Skills context included
- Branch protection rule included
- Commit + push posting instructed
- Slack URL format requirement stated
- Model target (Opus or Sonnet) specified

### Post-Spawn Checklist

- Linear ticket moved to In Progress
- STATUS.md updated
- Worktree added to settings if applicable

### Usage

Steve runs through this checklist before every agent spawn. Incomplete spawns produce output that does not meet quality standards and must be discarded. The checklist exists because spawn failures were a recurring source of operational friction.
