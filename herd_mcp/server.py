"""MCP server setup and tool registration for Herd operations."""

from __future__ import annotations

import logging
import os

from mcp.server.fastmcp import FastMCP

from .adapters import AdapterRegistry

# Import all tool modules
from .tools import (
    assign,
    assume_role,
    catchup,
    lifecycle,
    log,
    metrics,
    record_decision,
    review,
    spawn,
    status,
    token_harvest,
    transition,
)

logger = logging.getLogger(__name__)

# Initialize FastMCP server
mcp = FastMCP("herd")

# Global adapter registry (initialized on first access)
_registry: AdapterRegistry | None = None


def get_adapter_registry() -> AdapterRegistry:
    """Get or create the global adapter registry.

    Attempts to import and instantiate concrete adapter implementations.
    Falls back gracefully if adapters are not installed.

    Returns:
        AdapterRegistry instance with available adapters.
    """
    global _registry

    if _registry is not None:
        return _registry

    registry = AdapterRegistry()

    # Try to instantiate NotifyAdapter (Slack)
    try:
        from herd_notify_slack import SlackNotifyAdapter

        slack_token = os.getenv("HERD_SLACK_TOKEN")
        if slack_token:
            registry.notify = SlackNotifyAdapter(token=slack_token)
            logger.info("Initialized SlackNotifyAdapter")
        else:
            logger.warning("HERD_SLACK_TOKEN not set, NotifyAdapter unavailable")
    except ImportError:
        logger.info(
            "herd-notify-slack not installed, using fallback Slack implementation"
        )

    # Try to instantiate TicketAdapter (Linear)
    try:
        from herd_ticket_linear import LinearTicketAdapter

        linear_token = os.getenv("LINEAR_API_KEY")
        if linear_token:
            registry.tickets = LinearTicketAdapter(api_key=linear_token)
            logger.info("Initialized LinearTicketAdapter")
        else:
            logger.warning("LINEAR_API_KEY not set, TicketAdapter unavailable")
    except ImportError:
        logger.info(
            "herd-ticket-linear not installed, using fallback Linear implementation"
        )

    # Try to instantiate StoreAdapter (DuckDB)
    try:
        from herd_store_duckdb import DuckDBStoreAdapter

        db_path = os.getenv("HERD_DB_PATH", ".herd/herddb.duckdb")
        registry.store = DuckDBStoreAdapter(path=db_path)
        logger.info("Initialized DuckDBStoreAdapter")
    except ImportError:
        logger.info(
            "herd-store-duckdb not installed, using fallback DuckDB implementation"
        )
    except Exception as e:
        logger.warning(f"Failed to initialize DuckDBStoreAdapter: {e}")

    # Try to instantiate RepoAdapter (GitHub)
    try:
        from herd_repo_github import GitHubRepoAdapter

        repo_root = os.getenv("HERD_REPO_PATH", ".")
        registry.repo = GitHubRepoAdapter(repo_root=repo_root)
        logger.info("Initialized GitHubRepoAdapter")
    except ImportError:
        logger.info("herd-repo-github not installed, using fallback Git implementation")
    except Exception as e:
        logger.warning(f"Failed to initialize GitHubRepoAdapter: {e}")

    # Try to instantiate AgentAdapter (Claude)
    try:
        from herd_agent_claude import ClaudeAgentAdapter

        registry.agent = ClaudeAgentAdapter()
        logger.info("Initialized ClaudeAgentAdapter")
    except ImportError:
        logger.info(
            "herd-agent-claude not installed, using fallback spawn implementation"
        )
    except Exception as e:
        logger.warning(f"Failed to initialize ClaudeAgentAdapter: {e}")

    _registry = registry
    return registry


def get_agent_identity() -> str | None:
    """Get the current agent identity from environment.

    Returns:
        Agent name from HERD_AGENT_NAME environment variable, or None.
    """
    return os.getenv("HERD_AGENT_NAME")


# Register all tools
@mcp.tool()
async def herd_log(
    message: str,
    channel: str | None = None,
    await_response: bool = False,
) -> dict:
    """Post a message to Slack and log the activity.

    Args:
        message: Message content to post.
        channel: Optional Slack channel (defaults to #herd-feed).
        await_response: If True, wait for and return any thread responses.

    Returns:
        Dict with posted timestamp, event_id, and optional responses.
    """
    agent_name = get_agent_identity()
    registry = get_adapter_registry()
    return await log.execute(message, channel, await_response, agent_name, registry)


@mcp.tool()
async def herd_status(scope: str = "all") -> dict:
    """Get current status of Herd agents, sprint, and blockers.

    Args:
        scope: Status scope - "all", "agents", "sprint", or "blockers".

    Returns:
        Dict with agents status, sprint info, and blocker list.
    """
    agent_name = get_agent_identity()
    registry = get_adapter_registry()
    return await status.execute(scope, agent_name, registry)


@mcp.tool()
async def herd_spawn(
    count: int,
    role: str,
    model: str | None = None,
) -> dict:
    """Spawn new agent instances.

    Args:
        count: Number of agents to spawn.
        role: Agent role or code (accepts both "grunt" and "backend", "pikasso" and "frontend", etc.).
        model: Optional model override (uses role default if not specified).

    Returns:
        Dict with list of spawned agent instance codes.
    """
    agent_name = get_agent_identity()
    registry = get_adapter_registry()
    return await spawn.execute(count, role, model, agent_name, registry=registry)


