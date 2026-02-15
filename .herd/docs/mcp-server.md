# Herd MCP Server Guide

The Herd MCP Server is a Model Context Protocol server for operational tracking and team coordination. Built with FastMCP and DuckDB, it provides 13 tools for logging, status queries, agent lifecycle management, ticket tracking, code reviews, decision recording, identity loading, and token cost analytics.

Agents interact with the server through MCP tool calls. The server records all activity to DuckDB and optionally posts to Slack.

## Installation

```bash
pip install -e "/path/to/herd-core[env]"
```

This installs the `herd_mcp` package and its dependencies (mcp, duckdb, aiohttp, slack_sdk). The `env` extra adds `python-dotenv` for automatic `.env` loading.

## Environment Setup

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

The `.env` file is gitignored and never committed. When `python-dotenv` is installed, values are loaded automatically at server startup.

See `.env.example` for all available variables.

## Database Setup

```bash
python3 scripts/seed_db.py
```

This creates `.herd/herddb.duckdb` (or the path specified by `HERD_DB_PATH`) and populates:

- `agent_def` -- all eight Herd agents with roles, branch prefixes, and default models
- `model_def` -- Claude model pricing (Opus 4.6, Sonnet 4.5, Sonnet 4, Haiku 4)

The script is idempotent. Running it again updates existing records without creating duplicates.

## Configuration

Add the Herd MCP server to your `.mcp.json`:

```json
{
  "mcpServers": {
    "herd": {
      "command": "python3",
      "args": ["-m", "herd_mcp"],
      "env": {
        "HERD_AGENT_NAME": "mason",
        "HERD_DB_PATH": ".herd/herddb.duckdb"
      }
    }
  }
}
```

Restart Claude Code after adding the configuration.

## Run Modes

| Command | Mode | Description |
|---------|------|-------------|
| `python -m herd_mcp` | MCP stdio | Default. Tool calls via MCP protocol over stdio. |
| `python -m herd_mcp serve` | REST API | HTTP server on `HERD_API_HOST:HERD_API_PORT` (default: `0.0.0.0:8420`). |
| `python -m herd_mcp slack` | Daemon | REST API + Slack Socket Mode for event-driven coordination. |

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `HERD_AGENT_NAME` | Yes | -- | Agent identity code. Must match an `agent_code` in `agent_def`. |
| `HERD_DB_PATH` | No | `.herd/herddb.duckdb` | Path to the DuckDB database file. |
| `HERD_SLACK_TOKEN` | For Slack tools | -- | Slack bot token (`xoxb-...`) for posting messages. |
| `LINEAR_API_KEY` | For ticket tools | -- | Linear API key (`lin_api_...`) for ticket operations. |
| `HERD_API_HOST` | For `serve` mode | `0.0.0.0` | REST API bind address. |
| `HERD_API_PORT` | For `serve` mode | `8420` | REST API port. |
| `SLACK_APP_TOKEN` | For `slack` mode | -- | Slack app token (`xapp-...`) for Socket Mode. |
| `SSL_CERT_FILE` | No | -- | Path to CA cert bundle (macOS-specific). |

### Valid HERD_AGENT_NAME Values

Current agents:

| Code | Role | Model Tier |
|---|---|---|
| `steve` | Avalon leader (orchestration, judgment) | Opus |
| `leonardo` | Metropolis leader (governance, always-on ops) | Opus |
| `wardenstein` | QA sentinel (deep reasoning, pattern intuition) | Opus |
| `scribe` | Documentation executor (synthesis, voice) | Opus |
| `mason` | Backend executor (structured implementation) | Sonnet |
| `fresco` | Frontend executor (component building) | Sonnet |
| `vigil` | Automated QA (mechanical pass/fail) | Haiku |
| `rook` | Mechanical executor (bulk operations) | Haiku |

Legacy aliases (still accepted, mapped to current names):

| Legacy Code | Maps To |
|---|---|
| `grunt` | Mason |
| `pikasso` | Fresco |
| `mini-mao` | Steve |
| `shakesquill` | Scribe |

## Tool Reference

### herd_log

Post a message to Slack and log the activity.

```
herd_log(message, channel?, await_response?)
```

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `message` | `str` | Yes | -- | Message content to post. |
| `channel` | `str \| None` | No | `#herd-feed` | Slack channel to post to. |
| `await_response` | `bool` | No | `False` | If `True`, wait for and return thread responses. |

**Returns**: Dict with `posted_ts` (Slack timestamp), `event_id`, and optional `responses` list.

**Requires**: `HERD_SLACK_TOKEN` environment variable.

---

### herd_status

Get current status of Herd agents, sprint, and blockers.

```
herd_status(scope?)
```

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `scope` | `str` | No | `"all"` | Status scope. Options: `"all"`, `"agents"`, `"sprint"`, `"blockers"`. |

**Returns**: Dict with `agents` status list, `sprint` info, and `blockers` list.

