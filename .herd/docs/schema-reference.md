# HerdDB Schema Reference

The Herd database uses DuckDB to store all operational data for agent activity tracking. The schema lives in the `herd` namespace and contains 28 tables organized into seven categories.

## Architecture Overview

The data pipeline follows a **medallion architecture** with three layers, implemented in dbt:

```
Bronze (Sources)          Silver (Staging + Vault)          Gold (Dimensions + Facts)
source.herd.yml    -->    dwsa/ (staging views)       -->   dm/ (SCD2 dims + facts)
                          dwh/ (Data Vault 2.0)
```

- **Bronze**: Raw source definitions in `models/bronze/source.herd.yml`. Points directly at the `herd` schema tables.
- **Silver**: Two sub-layers:
  - `dwsa/` (staging) -- 25 staging views that clean and type-cast source data.
  - `dwh/` (vault) -- Data Vault 2.0 models: hubs, links, and satellites.
- **Gold**: `dm/` -- Star schema with SCD Type 2 dimensions and fact tables, materialized to the `herd_dm` schema. Dashboards query this layer exclusively.

## Table Categories

### Entity Definitions (12 tables)

Mutable tables that store the current state of business entities. Support soft deletes via `deleted_at`. All carry `created_at` and `modified_at` timestamps.

#### herd.initiative_def

Top-level strategic initiatives that group projects.

| Column | Type | Description |
|---|---|---|
| `initiative_code` | `TEXT PK` | Unique initiative identifier. |
| `initiative_title` | `TEXT` | Human-readable title. |
| `initiative_description` | `TEXT` | Detailed description. |
| `initiative_status` | `TEXT` | Current status. |
| `created_at` | `TIMESTAMP` | Record creation time. |
| `modified_at` | `TIMESTAMP` | Last modification time. |
| `deleted_at` | `TIMESTAMP` | Soft delete timestamp. |

#### herd.project_def

Projects linked to initiatives. A project groups related tickets.

| Column | Type | Description |
|---|---|---|
| `project_code` | `TEXT PK` | Unique project identifier. |
| `initiative_code` | `TEXT` | Parent initiative. |
| `project_title` | `TEXT` | Human-readable title. |
| `project_description` | `TEXT` | Detailed description. |
| `project_status` | `TEXT` | Current status. |
| `created_at` | `TIMESTAMP` | Record creation time. |
| `modified_at` | `TIMESTAMP` | Last modification time. |
| `deleted_at` | `TIMESTAMP` | Soft delete timestamp. |

#### herd.agent_def

Agent definitions with roles and configuration.

| Column | Type | Description |
|---|---|---|
| `agent_code` | `TEXT PK` | Unique agent identifier (e.g., `mason`, `wardenstein`). |
| `agent_role` | `TEXT` | Agent role (e.g., `backend`, `qa`, `docs`). |
| `agent_status` | `TEXT` | Current status (e.g., `active`). |
| `agent_branch_prefix` | `TEXT` | Git branch prefix (e.g., `herd/mason`). |
| `agent_email` | `TEXT` | Agent email for commits. |
| `default_model_code` | `TEXT` | Default LLM model for this agent. |
| `created_at` | `TIMESTAMP` | Record creation time. |
| `modified_at` | `TIMESTAMP` | Last modification time. |
| `deleted_at` | `TIMESTAMP` | Soft delete timestamp. |

#### herd.model_def

LLM model definitions with per-million-token pricing.

| Column | Type | Description |
|---|---|---|
| `model_code` | `TEXT PK` | Model identifier (e.g., `claude-opus-4-6`). |
| `model_provider` | `TEXT` | Provider name (e.g., `anthropic`). |
| `model_context_window` | `INTEGER` | Maximum context window in tokens. |
| `model_input_cost_per_m` | `DECIMAL(18,6)` | Input cost per million tokens (USD). |
| `model_output_cost_per_m` | `DECIMAL(18,6)` | Output cost per million tokens (USD). |
| `model_cache_read_cost_per_m` | `DECIMAL(18,6)` | Cache read cost per million tokens (USD). |
| `model_cache_create_cost_per_m` | `DECIMAL(18,6)` | Cache creation cost per million tokens (USD). |
| `created_at` | `TIMESTAMP` | Record creation time. |
| `modified_at` | `TIMESTAMP` | Last modification time. |
| `deleted_at` | `TIMESTAMP` | Soft delete timestamp. |

