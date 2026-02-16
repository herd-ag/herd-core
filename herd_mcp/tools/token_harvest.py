"""Token usage harvesting tool implementation.

Parses Claude Code JSONL session files to extract token usage, calculates costs
based on model pricing, and writes activity records to the token ledger.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from herd_core.types import ModelRecord, TokenEvent

if TYPE_CHECKING:
    from herd_core.adapters.store import StoreAdapter
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
    store: StoreAdapter,
    model_code: str,
    input_tokens: int,
    output_tokens: int,
) -> Decimal:
    """Calculate total cost for token usage using store for model pricing.

    Args:
        store: StoreAdapter instance for model pricing lookup.
        model_code: Model identifier.
        input_tokens: Input token count.
        output_tokens: Output token count.

    Returns:
        Total cost in USD as Decimal.
    """
    model_record = store.get(ModelRecord, model_code)

    if not model_record:
        # Default to zero if model not found
        return Decimal("0")

    total_cost = Decimal("0")
    if model_record.input_cost_per_token:
        total_cost += Decimal(str(input_tokens)) * model_record.input_cost_per_token
    if model_record.output_cost_per_token:
        total_cost += Decimal(str(output_tokens)) * model_record.output_cost_per_token

    return total_cost


def _write_token_activity(
    store: StoreAdapter,
    agent_instance_code: str,
    usage_data: dict[str, dict[str, int]],
) -> int:
    """Write token activity records to the store via TokenEvent append.

    Args:
        store: StoreAdapter instance.
        agent_instance_code: Agent instance identifier.
        usage_data: Dict mapping model_code to token counts.

    Returns:
        Number of records written.
    """
    records_written = 0

    for model_code, counts in usage_data.items():
        input_tokens = counts["input_tokens"]
        output_tokens = counts["output_tokens"]
        total_tokens = input_tokens + output_tokens

        # Calculate cost
        cost = _calculate_cost(store, model_code, input_tokens, output_tokens)

        # Append token event
        store.append(
            TokenEvent(
                entity_id=agent_instance_code,
                event_type="token_usage",
                instance_id=agent_instance_code,
                model=model_code,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                cost_usd=cost,
            )
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
    if not registry or not registry.store:
        return {"error": "StoreAdapter not configured"}

    store = registry.store

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

    # Write to store via token events
    async with registry.write_lock:
        records_written = _write_token_activity(store, agent_instance_code, usage_data)

    # Calculate total cost
    total_cost = sum(
        float(
            _calculate_cost(
                store,
                model,
                counts["input_tokens"],
                counts["output_tokens"],
            )
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