---

### herd_spawn

Spawn new agent instances.

```
herd_spawn(count, role, model?)
```

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `count` | `int` | Yes | -- | Number of agents to spawn. |
| `role` | `str` | Yes | -- | Agent role code (e.g., `"mason"`, `"fresco"`, `"wardenstein"`, `"scribe"`). Accepts both current and legacy names. |
| `model` | `str \| None` | No | Role default | Model override (e.g., `"claude-opus-4-6"`). Uses role default if not specified. |

**Returns**: Dict with `instances` list containing spawned agent instance codes.

---

### herd_assign

Assign a ticket to an agent.

```
herd_assign(ticket_id, agent_name?, priority?)
```

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `ticket_id` | `str` | Yes | -- | Linear ticket ID (e.g., `DBC-87`). |
| `agent_name` | `str \| None` | No | Current agent | Agent to assign to. Uses calling agent if `None`. |
| `priority` | `str` | No | `"normal"` | Assignment priority: `"normal"`, `"high"`, `"urgent"`. |

**Returns**: Dict with assignment confirmation, agent details, and ticket details.

---

### herd_transition

Transition a ticket to a new status.

```
herd_transition(ticket_id, to_status, blocked_by?, note?)
```

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `ticket_id` | `str` | Yes | -- | Linear ticket ID (e.g., `DBC-87`). |
| `to_status` | `str` | Yes | -- | Target status: `"todo"`, `"in_progress"`, `"review"`, `"blocked"`, `"done"`. |
| `blocked_by` | `str \| None` | No | `None` | Blocker ticket ID. Required when `to_status` is `"blocked"`. |
| `note` | `str \| None` | No | `None` | Optional note about the transition. |

**Returns**: Dict with `transition_id` and `elapsed_time` (time spent in previous status).

---

### herd_review

Submit a code review for a PR.

```
herd_review(pr_number, ticket_id, verdict, findings)
```

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `pr_number` | `int` | Yes | -- | GitHub PR number. |
| `ticket_id` | `str` | Yes | -- | Associated Linear ticket ID. |
| `verdict` | `str` | Yes | -- | Review verdict: `"approve"`, `"request_changes"`, `"comment"`. |
| `findings` | `list[dict]` | Yes | -- | List of finding dicts (see below). |

Each finding dict contains:

| Key | Type | Description |
|---|---|---|
| `category` | `str` | Finding category (e.g., `"code-quality"`, `"security"`, `"testing"`). |
| `severity` | `str` | Finding severity (e.g., `"blocking"`, `"advisory"`). |
| `description` | `str` | Description of the finding. |
| `file_path` | `str` | File path where the finding applies. |
| `line_number` | `int` | Line number in the file. |

**Returns**: Dict with `review_id` and `posted` status.

---

### herd_metrics

Query operational metrics from the Herd database.

```
herd_metrics(query, period?, group_by?)
```

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | `str` | Yes | -- | Metric query (see below). |
| `period` | `str \| None` | No | `None` | Time period: `"today"`, `"this_week"`, `"this_sprint"`, `"last_30d"`, or ISO date range (e.g., `"2026-01-01..2026-02-01"`). |
| `group_by` | `str \| None` | No | `None` | Grouping: `"agent"`, `"model"`, `"ticket"`, `"category"`. |

Available queries:

| Query | Alias | Description |
|---|---|---|
| `cost_per_ticket` | `token_costs` | Token costs grouped by ticket |
| `review_effectiveness` | `review_stats` | QA review pass rates and finding patterns |
| `sprint_velocity` | `velocity` | Tickets completed per sprint |
| `agent_performance` | -- | Agent session metrics and outcomes |
| `model_efficiency` | -- | Cost and token usage by model |
| `pipeline_efficiency` | -- | Ticket flow and bottleneck analysis |
| `headline` | -- | Executive summary metrics |

**Returns**: Dict with `data` rows and `summary` statistics.

---

### herd_catchup

Get a summary of what happened since the agent was last active.

```
herd_catchup()
```

No parameters. Identity determined from `HERD_AGENT_NAME`.

**Returns**: Dict with `timestamp`, `slack_mentions`, `ticket_updates`, and `summary`.

---

### herd_harvest_tokens

Harvest token usage from Claude Code session files.

```
herd_harvest_tokens(agent_instance_code, project_path)
```

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `agent_instance_code` | `str` | Yes | -- | Agent instance identifier to attribute tokens to. |
| `project_path` | `str` | Yes | -- | Absolute path to the project directory containing session files. |

Parses JSONL session files, extracts token counts per model, calculates costs using `model_def` pricing, and writes records to the `agent_instance_token_activity` ledger.

**Returns**: Dict with `records_written` count and `total_cost` in USD.

---

### herd_record_decision

Record an agent decision to DuckDB and post to `#herd-decisions`.