#### herd.craft_def

Craft standard definitions. A craft is a set of quality standards for a specific discipline.

| Column | Type | Description |
|---|---|---|
| `craft_code` | `TEXT PK` | Unique craft identifier. |
| `craft_description` | `TEXT` | Description of the craft standard. |
| `created_at` | `TIMESTAMP` | Record creation time. |
| `modified_at` | `TIMESTAMP` | Last modification time. |
| `deleted_at` | `TIMESTAMP` | Soft delete timestamp. |

#### herd.personality_def

Agent personality definitions that control tone and behavior.

| Column | Type | Description |
|---|---|---|
| `personality_code` | `TEXT PK` | Unique personality identifier. |
| `personality_description` | `TEXT` | Description of the personality profile. |
| `created_at` | `TIMESTAMP` | Record creation time. |
| `modified_at` | `TIMESTAMP` | Last modification time. |
| `deleted_at` | `TIMESTAMP` | Soft delete timestamp. |

#### herd.skillset_def

Skillset definitions. A skillset is a collection of individual skills.

| Column | Type | Description |
|---|---|---|
| `skillset_code` | `TEXT PK` | Unique skillset identifier. |
| `skillset_description` | `TEXT` | Description of the skillset. |
| `created_at` | `TIMESTAMP` | Record creation time. |
| `modified_at` | `TIMESTAMP` | Last modification time. |
| `deleted_at` | `TIMESTAMP` | Soft delete timestamp. |

#### herd.sprint_def

Sprint definitions with goals and timelines.

| Column | Type | Description |
|---|---|---|
| `sprint_code` | `TEXT PK` | Unique sprint identifier. |
| `sprint_title` | `TEXT` | Sprint title. |
| `sprint_goal` | `TEXT` | Sprint goal description. |
| `sprint_started_at` | `TIMESTAMP` | Sprint start time. |
| `sprint_planned_end_at` | `TIMESTAMP` | Planned end time. |
| `sprint_actual_end_at` | `TIMESTAMP` | Actual end time (`NULL` if still active). |
| `created_at` | `TIMESTAMP` | Record creation time. |
| `modified_at` | `TIMESTAMP` | Last modification time. |
| `deleted_at` | `TIMESTAMP` | Soft delete timestamp. |

#### herd.ticket_def

Ticket definitions with status tracking and metadata.

| Column | Type | Description |
|---|---|---|
| `ticket_code` | `TEXT PK` | Unique ticket identifier (e.g., `DBC-87`). |
| `project_code` | `TEXT` | Parent project. |
| `ticket_title` | `TEXT` | Ticket title. |
| `ticket_description` | `TEXT` | Full description. |
| `ticket_tshirt_size` | `TEXT` | Estimated size: `XS`, `S`, `M`, `L`, `XL`. |
| `ticket_acceptance_criteria` | `TEXT` | Acceptance criteria. |
| `ticket_current_status` | `TEXT` | Current status. |
| `current_sprint_code` | `TEXT` | Sprint this ticket belongs to. |
| `created_at` | `TIMESTAMP` | Record creation time. |
| `modified_at` | `TIMESTAMP` | Last modification time. |
| `deleted_at` | `TIMESTAMP` | Soft delete timestamp. |

#### herd.pr_def

Pull request definitions with code change metrics.

| Column | Type | Description |
|---|---|---|
| `pr_code` | `TEXT PK` | Unique PR identifier. |
| `ticket_code` | `TEXT` | Associated ticket. |
| `creator_agent_instance_code` | `TEXT` | Agent instance that created the PR. |
| `pr_branch_name` | `TEXT` | Git branch name. |
| `pr_title` | `TEXT` | PR title. |
| `pr_lines_added` | `INTEGER` | Lines added. |
| `pr_lines_deleted` | `INTEGER` | Lines deleted. |
| `pr_files_changed` | `INTEGER` | Files changed. |
| `pr_merged_at` | `TIMESTAMP` | Merge timestamp. |
| `pr_closed_at` | `TIMESTAMP` | Close timestamp (if closed without merge). |
| `created_at` | `TIMESTAMP` | Record creation time. |
| `modified_at` | `TIMESTAMP` | Last modification time. |
| `deleted_at` | `TIMESTAMP` | Soft delete timestamp. |