@mcp.tool()
async def herd_assign(
    ticket_id: str,
    agent_name: str | None = None,
    priority: str = "normal",
) -> dict:
    """Assign a ticket to an agent.

    Args:
        ticket_id: Linear ticket ID (e.g., DBC-87).
        agent_name: Agent to assign to (uses current agent if None).
        priority: Assignment priority - "normal", "high", or "urgent".

    Returns:
        Dict with assignment confirmation, agent, and ticket details.
    """
    current_agent = get_agent_identity()
    registry = get_adapter_registry()
    return await assign.execute(
        ticket_id, agent_name or current_agent, priority, registry
    )


@mcp.tool()
async def herd_transition(
    ticket_id: str,
    to_status: str,
    blocked_by: str | None = None,
    note: str | None = None,
) -> dict:
    """Transition a ticket to a new status.

    Args:
        ticket_id: Linear ticket ID (e.g., DBC-87).
        to_status: Target status (todo, in_progress, review, blocked, done).
        blocked_by: Optional blocker ticket ID if status is "blocked".
        note: Optional note about the transition.

    Returns:
        Dict with transition_id and elapsed time in previous status.
    """
    agent_name = get_agent_identity()
    registry = get_adapter_registry()
    return await transition.execute(
        ticket_id, to_status, blocked_by, note, agent_name, registry
    )


@mcp.tool()
async def herd_review(
    pr_number: int,
    ticket_id: str,
    verdict: str,
    findings: list[dict],
) -> dict:
    """Submit a code review for a PR.

    Args:
        pr_number: GitHub PR number.
        ticket_id: Associated Linear ticket ID.
        verdict: Review verdict - "approve", "request_changes", or "comment".
        findings: List of finding dicts with category, severity, description, file_path, line_number.

    Returns:
        Dict with review_id and posted status.
    """
    agent_name = get_agent_identity()
    registry = get_adapter_registry()
    return await review.execute(
        pr_number, ticket_id, verdict, findings, agent_name, registry
    )


@mcp.tool()
async def herd_metrics(
    query: str,
    period: str | None = None,
    group_by: str | None = None,
) -> dict:
    """Query operational metrics from the Herd database.

    Args:
        query: Metric query - "cost_per_ticket" (alias: "token_costs"),
               "review_effectiveness" (alias: "review_stats"),
               "sprint_velocity" (alias: "velocity"),
               "agent_performance", "model_efficiency", "pipeline_efficiency", "headline".
        period: Optional time period - "today", "this_week", "this_sprint", "last_30d",
                or ISO date range (e.g., "2026-01-01..2026-02-01").
        group_by: Optional grouping - "agent", "model", "ticket", "category".

    Returns:
        Dict with data rows and summary statistics.
    """
    agent_name = get_agent_identity()
    registry = get_adapter_registry()
    return await metrics.execute(query, period, group_by, agent_name, registry)


@mcp.tool()
async def herd_catchup() -> dict:
    """Get a summary of what happened since agent was last active.

    Returns:
        Dict with timestamp, slack mentions, ticket updates, and summary.
    """
    agent_name = get_agent_identity()
    registry = get_adapter_registry()
    return await catchup.execute(agent_name, registry)


@mcp.tool()
async def herd_decommission(agent_name: str) -> dict:
    """Permanently decommission an agent instance.

    Args:
        agent_name: Agent instance to decommission.

    Returns:
        Dict with success status and message.
    """
    current_agent = get_agent_identity()
    registry = get_adapter_registry()
    return await lifecycle.decommission(agent_name, current_agent, registry)


@mcp.tool()
async def herd_standdown(agent_name: str) -> dict:
    """Temporarily stand down an agent instance.

    Args:
        agent_name: Agent instance to stand down.

    Returns:
        Dict with success status and message.
    """
    current_agent = get_agent_identity()
    registry = get_adapter_registry()
    return await lifecycle.standdown(agent_name, current_agent, registry)


@mcp.tool()
async def herd_harvest_tokens(agent_instance_code: str, project_path: str) -> dict:
    """Harvest token usage from Claude Code session files.

    Parses JSONL session files for a project, extracts token counts, calculates costs
    based on model pricing, and writes activity records to the token ledger.

    Args:
        agent_instance_code: Agent instance identifier to attribute tokens to.
        project_path: Absolute path to the project directory.

    Returns:
        Dict with harvest results including records written and total cost.
    """
    registry = get_adapter_registry()
    return await token_harvest.execute(agent_instance_code, project_path, registry)


@mcp.tool()
async def herd_record_decision(
    decision_type: str,
    context: str,
    decision: str,
    rationale: str,
    alternatives_considered: str | None = None,
    ticket_code: str | None = None,
) -> dict:
    """Record an agent decision to DuckDB and post to #herd-decisions.

    This enables cross-agent learning and Architect oversight. Use this when making
    any implementation decisions (architectural choices, design trade-offs, pattern
    selections, etc.).

    Args:
        decision_type: Type of decision (architectural, implementation, pattern, etc).
        context: Context/situation requiring the decision.
        decision: The decision made.
        rationale: Why this decision was made.
        alternatives_considered: Optional alternatives that were considered.
        ticket_code: Optional associated ticket code (e.g., DBC-125).

    Returns:
        Dict with decision_id, posted status, and Slack response.
    """
    agent_name = get_agent_identity()
    registry = get_adapter_registry()
    return await record_decision.execute(
        decision_type,
        context,
        decision,
        rationale,
        alternatives_considered,
        ticket_code,
        agent_name,
        registry,
    )


@mcp.tool()
async def herd_assume(agent_name: str) -> str:
    """Assume a herd agent identity with full context.

    Assembles role file, craft standards, project guidelines, current state,
    git log, Linear tickets, handoffs, and recent HDRs into a complete
    identity prompt.

    Args:
        agent_name: Agent code (e.g., steve, mason, fresco).

    Returns:
        Full identity prompt for the specified agent.
    """
    registry = get_adapter_registry()
    return await assume_role.execute(agent_name, registry)