```
herd_record_decision(decision_type, context, decision, rationale, alternatives_considered?, ticket_code?)
```

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `decision_type` | `str` | Yes | -- | Type of decision (e.g., `"architectural"`, `"implementation"`, `"pattern"`). |
| `context` | `str` | Yes | -- | Context/situation requiring the decision. |
| `decision` | `str` | Yes | -- | The decision made. |
| `rationale` | `str` | Yes | -- | Why this decision was made. |
| `alternatives_considered` | `str \| None` | No | `None` | Alternatives that were considered. |
| `ticket_code` | `str \| None` | No | `None` | Associated ticket code (e.g., `DBC-125`). |

Records the decision to the `herd.decision_record` table and posts a formatted summary to the `#herd-decisions` Slack channel.

**Returns**: Dict with `decision_id`, `posted_to_slack` boolean, and agent identity.

---

### herd_assume

Load agent identity with full context for zero-ceremony role assumption.

```
herd_assume(agent_name)
```

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `agent_name` | `str` | Yes | -- | Agent code (e.g., `"steve"`, `"mason"`, `"fresco"`). Accepts legacy names. |

Assembles a complete identity prompt from:
- Role file (`.herd/roles/<agent>.md`)
- Craft standards section (from `.herd/craft.md`)
- Project guidelines (`CLAUDE.md`)
- Current state (`STATUS.md`)
- Recent git log (last 10 commits)
- Assigned Linear tickets
- Pending handoffs (last 7 days)
- Recent HDRs (last 7 days)

**Returns**: Formatted prompt string with full agent context.

---

### herd_decommission

Permanently decommission an agent instance.

```
herd_decommission(agent_name)
```

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `agent_name` | `str` | Yes | -- | Agent instance to decommission. |

Sets the agent's status to permanently inactive. The agent cannot be reactivated after decommission.

**Returns**: Dict with `success` boolean and `message`.

---

### herd_standdown

Temporarily stand down an agent instance.

```
herd_standdown(agent_name)
```

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `agent_name` | `str` | Yes | -- | Agent instance to stand down. |

Sets the agent's status to temporarily inactive. The agent can be reactivated later.

**Returns**: Dict with `success` boolean and `message`.

## Identity Resolution

The server resolves agent identity through a two-step process:

1. **`HERD_AGENT_NAME`** environment variable maps to an **`agent_code`** in the `agent_def` table. This is the agent's permanent identity (e.g., `mason`, `wardenstein`). Legacy names (`grunt`, `pikasso`, `mini-mao`, `shakesquill`) are accepted and mapped to current names.

2. The **`agent_code`** maps to an **`agent_instance`** record. Each time an agent is spawned, a new instance is created with a unique `agent_instance_code`. If no active instance exists when a tool is called, the server creates one automatically.

The instance carries the specific configuration for that session: which model was used, which craft version was loaded, which ticket was assigned. All activity ledger entries are recorded against the instance, not the base agent definition.

## Content Path Resolution

The server uses `get_herd_content_path()` to locate `.herd/` content with a two-step fallback:

1. **Project root** `.herd/` -- project-specific overrides
2. **Package root** `.herd/` -- canonical defaults from herd-core install

This means consuming projects can override any role file, craft standard, or template by placing their own version in their project's `.herd/` directory.

## Troubleshooting

### Tools not appearing in Claude Code

1. Verify `.mcp.json` is valid JSON (use `python3 -m json.tool .mcp.json`).
2. Confirm `python3 -m herd_mcp` runs without errors.
3. Check Claude Code logs for MCP server startup errors.
4. Restart Claude Code to reload MCP server configuration.

### Identity not resolving

1. Confirm `HERD_AGENT_NAME` is set in the `env` block of `.mcp.json`.
2. Run `python3 scripts/seed_db.py` to ensure agent definitions exist in the database.
3. Verify the `HERD_AGENT_NAME` value matches an `agent_code` in `agent_def` (case-sensitive). Legacy names (`grunt`, `pikasso`, `mini-mao`, `shakesquill`) are accepted.

### Database errors

1. Confirm the `.herd/` directory exists.
2. Run `python3 scripts/seed_db.py` to initialize the schema and seed data.
3. Check file permissions on the database file (read/write required).
4. If the database is corrupted, delete `.herd/herddb.duckdb` and re-run the seed script.

### Slack posting fails (herd_log)

1. Confirm `HERD_SLACK_TOKEN` is set (either in `.env`, `.mcp.json` env block, or shell environment).
2. Verify the token starts with `xoxb-` and has `chat:write` scope.
3. Ensure the bot is invited to the target Slack channel.
4. Check network connectivity to `https://slack.com/api/`.

### REST API not starting (serve mode)

1. Check that `HERD_API_HOST` and `HERD_API_PORT` are not conflicting with other services.
2. Default port is `8420`. Override with `HERD_API_PORT` environment variable.
3. Verify `aiohttp` is installed (`pip install herd-core` includes it).