#### herd.review_def

Code review definitions. **Immutable** -- records are never updated after creation.

| Column | Type | Description |
|---|---|---|
| `review_code` | `TEXT PK` | Unique review identifier. |
| `pr_code` | `TEXT` | Reviewed PR. |
| `reviewer_agent_instance_code` | `TEXT` | Agent instance that performed the review. |
| `review_round` | `INTEGER` | Review round number (1 = first pass). |
| `review_verdict` | `TEXT` | Verdict: `approved`, `request_changes`, `comment`. |
| `review_duration_minutes` | `DECIMAL(18,6)` | Time spent on the review. |
| `created_at` | `TIMESTAMP` | Record creation time. |

#### herd.review_finding

Individual findings from code reviews. **Immutable**.

| Column | Type | Description |
|---|---|---|
| `review_finding_code` | `TEXT PK` | Unique finding identifier. |
| `review_code` | `TEXT` | Parent review. |
| `finding_category` | `TEXT` | Category (e.g., `code-quality`, `security`). |
| `finding_severity` | `TEXT` | Severity: `blocking`, `advisory`. |
| `finding_description` | `TEXT` | Description of the finding. |
| `finding_file_path` | `TEXT` | File path where the finding applies. |
| `finding_line_number` | `INTEGER` | Line number in the file. |
| `finding_pattern_id` | `TEXT` | Pattern identifier for recurring issues. |
| `finding_outcome` | `TEXT` | Resolution outcome. |
| `created_at` | `TIMESTAMP` | Record creation time. |

---

### Versioned Content (3 tables)

**Immutable** tables that store content-addressable versions of agent configuration artifacts. Each version is a snapshot; new versions are appended, never updated.

#### herd.craft_version

| Column | Type | Description |
|---|---|---|
| `craft_version_code` | `TEXT PK` | Content-addressable version identifier. |
| `craft_code` | `TEXT` | Parent craft definition. |
| `craft_version_content` | `TEXT` | Full text content of this version. |
| `created_at` | `TIMESTAMP` | Version creation time. |

#### herd.personality_version

| Column | Type | Description |
|---|---|---|
| `personality_version_code` | `TEXT PK` | Content-addressable version identifier. |
| `personality_code` | `TEXT` | Parent personality definition. |
| `personality_version_content` | `TEXT` | Full text content of this version. |
| `created_at` | `TIMESTAMP` | Version creation time. |

#### herd.skillset_version

| Column | Type | Description |
|---|---|---|
| `skillset_version_code` | `TEXT PK` | Content-addressable version identifier. |
| `skillset_code` | `TEXT` | Parent skillset definition. |
| `skillset_version_content` | `TEXT` | Full text content of this version. |
| `created_at` | `TIMESTAMP` | Version creation time. |

---

### Skills (3 tables)

Individual fetchable skills that compose into skillsets. Skills can be sourced from external repositories.

#### herd.skill_def

| Column | Type | Description |
|---|---|---|
| `skill_code` | `TEXT PK` | Unique skill identifier. |
| `skill_description` | `TEXT` | Description of the skill. |
| `skill_source_url` | `TEXT` | URL to fetch skill content from. |
| `skill_source_type` | `TEXT` | Source type (e.g., `github`, `local`). |
| `created_at` | `TIMESTAMP` | Record creation time. |
| `modified_at` | `TIMESTAMP` | Last modification time. |
| `deleted_at` | `TIMESTAMP` | Soft delete timestamp. |

#### herd.skill_version

**Immutable**. Versioned snapshots of skill content.

| Column | Type | Description |
|---|---|---|
| `skill_version_code` | `TEXT PK` | Content-addressable version identifier. |
| `skill_code` | `TEXT` | Parent skill definition. |
| `skill_version_content` | `TEXT` | Full text content of this version. |
| `skill_source_url` | `TEXT` | Source URL at time of fetch. |
| `created_at` | `TIMESTAMP` | Version creation time. |

#### herd.skill_skillset

Junction table linking skills to skillsets with ordering.

