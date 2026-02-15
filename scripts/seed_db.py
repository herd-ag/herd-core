#!/usr/bin/env python3
"""Seed the Herd database with agent definitions and model pricing.

This script parses existing .herd/roles/*.md files to populate agent_def,
and includes current model pricing data for model_def table.

Idempotent: Safe to run multiple times without creating duplicates.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add src to path so we can import herd_mcp
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from herd_mcp.db import connection


def seed_agent_def(conn) -> None:
    """Seed agent_def table with known agents.

    Args:
        conn: DuckDB connection.
    """
    # Define agents based on role files in .herd/roles/
    agents = [
        {
            "agent_code": "steve",
            "agent_role": "coordinator",
            "agent_status": "active",
            "agent_branch_prefix": "herd/steve",
            "agent_email": "steve@herd.local",
            "default_model_code": "claude-opus-4-6",
        },
        {
            "agent_code": "leonardo",
            "agent_role": "coordinator",
            "agent_status": "active",
            "agent_branch_prefix": "herd/leonardo",
            "agent_email": "leonardo@herd.local",
            "default_model_code": "claude-opus-4-6",
        },
        {
            "agent_code": "mason",
            "agent_role": "backend",
            "agent_status": "active",
            "agent_branch_prefix": "herd/mason",
            "agent_email": "mason@herd.local",
            "default_model_code": "claude-sonnet-4-5",
        },
        {
            "agent_code": "fresco",
            "agent_role": "frontend",
            "agent_status": "active",
            "agent_branch_prefix": "herd/fresco",
            "agent_email": "fresco@herd.local",
            "default_model_code": "claude-sonnet-4-5",
        },
        {
            "agent_code": "wardenstein",
            "agent_role": "qa",
            "agent_status": "active",
            "agent_branch_prefix": "herd/wardenstein",
            "agent_email": "wardenstein@herd.local",
            "default_model_code": "claude-opus-4-6",
        },
        {
            "agent_code": "scribe",
            "agent_role": "docs",
            "agent_status": "active",
            "agent_branch_prefix": "herd/scribe",
            "agent_email": "scribe@herd.local",
            "default_model_code": "claude-opus-4-6",
        },
        {
            "agent_code": "vigil",
            "agent_role": "qa-automated",
            "agent_status": "active",
            "agent_branch_prefix": "herd/vigil",
            "agent_email": "vigil@herd.local",
            "default_model_code": "claude-haiku-4-5",
        },
        {
            "agent_code": "rook",
            "agent_role": "mechanical",
            "agent_status": "active",
            "agent_branch_prefix": "herd/rook",
            "agent_email": "rook@herd.local",
            "default_model_code": "claude-haiku-4-5",
        },
    ]

    for agent in agents:
        # Check if agent already exists
        existing = conn.execute(
            "SELECT agent_code FROM herd.agent_def WHERE agent_code = ?",
            [agent["agent_code"]],
        ).fetchone()

        if existing:
            # Update if exists
            conn.execute(
                """
                UPDATE herd.agent_def
                SET agent_role = ?,
                    agent_status = ?,
                    agent_branch_prefix = ?,
                    agent_email = ?,
                    default_model_code = ?,
                    modified_at = CURRENT_TIMESTAMP
                WHERE agent_code = ?
                """,
                [
                    agent["agent_role"],
                    agent["agent_status"],
                    agent["agent_branch_prefix"],
                    agent["agent_email"],
                    agent["default_model_code"],
                    agent["agent_code"],
                ],
            )
            print(f"Updated agent_def: {agent['agent_code']}")
        else:
            # Insert new
            conn.execute(
                """
                INSERT INTO herd.agent_def
                  (agent_code, agent_role, agent_status, agent_branch_prefix,
                   agent_email, default_model_code, created_at, modified_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                [
                    agent["agent_code"],
                    agent["agent_role"],
                    agent["agent_status"],
                    agent["agent_branch_prefix"],
                    agent["agent_email"],
                    agent["default_model_code"],
                ],
            )
            print(f"Inserted agent_def: {agent['agent_code']}")


