"""Token usage harvesting tool implementation.

Parses Claude Code JSONL session files to extract token usage, calculates costs
based on model pricing, and writes activity records to the token ledger.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from herd_mcp.db import connection

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry


def _find_project_session_dir(project_path: str) -> Path | None:
    """Locate the Claude Code session directory for a project path.

    Args:
        project_path: Absolute path to the project directory.

    Returns:
        Path to the session directory, or None if not found.
    """
    # Convert project path to Claude Code project hash
    # e.g., /Users/name/project -> -Users-name-project
    project_hash = project_path.replace(os.sep, "-")

    # Locate the session directory
    claude_projects = Path.home() / ".claude" / "projects"
    session_dir = claude_projects / project_hash

    return session_dir if session_dir.exists() else None


def _parse_jsonl_sessions(session_dir: Path) -> list[dict[str, Any]]:
    """Parse all JSONL session files in the directory.

    Args:
        session_dir: Path to Claude Code session directory.

    Returns:
        List of message records with usage data.
    """
    messages = []

    for jsonl_file in session_dir.glob("*.jsonl"):
        try:
            with open(jsonl_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        record = json.loads(line)

                        # Extract messages with usage data
                        if record.get("type") == "assistant" and "message" in record:
                            message = record["message"]
                            if "usage" in message and "model" in message:
                                messages.append(
                                    {
                                        "model": message["model"],
                                        "usage": message["usage"],
                                        "timestamp": record.get("timestamp"),
                                    }
                                )
                    except json.JSONDecodeError:
                        # Skip malformed lines
                        continue
        except Exception:
            # Skip files that can't be read
            continue

    return messages


def _aggregate_usage_by_model(
    messages: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """Aggregate token counts by model.

    Args:
        messages: List of message records with usage data.

    Returns:
        Dict mapping model_code to aggregated token counts.
    """
    aggregated = {}

    for msg in messages:
        model = msg["model"]
        usage = msg["usage"]

        if model not in aggregated:
            aggregated[model] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_tokens": 0,
                "cache_create_tokens": 0,
            }

        aggregated[model]["input_tokens"] += usage.get("input_tokens", 0)
        aggregated[model]["output_tokens"] += usage.get("output_tokens", 0)
        aggregated[model]["cache_read_tokens"] += usage.get(
            "cache_read_input_tokens", 0
        )
        aggregated[model]["cache_create_tokens"] += usage.get(
            "cache_creation_input_tokens", 0
        )

    return aggregated


def _calculate_cost(
    model_code: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_create_tokens: int,
) -> float:
    """Calculate total cost for token usage.

    Args:
        model_code: Model identifier.
        input_tokens: Input token count.
        output_tokens: Output token count.
        cache_read_tokens: Cache read token count.
        cache_create_tokens: Cache creation token count.

    Returns:
        Total cost in USD.
    """
    with connection() as conn:
        result = conn.execute(
            """
            SELECT
                model_input_cost_per_m,
                model_output_cost_per_m,
                model_cache_read_cost_per_m,
                model_cache_create_cost_per_m
            FROM herd.model_def
            WHERE model_code = ?
            LIMIT 1
            """,
            [model_code],
        ).fetchone()

        if not result:
            # Default to zero if model not found
            return 0.0

        (
            input_cost_per_m,
            output_cost_per_m,
            cache_read_cost_per_m,
            cache_create_cost_per_m,
        ) = result

    # Calculate cost (per million tokens)
    total_cost = 0.0
    if input_cost_per_m:
        total_cost += (input_tokens / 1_000_000) * float(input_cost_per_m)
    if output_cost_per_m:
        total_cost += (output_tokens / 1_000_000) * float(output_cost_per_m)
    if cache_read_cost_per_m:
        total_cost += (cache_read_tokens / 1_000_000) * float(cache_read_cost_per_m)
    if cache_create_cost_per_m:
        total_cost += (cache_create_tokens / 1_000_000) * float(cache_create_cost_per_m)

    return total_cost


def _write_token_activity(
    agent_instance_code: str, usage_data: dict[str, dict[str, int]]
) -> int:
    """Write token activity records to the database.

    Args:
        agent_instance_code: Agent instance identifier.
        usage_data: Dict mapping model_code to token counts.

    Returns:
        Number of records written.
    """
    records_written = 0

    with connection() as conn:
        for model_code, counts in usage_data.items():
            # Calculate cost
            cost = _calculate_cost(
                model_code,
                counts["input_tokens"],
                counts["output_tokens"],
                counts["cache_read_tokens"],
                counts["cache_create_tokens"],
            )

            # Insert activity record
            conn.execute(
                """
                INSERT INTO herd.agent_instance_token_activity
                  (agent_instance_code, model_code, token_input_count, token_output_count,
                   token_cache_read_count, token_cache_create_count, token_cost_usd,
                   token_context_utilization_pct, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, CURRENT_TIMESTAMP)
                """,
                [
                    agent_instance_code,
                    model_code,
                    counts["input_tokens"],
                    counts["output_tokens"],
                    counts["cache_read_tokens"],
                    counts["cache_create_tokens"],
                    cost,
                ],
            )

            records_written += 1

    return records_written


async def execute(
    agent_instance_code: str, project_path: str, registry: AdapterRegistry | None = None
) -> dict:
    """Harvest token usage from Claude Code session files.

    Parses JSONL session files, extracts token counts, calculates costs,
    and writes activity records to the token ledger.

    Args:
        agent_instance_code: Agent instance identifier.
        project_path: Absolute path to the project directory.
        registry: Optional adapter registry for dependency injection.

    Returns:
        Dict with harvest results including records written and total cost.
    """
    # NOTE: Token harvest tool will be wired by Grunt B in DBC-149.
    # This registry parameter is added for future wiring.
    # Find session directory
    session_dir = _find_project_session_dir(project_path)
    if not session_dir:
        return {
            "success": False,
            "error": f"Could not locate session directory for {project_path}",
            "records_written": 0,
        }

    # Parse JSONL files
    messages = _parse_jsonl_sessions(session_dir)
    if not messages:
        return {
            "success": True,
            "message": "No token usage data found in session files",
            "records_written": 0,
            "total_cost_usd": 0.0,
        }

    # Aggregate by model
    usage_data = _aggregate_usage_by_model(messages)

    # Write to database
    records_written = _write_token_activity(agent_instance_code, usage_data)

    # Calculate total cost
    total_cost = sum(
        _calculate_cost(
            model,
            counts["input_tokens"],
            counts["output_tokens"],
            counts["cache_read_tokens"],
            counts["cache_create_tokens"],
        )
        for model, counts in usage_data.items()
    )

    return {
        "success": True,
        "records_written": records_written,
        "total_cost_usd": round(total_cost, 6),
        "models_processed": list(usage_data.keys()),
        "session_directory": str(session_dir),
    }
