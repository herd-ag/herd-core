# Workflow Guide

How work flows through The Herd, from ticket to merge.

---

## Ticket Lifecycle

Every piece of work moves through these states in order. No skipping. No retroactive changes.

| State | Description |
|-------|-------------|
| Triage | New issue or request, not yet assessed |
| Backlog | Assessed, not yet prioritized for work |
| Assigned | Architect has assigned to an agent, not yet started |
| In Progress | Agent is actively implementing |
| PR Submitted | Code complete, PR created, awaiting QA |
| QA Review | Wardenstein is reviewing |
| Architect Review | QA passed, awaiting Architect merge decision |
| Done | Merged to main |
| Cancelled | Dropped (with reason) |
| Rejected | QA or Architect rejected; will not proceed |

Ticket titles follow the convention: `<type>(<scope>): <description>`. Example: `feat(governance): add manifest schema validation`.

Every ticket must have: a role label (backend/frontend/docs/qa), a type label (feature/bug/refactor/chore), and assignment to a project.

---

## Agent Spawning

When the Architect assigns work, Steve spawns the appropriate agent. Every spawn includes full context -- a bare prompt with just a work description is not acceptable.

### Spawn Checklist

Before spawning, Steve reads and includes ALL of the following in the agent's prompt:

1. **Full role file**: Complete content of `.herd/roles/<agent>.md`
2. **Craft standards**: The agent's section from `.herd/craft.md`
3. **Project guidelines**: Key sections from `CLAUDE.md` (pre-commit checks, project structure, design decisions)
4. **Slack token**: `export HERD_SLACK_TOKEN="..."` so the agent can post
5. **Session protocol**: Agent instructed to follow their session start sequence
6. **Skills context**: Equivalent instructions for the agent's listed skills
7. **Branch protection rule**: The explicit "NEVER push to main" block
8. **Commit + push posting**: Agent instructed to post to `#herd-feed` after every commit
9. **Slack URL format**: `<url|display text>` requirement
10. **Model target**: Opus, Sonnet, or Haiku per HDR-0004

### Post-Spawn

After spawning, Steve:

- Moves the Linear ticket to In Progress
- Updates STATUS.md with the active work entry
- Adds the worktree path to `settings.local.json` if applicable

---

## Implementation Flow

Each implementing agent (Mason, Fresco) follows the same core workflow:

1. **Read the assignment**: Linear ticket or task description from the Architect
2. **Create branch**: `herd/<agent>/<ticket-id>-<short-description>`
3. **Implement with tests**: Code and tests in the same commit
4. **Run local checks**: `pytest`, `ruff check`, `black --check`, `mypy` -- all green before proceeding
5. **Create handoff note**: `.herd/handoffs/<ticket-id>.md` using the handoff template
6. **Push branch and submit PR**
7. **Post to `#herd-feed`**: Include ticket ID, description, and PR URL
8. **Update Linear ticket**: Move to PR Submitted

### Milestone Posts

Agents post to `#herd-feed` at each implementation milestone (not on a timer -- only when the milestone is reached):

- Branch created
- Code complete
- Tests passing
- Pre-commit checks passing
- PR submitted
- Blocked (posted to `#herd-blocked` instead)

---

## The QA Gate

Wardenstein reviews every PR before merge. No exceptions. This is codified in HDR-0005.

### Review Protocol

1. **Read the handoff note**: Understand what was built and why before reading code
2. **Run full test suite**: Not just new tests -- the entire suite, checking for regressions
3. **Coverage analysis**: `pytest --cov --cov-report=term-missing` on changed files. Gate: >80%
4. **Test quality audit**: Do assertions prove meaningful behavior? Could the implementation be wrong and still pass?
5. **Edge case review**: Empty/null input, single-element, boundary, malformed, invalid types
6. **Pattern consistency**: Does new code follow existing conventions?
7. **Error message review**: Are messages diagnostic (what, expected, where)?
8. **Integration check**: Do changes break anything in the broader system?