| Column | Type | Description |
|---|---|---|
| `skill_code` | `TEXT PK` | Skill identifier. |
| `skillset_code` | `TEXT PK` | Skillset identifier. |
| `skill_order` | `INTEGER` | Order of the skill within the skillset. |
| `created_at` | `TIMESTAMP` | Record creation time. |
| `deleted_at` | `TIMESTAMP` | Soft delete timestamp. |

---

### Instance (1 table)

#### herd.agent_instance

Each row represents a single agent execution session. Links the base agent definition to a specific model, craft version, personality version, and ticket assignment.

| Column | Type | Description |
|---|---|---|
| `agent_instance_code` | `TEXT PK` | Unique instance identifier. |
| `agent_code` | `TEXT` | Base agent definition. |
| `model_code` | `TEXT` | LLM model used for this session. |
| `craft_version_code` | `TEXT` | Craft version loaded. |
| `personality_version_code` | `TEXT` | Personality version loaded. |
| `ticket_code` | `TEXT` | Assigned ticket. |
| `spawned_by_agent_instance_code` | `TEXT` | Instance that spawned this one. |
| `agent_instance_started_at` | `TIMESTAMP` | Session start time. |
| `agent_instance_ended_at` | `TIMESTAMP` | Session end time. |
| `agent_instance_outcome` | `TEXT` | Session outcome (e.g., `success`, `failure`). |

---

### Junctions (2 tables)

#### herd.agent_skillset

Links agents to their assigned skillsets.

| Column | Type | Description |
|---|---|---|
| `agent_code` | `TEXT PK` | Agent identifier. |
| `skillset_code` | `TEXT PK` | Skillset identifier. |
| `created_at` | `TIMESTAMP` | Assignment time. |
| `deleted_at` | `TIMESTAMP` | Soft delete timestamp. |

#### herd.agent_instance_skillset

Links agent instances to specific skillset versions loaded for that session.

| Column | Type | Description |
|---|---|---|
| `agent_instance_code` | `TEXT PK` | Agent instance identifier. |
| `skillset_version_code` | `TEXT PK` | Skillset version loaded. |

---

### Activity Ledgers (5 tables)

**Insert-only** append ledgers. Records are never updated or deleted. These tables capture the full event history of all agent operations.

#### herd.agent_instance_lifecycle_activity

Agent lifecycle events (spawn, standdown, decommission).

| Column | Type | Description |
|---|---|---|
| `agent_instance_code` | `TEXT` | Agent instance. |
| `lifecycle_event_type` | `TEXT` | Event type (e.g., `spawned`, `stood_down`, `decommissioned`). |
| `lifecycle_detail` | `TEXT` | Additional detail about the event. |
| `created_at` | `TIMESTAMP` | Event timestamp. |

#### herd.agent_instance_ticket_activity

Ticket-related events: assignment, status transitions, handoffs.

| Column | Type | Description |
|---|---|---|
| `agent_instance_code` | `TEXT` | Agent instance. |
| `ticket_code` | `TEXT` | Ticket being acted on. |
| `ticket_event_type` | `TEXT` | Event type (e.g., `assigned`, `transitioned`, `blocked`). |
| `ticket_status` | `TEXT` | New ticket status. |
| `sprint_code` | `TEXT` | Associated sprint. |
| `blocker_ticket_code` | `TEXT` | Blocking ticket (if blocked). |
| `blocker_description` | `TEXT` | Description of the blocker. |
| `handoff_to_agent_code` | `TEXT` | Agent receiving handoff (if applicable). |
| `ticket_activity_comment` | `TEXT` | Comment about the activity. |
| `created_at` | `TIMESTAMP` | Event timestamp. |

#### herd.agent_instance_pr_activity

PR-related events: creation, push, merge, close.

| Column | Type | Description |
|---|---|---|
| `agent_instance_code` | `TEXT` | Agent instance. |
| `pr_code` | `TEXT` | PR being acted on. |
| `pr_event_type` | `TEXT` | Event type (e.g., `created`, `pushed`, `merged`). |
| `pr_commit_hash` | `TEXT` | Commit hash for push events. |
| `pr_push_lines_added` | `INTEGER` | Lines added in this push. |
| `pr_push_lines_deleted` | `INTEGER` | Lines deleted in this push. |
| `pr_activity_detail` | `TEXT` | Additional detail. |
| `created_at` | `TIMESTAMP` | Event timestamp. |

