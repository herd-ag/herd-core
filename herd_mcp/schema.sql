-- Herd MCP Schema
-- DuckDB DDL for all 28 operational tables

CREATE SCHEMA IF NOT EXISTS herd;

-- ============================================================================
-- Entity Definitions (12 tables)
-- ============================================================================

CREATE TABLE IF NOT EXISTS herd.initiative_def (
    initiative_code TEXT PRIMARY KEY,
    initiative_title TEXT,
    initiative_description TEXT,
    initiative_status TEXT,
    created_at TIMESTAMP,
    modified_at TIMESTAMP,
    deleted_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.project_def (
    project_code TEXT PRIMARY KEY,
    initiative_code TEXT,
    project_title TEXT,
    project_description TEXT,
    project_status TEXT,
    created_at TIMESTAMP,
    modified_at TIMESTAMP,
    deleted_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.agent_def (
    agent_code TEXT PRIMARY KEY,
    agent_role TEXT,
    agent_status TEXT,
    agent_branch_prefix TEXT,
    agent_email TEXT,
    default_model_code TEXT,
    created_at TIMESTAMP,
    modified_at TIMESTAMP,
    deleted_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.model_def (
    model_code TEXT PRIMARY KEY,
    model_provider TEXT,
    model_context_window INTEGER,
    model_input_cost_per_m DECIMAL(18,6),
    model_output_cost_per_m DECIMAL(18,6),
    model_cache_read_cost_per_m DECIMAL(18,6),
    model_cache_create_cost_per_m DECIMAL(18,6),
    created_at TIMESTAMP,
    modified_at TIMESTAMP,
    deleted_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.craft_def (
    craft_code TEXT PRIMARY KEY,
    craft_description TEXT,
    created_at TIMESTAMP,
    modified_at TIMESTAMP,
    deleted_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.personality_def (
    personality_code TEXT PRIMARY KEY,
    personality_description TEXT,
    created_at TIMESTAMP,
    modified_at TIMESTAMP,
    deleted_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.skillset_def (
    skillset_code TEXT PRIMARY KEY,
    skillset_description TEXT,
    created_at TIMESTAMP,
    modified_at TIMESTAMP,
    deleted_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.sprint_def (
    sprint_code TEXT PRIMARY KEY,
    sprint_title TEXT,
    sprint_goal TEXT,
    sprint_started_at TIMESTAMP,
    sprint_planned_end_at TIMESTAMP,
    sprint_actual_end_at TIMESTAMP,
    created_at TIMESTAMP,
    modified_at TIMESTAMP,
    deleted_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.ticket_def (
    ticket_code TEXT PRIMARY KEY,
    project_code TEXT,
    ticket_title TEXT,
    ticket_description TEXT,
    ticket_tshirt_size TEXT,
    ticket_acceptance_criteria TEXT,
    ticket_current_status TEXT,
    current_sprint_code TEXT,
    created_at TIMESTAMP,
    modified_at TIMESTAMP,
    deleted_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.pr_def (
    pr_code TEXT PRIMARY KEY,
    ticket_code TEXT,
    creator_agent_instance_code TEXT,
    pr_branch_name TEXT,
    pr_title TEXT,
    pr_lines_added INTEGER,
    pr_lines_deleted INTEGER,
    pr_files_changed INTEGER,
    pr_merged_at TIMESTAMP,
    pr_closed_at TIMESTAMP,
    created_at TIMESTAMP,
    modified_at TIMESTAMP,
    deleted_at TIMESTAMP
);

-- IMMUTABLE tables (review_def, review_finding)
CREATE TABLE IF NOT EXISTS herd.review_def (
    review_code TEXT PRIMARY KEY,
    pr_code TEXT,
    reviewer_agent_instance_code TEXT,
    review_round INTEGER,
    review_verdict TEXT,
    review_duration_minutes DECIMAL(18,6),
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.review_finding (
    review_finding_code TEXT PRIMARY KEY,
    review_code TEXT,
    finding_category TEXT,
    finding_severity TEXT,
    finding_description TEXT,
    finding_file_path TEXT,
    finding_line_number INTEGER,
    finding_pattern_id TEXT,
    finding_outcome TEXT,
    created_at TIMESTAMP
);

-- ============================================================================
-- Versioned Content (3 tables — IMMUTABLE)
-- ============================================================================

CREATE TABLE IF NOT EXISTS herd.craft_version (
    craft_version_code TEXT PRIMARY KEY,
    craft_code TEXT,
    craft_version_content TEXT,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.personality_version (
    personality_version_code TEXT PRIMARY KEY,
    personality_code TEXT,
    personality_version_content TEXT,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.skillset_version (
    skillset_version_code TEXT PRIMARY KEY,
    skillset_code TEXT,
    skillset_version_content TEXT,
    created_at TIMESTAMP
);

-- ============================================================================
-- Skills (3 tables — individual fetchable skills that compose into skillsets)
-- ============================================================================

CREATE TABLE IF NOT EXISTS herd.skill_def (
    skill_code TEXT PRIMARY KEY,
    skill_description TEXT,
    skill_source_url TEXT,
    skill_source_type TEXT,
    created_at TIMESTAMP,
    modified_at TIMESTAMP,
    deleted_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.skill_version (
    skill_version_code TEXT PRIMARY KEY,
    skill_code TEXT,
    skill_version_content TEXT,
    skill_source_url TEXT,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.skill_skillset (
    skill_code TEXT,
    skillset_code TEXT,
    skill_order INTEGER,
    created_at TIMESTAMP,
    deleted_at TIMESTAMP,
    PRIMARY KEY (skill_code, skillset_code)
);

-- ============================================================================
-- Instance (1 table)
-- ============================================================================

CREATE TABLE IF NOT EXISTS herd.agent_instance (
    agent_instance_code TEXT PRIMARY KEY,
    agent_code TEXT,
    model_code TEXT,
    craft_version_code TEXT,
    personality_version_code TEXT,
    ticket_code TEXT,
    spawned_by_agent_instance_code TEXT,
    agent_instance_started_at TIMESTAMP,
    agent_instance_ended_at TIMESTAMP,
    agent_instance_outcome TEXT
);

-- ============================================================================
-- Junction (2 tables)
-- ============================================================================

CREATE TABLE IF NOT EXISTS herd.agent_skillset (
    agent_code TEXT,
    skillset_code TEXT,
    created_at TIMESTAMP,
    deleted_at TIMESTAMP,
    PRIMARY KEY (agent_code, skillset_code)
);

CREATE TABLE IF NOT EXISTS herd.agent_instance_skillset (
    agent_instance_code TEXT,
    skillset_version_code TEXT,
    PRIMARY KEY (agent_instance_code, skillset_version_code)
);

-- ============================================================================
-- Activity Ledgers (5 tables — INSERT-ONLY)
-- ============================================================================

CREATE TABLE IF NOT EXISTS herd.agent_instance_lifecycle_activity (
    agent_instance_code TEXT,
    lifecycle_event_type TEXT,
    lifecycle_detail TEXT,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.agent_instance_ticket_activity (
    agent_instance_code TEXT,
    ticket_code TEXT,
    ticket_event_type TEXT,
    ticket_status TEXT,
    sprint_code TEXT,
    blocker_ticket_code TEXT,
    blocker_description TEXT,
    handoff_to_agent_code TEXT,
    ticket_activity_comment TEXT,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.agent_instance_pr_activity (
    agent_instance_code TEXT,
    pr_code TEXT,
    pr_event_type TEXT,
    pr_commit_hash TEXT,
    pr_push_lines_added INTEGER,
    pr_push_lines_deleted INTEGER,
    pr_activity_detail TEXT,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.agent_instance_review_activity (
    agent_instance_code TEXT,
    review_code TEXT,
    pr_code TEXT,
    review_event_type TEXT,
    review_finding_code TEXT,
    review_activity_detail TEXT,
    created_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.agent_instance_token_activity (
    agent_instance_code TEXT,
    model_code TEXT,
    token_input_count INTEGER,
    token_output_count INTEGER,
    token_cache_read_count INTEGER,
    token_cache_create_count INTEGER,
    token_cost_usd DECIMAL(18,6),
    token_context_utilization_pct DECIMAL(18,6),
    created_at TIMESTAMP
);

-- ============================================================================
-- Reflexive Learning (2 tables — agent self-awareness and decision tracking)
-- ============================================================================

CREATE TABLE IF NOT EXISTS herd.agent_observation (
    observation_id TEXT PRIMARY KEY,
    agent_code TEXT,
    session_code TEXT,
    observation_type TEXT,
    observation_content TEXT,
    confidence FLOAT,
    created_at TIMESTAMP,
    deleted_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS herd.decision_record (
    decision_id TEXT PRIMARY KEY,
    decision_type TEXT,
    context TEXT,
    decision TEXT,
    rationale TEXT,
    alternatives_considered TEXT,
    decided_by TEXT,
    ticket_code TEXT,
    created_at TIMESTAMP,
    deleted_at TIMESTAMP
);