### Outcomes

**QA PASS**: Wardenstein posts approval comment on the GitHub PR and to `#herd-feed`. Ticket moves to Architect Review.

**QA FAIL**: Wardenstein posts specific rejection comments on the PR (with file:line references and required fixes). The implementing agent reads the comments, fixes on the branch, and pushes updates. Wardenstein re-reviews.

### PR Comments Are Mandatory

Wardenstein always posts the full QA review as a comment on the GitHub PR using `gh api`. The Architect reviews PRs on GitHub -- a review that only lives on Linear or in local files is invisible to the Architect.

---

## Merge Authority

Only the Architect merges. Steve executes the merge command with `--admin` after QA passes, but the decision to merge is the Architect's.

The flow is always:

1. Implementing agent submits PR
2. Wardenstein reviews
3. QA PASS: Steve merges (with Architect approval)
4. QA FAIL: Back to the implementing agent for fixes

"Approve as needed" means "merge after QA passes" -- not "skip QA."

---

## Handoff Protocol

When an implementing agent completes work that affects another agent's domain, they create a handoff note at `.herd/handoffs/<ticket-id>.md`.

The handoff contains:

- **Summary**: What was done and why
- **What Changed**: Specific files and changes (code and tests)
- **Testing**: Status of pytest, ruff, black, mypy
- **QA Notes**: What Wardenstein should test, known issues
- **Documentation Notes**: What Scribe should document (user-facing changes)

Handoffs are the primary coordination mechanism between agents. Steve monitors for stale handoffs (>24 hours unactioned) and flags them.

---

## Session Management

### Session Start

Every agent follows the same startup sequence:

1. Read `.herd/STATUS.md` -- understand current state
2. Read their latest session file -- pick up where they left off
3. Read `CLAUDE.md` -- refresh on project conventions
4. Read `.herd/craft.md` -- their section and sections of agents they interact with
5. Read relevant handoff files
6. Check intro marker -- if first session, post to `#introductions`
7. Post greeting to `#herd-feed`
8. Check assignment

### Session End

Steve at session end:

1. Updates STATUS.md with final state
2. Reviews HDRs drafted during the session
3. Writes session file: `.herd/sessions/steve-<date>.md`

Implementing agents write their own session files: `.herd/sessions/<agent>-<date>.md` with current branch, last commit, what is left, and context for the next session.

---

## Branch Protection

No agent ever pushes to main. This is codified in HDR-0006.

- All work goes on feature branches
- Branch naming: `herd/<agent>/<ticket-id>-<short-description>`
- PRs are created from feature branches
- The Architect merges
- Every spawn prompt includes the explicit rule

If an agent violates this, it is immediately visible in `git log`. Main only moves via merge commits.

---

## Slack Channels

| Channel | Purpose |
|---------|---------|
| `#herd-feed` | All agent activity: milestone posts, PR submissions, QA results, daily briefs |
| `#herd-blocked` | Blockers requiring Architect attention |
| `#introductions` | First-time agent introductions (one post per agent, ever) |
| `#herd-decisions` | Agent decision records (posted via `herd_record_decision`) |

### Slack Posting Rules

- All posts must include clickable URLs with display text using Slack's link format: `<url|display text>`
- Bare ticket numbers (`DBC-43`) without links are not acceptable
- Raw URLs without display text are not acceptable
- Agents post after every commit + push, not just at final PR submission

---

## Decision Capture

Steve detects Architect decisions during sessions and captures them as Herd Decision Records (HDRs).

Two modes:

**Silent capture**: When the decision signal is clear (principle invocation, explicit reasoning, directive with rationale), Steve drafts the HDR immediately without interrupting the session flow.

**Prompt the Architect**: When the signal is ambiguous, Steve asks: "That sounds like it could be an architectural decision -- should I capture an HDR?"

See `hdr-guide.md` for the full HDR specification.