def seed_model_def(conn) -> None:
    """Seed model_def table with current Claude model pricing.

    Args:
        conn: DuckDB connection.

    Pricing as of 2026-02-09 (per million tokens):
    - Claude Opus 4.6: $15 input, $75 output, $1.50 cache read, $18.75 cache create
    - Claude Sonnet 4.5: $3 input, $15 output, $0.30 cache read, $3.75 cache create
    - Claude Sonnet 4: $3 input, $15 output, $0.30 cache read, $3.75 cache create
    - Claude Haiku 4: $0.80 input, $4 output, $0.08 cache read, $1 cache create
    """
    models = [
        {
            "model_code": "claude-opus-4-6",
            "model_provider": "anthropic",
            "model_context_window": 200000,
            "model_input_cost_per_m": 15.00,
            "model_output_cost_per_m": 75.00,
            "model_cache_read_cost_per_m": 1.50,
            "model_cache_create_cost_per_m": 18.75,
        },
        {
            "model_code": "claude-sonnet-4-5",
            "model_provider": "anthropic",
            "model_context_window": 200000,
            "model_input_cost_per_m": 3.00,
            "model_output_cost_per_m": 15.00,
            "model_cache_read_cost_per_m": 0.30,
            "model_cache_create_cost_per_m": 3.75,
        },
        {
            "model_code": "claude-sonnet-4",
            "model_provider": "anthropic",
            "model_context_window": 200000,
            "model_input_cost_per_m": 3.00,
            "model_output_cost_per_m": 15.00,
            "model_cache_read_cost_per_m": 0.30,
            "model_cache_create_cost_per_m": 3.75,
        },
        {
            "model_code": "claude-haiku-4",
            "model_provider": "anthropic",
            "model_context_window": 200000,
            "model_input_cost_per_m": 0.80,
            "model_output_cost_per_m": 4.00,
            "model_cache_read_cost_per_m": 0.08,
            "model_cache_create_cost_per_m": 1.00,
        },
    ]

    for model in models:
        # Check if model already exists
        existing = conn.execute(
            "SELECT model_code FROM herd.model_def WHERE model_code = ?",
            [model["model_code"]],
        ).fetchone()

        if existing:
            # Update if exists
            conn.execute(
                """
                UPDATE herd.model_def
                SET model_provider = ?,
                    model_context_window = ?,
                    model_input_cost_per_m = ?,
                    model_output_cost_per_m = ?,
                    model_cache_read_cost_per_m = ?,
                    model_cache_create_cost_per_m = ?,
                    modified_at = CURRENT_TIMESTAMP
                WHERE model_code = ?
                """,
                [
                    model["model_provider"],
                    model["model_context_window"],
                    model["model_input_cost_per_m"],
                    model["model_output_cost_per_m"],
                    model["model_cache_read_cost_per_m"],
                    model["model_cache_create_cost_per_m"],
                    model["model_code"],
                ],
            )
            print(f"Updated model_def: {model['model_code']}")
        else:
            # Insert new
            conn.execute(
                """
                INSERT INTO herd.model_def
                  (model_code, model_provider, model_context_window,
                   model_input_cost_per_m, model_output_cost_per_m,
                   model_cache_read_cost_per_m, model_cache_create_cost_per_m,
                   created_at, modified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """,
                [
                    model["model_code"],
                    model["model_provider"],
                    model["model_context_window"],
                    model["model_input_cost_per_m"],
                    model["model_output_cost_per_m"],
                    model["model_cache_read_cost_per_m"],
                    model["model_cache_create_cost_per_m"],
                ],
            )
            print(f"Inserted model_def: {model['model_code']}")


def main() -> None:
    """Main entry point for database seeding."""
    # Use environment variable if set, otherwise use default
    db_path = os.getenv("HERD_DB_PATH", ".herd/herddb.duckdb")

    print(f"Seeding Herd database: {db_path}")
    print("-" * 60)

    with connection(db_path) as conn:
        seed_agent_def(conn)
        print()
        seed_model_def(conn)

    print("-" * 60)
    print("Database seeding complete!")


if __name__ == "__main__":
    main()