#### herd.agent_instance_review_activity

Review-related events: submission, finding creation.

| Column | Type | Description |
|---|---|---|
| `agent_instance_code` | `TEXT` | Agent instance. |
| `review_code` | `TEXT` | Associated review. |
| `pr_code` | `TEXT` | Reviewed PR. |
| `review_event_type` | `TEXT` | Event type (e.g., `submitted`, `finding_created`). |
| `review_finding_code` | `TEXT` | Associated finding (if applicable). |
| `review_activity_detail` | `TEXT` | Additional detail. |
| `created_at` | `TIMESTAMP` | Event timestamp. |

#### herd.agent_instance_token_activity

Token usage and cost tracking per agent instance.

| Column | Type | Description |
|---|---|---|
| `agent_instance_code` | `TEXT` | Agent instance. |
| `model_code` | `TEXT` | LLM model used. |
| `token_input_count` | `INTEGER` | Input tokens consumed. |
| `token_output_count` | `INTEGER` | Output tokens generated. |
| `token_cache_read_count` | `INTEGER` | Tokens served from cache. |
| `token_cache_create_count` | `INTEGER` | Tokens written to cache. |
| `token_cost_usd` | `DECIMAL(18,6)` | Calculated cost in USD. |
| `token_context_utilization_pct` | `DECIMAL(18,6)` | Percentage of context window used. |
| `created_at` | `TIMESTAMP` | Event timestamp. |

---

### Reflexive Learning (2 tables)

Tables for agent self-awareness and decision tracking.

#### herd.agent_observation

Agent-generated observations about patterns, risks, and improvements.

| Column | Type | Description |
|---|---|---|
| `observation_id` | `TEXT PK` | Unique observation identifier. |
| `agent_code` | `TEXT` | Observing agent. |
| `session_code` | `TEXT` | Session during which the observation was made. |
| `observation_type` | `TEXT` | Type of observation. |
| `observation_content` | `TEXT` | Observation text. |
| `confidence` | `FLOAT` | Confidence score (0.0 to 1.0). |
| `created_at` | `TIMESTAMP` | Observation timestamp. |
| `deleted_at` | `TIMESTAMP` | Soft delete timestamp. |

#### herd.decision_record

Architectural and operational decision records (lightweight ADRs).

| Column | Type | Description |
|---|---|---|
| `decision_id` | `TEXT PK` | Unique decision identifier. |
| `decision_type` | `TEXT` | Type of decision. |
| `context` | `TEXT` | Context that prompted the decision. |
| `decision` | `TEXT` | The decision made. |
| `rationale` | `TEXT` | Reasoning behind the decision. |
| `alternatives_considered` | `TEXT` | Other options that were evaluated. |
| `decided_by` | `TEXT` | Who made the decision. |
| `ticket_code` | `TEXT` | Associated ticket (if applicable). |
| `created_at` | `TIMESTAMP` | Decision timestamp. |
| `deleted_at` | `TIMESTAMP` | Soft delete timestamp. |

---

## Data Vault Layer (Silver)

The Data Vault 2.0 layer in `models/silver/dwh/` transforms staging data into a historized, auditable structure.

### Hubs (14 tables)

Hubs store unique business keys. Each hub has a surrogate hash key and `load_ts`.

| Hub | Source Table | Business Key |
|---|---|---|
| `h_agent` | `agent_def` | `agent_code` |
| `h_craft` | `craft_def` | `craft_code` |
| `h_decision` | `decision_record` | `decision_id` |
| `h_initiative` | `initiative_def` | `initiative_code` |
| `h_model` | `model_def` | `model_code` |
| `h_observation` | `agent_observation` | `observation_id` |
| `h_personality` | `personality_def` | `personality_code` |
| `h_project` | `project_def` | `project_code` |
| `h_pull_request` | `pr_def` | `pr_code` |
| `h_review` | `review_def` | `review_code` |
| `h_skill` | `skill_def` | `skill_code` |
| `h_skillset` | `skillset_def` | `skillset_code` |
| `h_sprint` | `sprint_def` | `sprint_code` |
| `h_ticket` | `ticket_def` | `ticket_code` |

### Links (7 tables)

Links capture relationships between hubs. Non-historized links (`l_`) are for static relationships; non-historized links (`ln_`) track transactional relationships.

| Link | Relationship |
|---|---|
| `l_agent_craft` | Agent to craft assignment |
| `l_agent_personality` | Agent to personality assignment |
| `l_agent_skillset` | Agent to skillset assignment |
| `l_skill_skillset` | Skill to skillset membership |
| `ln_agent_instance` | Agent instance to agent, model, craft, personality |
| `ln_pr_submission` | PR to ticket and creator agent instance |
| `ln_review_submission` | Review to PR and reviewer agent instance |

### Satellites (18 tables)

Satellites store descriptive attributes and change history. Standard satellites (`s_`) track entity attributes; non-historized satellites (`sn_`) store event data from activity ledgers.

| Satellite | Description |
|---|---|
| `s_agent_base` | Agent role, status, branch prefix, email, model |
| `s_craft_base` | Craft description |
| `s_craft_version` | Craft version content snapshots |
| `s_decision_base` | Decision type, context, rationale, alternatives |
| `s_initiative_base` | Initiative title, description, status |
| `s_model_base` | Model provider, context window, pricing |
| `s_observation_base` | Observation type, content, confidence |
| `s_personality_base` | Personality description |
| `s_personality_version` | Personality version content snapshots |
| `s_project_base` | Project title, description, status |
| `s_pull_request_base` | PR branch, title, lines, merge/close timestamps |
| `s_review_base` | Review round, verdict, duration |
| `s_skill_base` | Skill description, source URL, source type |
| `s_skill_version` | Skill version content snapshots |
| `s_sprint_base` | Sprint title, goal, start/end dates |
| `s_ticket_base` | Ticket title, description, size, status, sprint |
| `sn_agent_instance_lifecycle` | Lifecycle events (from activity ledger) |
| `sn_agent_instance_pr` | PR events (from activity ledger) |
| `sn_agent_instance_review` | Review events (from activity ledger) |
| `sn_agent_instance_ticket` | Ticket events (from activity ledger) |
| `sn_agent_instance_token` | Token usage events (from activity ledger) |
| `sn_review_finding` | Review finding details |

---

## Gold Layer (Mart Models)

The gold layer produces the final star schema consumed by dashboards. All models materialize to the `herd_dm` schema.

### Dimensions (13 tables)

SCD Type 2 dimensions with `valid_from`, `valid_to`, `is_current`, and `is_deleted` columns.

| Model | Description |
|---|---|
| `dim_agent` | Agent code, role, status, branch prefix, email, default model |
| `dim_agent_observation` | Agent observations with type, content, confidence |
| `dim_craft` | Craft code and description |
| `dim_date` | Date dimension with `date_sk` (YYYYMMDD integer), calendar attributes |
| `dim_decision_record` | Decision type, context, rationale, alternatives, decided_by |
| `dim_initiative` | Initiative title, description, status |
| `dim_model` | Model code, provider, context window, pricing |
| `dim_personality` | Personality code and description |
| `dim_project` | Project code, title, description, status, initiative |
| `dim_pull_request` | PR code, ticket, branch, title, lines, files, merge/close times |
| `dim_skillset` | Skillset code and description |
| `dim_sprint` | Sprint code, title, goal, start/end dates |
| `dim_ticket` | Ticket code, project, title, size, status, sprint |

### Facts (6 tables)

Fact tables aggregate activity data and link to dimension surrogate keys.

| Model | Description |
|---|---|
| `fact_agent_instance_cost` | Token usage and cost aggregated per agent instance. Measures: input/output/cache tokens, total cost USD. |
| `fact_agent_instance_work` | Agent session activity. Measures: duration minutes, lifecycle/ticket/PR event counts, outcome. |
| `fact_pr_delivery` | PR delivery metrics. Measures: lines added/deleted, files changed, merge timestamp. |
| `fact_review_quality` | Review quality metrics. Measures: round, verdict, finding counts (blocking/advisory), duration. |
| `fact_sprint_burndown` | Sprint burndown events. Measures: ticket status transitions over time. |
| `fact_ticket_lifecycle` | Ticket state transitions. Measures: time in previous status, blocker info, handoff details. |
