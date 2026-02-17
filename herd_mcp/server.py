"""MCP server setup and tool registration for Herd operations."""

from __future__ import annotations

import importlib.metadata
import logging
import os
import subprocess
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path

from typing import TYPE_CHECKING

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from .adapters import AdapterRegistry
from .bus import CheckinRegistry, MessageBus

if TYPE_CHECKING:
    from .auth import HerdOAuthProvider

# Import all tool modules
from .tools import (
    assign,
    assume_role,
    catchup,
    checkin,
    create_ticket,
    get_messages,
    graph,
    lifecycle,
    list_tickets,
    log,
    metrics,
    recall,
    record_decision,
    review,
    spawn,
    status,
    token_harvest,
    transition,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conditional OAuth setup (HDR-0040: GitHub OAuth for public exposure)
# ---------------------------------------------------------------------------

_github_client_id = os.getenv("HERD_OAUTH_GITHUB_CLIENT_ID")
_oauth_provider: "HerdOAuthProvider | None" = None

if _github_client_id:
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions

    from .auth import HerdOAuthProvider

    _allowed_users_raw = os.getenv("HERD_ALLOWED_GITHUB_USERS", "")
    _allowed_users = [u.strip() for u in _allowed_users_raw.split(",") if u.strip()]
    _public_url = os.getenv("HERD_PUBLIC_URL", "https://herd-mcp.eriksen.live")

    _oauth_provider = HerdOAuthProvider(
        github_client_id=_github_client_id,
        github_client_secret=os.getenv("HERD_OAUTH_GITHUB_CLIENT_SECRET", ""),
        allowed_users=_allowed_users,
        public_url=_public_url,
        static_token=os.getenv("HERD_API_TOKEN", ""),
    )

    mcp = FastMCP(
        "herd",
        host=os.getenv("HERD_API_HOST", "0.0.0.0"),
        port=int(os.getenv("HERD_API_PORT", "8420")),
        stateless_http=True,
        auth_server_provider=_oauth_provider,
        auth=AuthSettings(
            issuer_url=_public_url,  # type: ignore[arg-type]
            # resource_server_url intentionally None — server serves both
            # internal (http://metropolis:8420) and public (https://herd-mcp.
            # eriksen.live) clients. A static URL causes mismatch for one side.
            # When None, /.well-known/oauth-protected-resource is not served,
            # avoiding the mismatch. The real OAuth blocker is Cloudflare's
            # "Block AI training bots" rule, not resource metadata.
            resource_server_url=None,
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=["herd:advisor"],
                default_scopes=["herd:advisor"],
            ),
            required_scopes=["herd:advisor"],
        ),
    )
    logger.info(
        "OAuth mode enabled: GitHub client %s, allowed users: %s",
        _github_client_id[:8],
        _allowed_users,
    )
else:
    mcp = FastMCP(
        "herd",
        host=os.getenv("HERD_API_HOST", "0.0.0.0"),
        port=int(os.getenv("HERD_API_PORT", "8420")),
        stateless_http=True,
    )

# ---------------------------------------------------------------------------
# Tool-level authorization for OAuth sessions (HDR-0040)
# ---------------------------------------------------------------------------
# When OAuth mode is active, all requests come from advisor sessions.
# Only ADVISOR_TOOLS are visible and callable. Agent-only tools are blocked.
# This does NOT affect non-OAuth mode (local/agent deployments).

if _oauth_provider is not None:
    from mcp import types as _mcp_types

    from .auth import ADVISOR_TOOLS as _ADVISOR_TOOLS
    from .auth import is_internal_session as _is_internal_session

    _original_list_tools_handler = mcp._mcp_server.request_handlers[
        _mcp_types.ListToolsRequest
    ]
    _original_call_tool_handler = mcp._mcp_server.request_handlers[
        _mcp_types.CallToolRequest
    ]

    async def _filtered_list_tools_handler(
        req: _mcp_types.ListToolsRequest,
    ) -> _mcp_types.ServerResult:
        """Filter tool listing for advisor sessions; internal gets all tools."""
        if _is_internal_session.get(False):
            return await _original_list_tools_handler(req)
        result = await _original_list_tools_handler(req)
        if isinstance(result, _mcp_types.ServerResult) and isinstance(
            result.root, _mcp_types.ListToolsResult
        ):
            filtered = [t for t in result.root.tools if t.name in _ADVISOR_TOOLS]
            return _mcp_types.ServerResult(_mcp_types.ListToolsResult(tools=filtered))
        return result

    async def _gated_call_tool_handler(
        req: _mcp_types.CallToolRequest,
    ) -> _mcp_types.ServerResult:
        """Block non-advisor tools for OAuth sessions; internal gets full access."""
        if _is_internal_session.get(False):
            return await _original_call_tool_handler(req)
        tool_name = req.params.name
        if tool_name not in _ADVISOR_TOOLS:
            logger.warning("OAuth session attempted blocked tool: %s", tool_name)
            return _mcp_types.ServerResult(
                _mcp_types.CallToolResult(
                    content=[
                        _mcp_types.TextContent(
                            type="text",
                            text=(
                                f"Access denied: tool '{tool_name}' is not "
                                f"available to advisor sessions. "
                                f"Available tools: "
                                f"{', '.join(sorted(_ADVISOR_TOOLS))}"
                            ),
                        )
                    ],
                    isError=True,
                )
            )
        return await _original_call_tool_handler(req)

    mcp._mcp_server.request_handlers[_mcp_types.ListToolsRequest] = (
        _filtered_list_tools_handler
    )
    mcp._mcp_server.request_handlers[_mcp_types.CallToolRequest] = (
        _gated_call_tool_handler
    )

    logger.info(
        "Tool authorization active: %d of %d tools exposed to advisors",
        len(_ADVISOR_TOOLS),
        len(mcp._tool_manager.list_tools()),
    )

# Global message bus (in-memory hot cache + DiskCache persistence)
bus = MessageBus()

# Global checkin registry (in-memory, tracks agent heartbeats)
checkin_registry = CheckinRegistry()

# Global adapter registry (initialized on first access)
_registry: AdapterRegistry | None = None

# Server start time - captured at module import
_SERVER_START_TIME: str = datetime.now(timezone.utc).isoformat()

# Running git commit - captured at module import
try:
    _RUNNING_COMMIT: str = (
        subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        )
        .decode()
        .strip()
    )
except Exception:
    _RUNNING_COMMIT = "unknown"


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
        from herd_notify_slack import SlackNotifyAdapter  # type: ignore[import-untyped]

        slack_token = os.getenv("HERD_NOTIFY_SLACK_TOKEN")
        if slack_token:
            registry.notify = SlackNotifyAdapter(token=slack_token)
            logger.info("Initialized SlackNotifyAdapter")
        else:
            logger.warning("HERD_NOTIFY_SLACK_TOKEN not set, NotifyAdapter unavailable")
    except ImportError:
        logger.info(
            "herd-notify-slack not installed, using fallback Slack implementation"
        )

    # Try to instantiate TicketAdapter (Linear)
    try:
        from herd_ticket_linear import LinearTicketAdapter  # type: ignore[import-untyped]

        linear_token = os.getenv("HERD_TICKET_LINEAR_API_KEY")
        linear_team_id = os.getenv("HERD_TICKET_LINEAR_TEAM_ID", "")
        if linear_token:
            registry.tickets = LinearTicketAdapter(
                api_key=linear_token, team_id=linear_team_id
            )
            logger.info("Initialized LinearTicketAdapter")
        else:
            logger.warning(
                "HERD_TICKET_LINEAR_API_KEY not set, TicketAdapter unavailable"
            )
    except ImportError:
        logger.info(
            "herd-ticket-linear not installed, using fallback Linear implementation"
        )

    # Try to instantiate StoreAdapter (DuckDB)
    try:
        from herd_store_duckdb import DuckDBStoreAdapter  # type: ignore[import-untyped]

        db_path = os.getenv("HERD_STORE_DUCKDB_PATH", ".herd/herddb.duckdb")
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
        from herd_repo_github import GitHubRepoAdapter  # type: ignore[import-untyped]

        repo_root = os.getenv("HERD_REPO_GITHUB_PATH", ".")
        registry.repo = GitHubRepoAdapter(repo_root=repo_root)
        logger.info("Initialized GitHubRepoAdapter")
    except ImportError:
        logger.info("herd-repo-github not installed, using fallback Git implementation")
    except Exception as e:
        logger.warning(f"Failed to initialize GitHubRepoAdapter: {e}")

    # Try to instantiate AgentAdapter (Claude)
    try:
        from herd_agent_claude import ClaudeAgentAdapter  # type: ignore[import-untyped]

        agent_repo_root = os.getenv("HERD_REPO_GITHUB_PATH", ".")
        registry.agent = ClaudeAgentAdapter(repo_root=agent_repo_root)
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
    agent_name: str | None = None,
) -> dict:
    """Post a message to Slack and log the activity.

    Args:
        message: Message content to post.
        channel: Optional Slack channel (defaults to #herd-feed).
        await_response: If True, wait for and return any thread responses.
        agent_name: Calling agent identity (falls back to HERD_AGENT_NAME).

    Returns:
        Dict with posted timestamp, event_id, and optional responses.
    """
    agent_name = agent_name or get_agent_identity()
    registry = get_adapter_registry()
    return await log.execute(message, channel, await_response, agent_name, registry)


@mcp.tool()
async def herd_status(scope: str = "all", agent_name: str | None = None) -> dict:
    """Get current status of Herd agents, sprint, and blockers.

    Args:
        scope: Status scope - "all", "agents", "sprint", or "blockers".
        agent_name: Calling agent identity (falls back to HERD_AGENT_NAME).

    Returns:
        Dict with agents status, sprint info, and blocker list.
    """
    agent_name = agent_name or get_agent_identity()
    registry = get_adapter_registry()
    return await status.execute(scope, agent_name, registry)


@mcp.tool()
async def herd_spawn(
    count: int,
    role: str,
    model: str | None = None,
    agent_name: str | None = None,
) -> dict:
    """Spawn new agent instances.

    Args:
        count: Number of agents to spawn.
        role: Agent role or code (accepts both "grunt" and "backend", "pikasso" and "frontend", etc.).
        model: Optional model override (uses role default if not specified).
        agent_name: Calling agent identity (falls back to HERD_AGENT_NAME).

    Returns:
        Dict with list of spawned agent instance codes.
    """
    agent_name = agent_name or get_agent_identity()
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
    resolved_agent = agent_name or current_agent
    registry = get_adapter_registry()
    return await assign.execute(ticket_id, resolved_agent, priority, registry)


@mcp.tool()
async def herd_transition(
    ticket_id: str,
    to_status: str,
    blocked_by: str | None = None,
    note: str | None = None,
    agent_name: str | None = None,
) -> dict:
    """Transition a ticket to a new status.

    Args:
        ticket_id: Linear ticket ID (e.g., DBC-87).
        to_status: Target status (todo, in_progress, review, blocked, done).
        blocked_by: Optional blocker ticket ID if status is "blocked".
        note: Optional note about the transition.
        agent_name: Calling agent identity (falls back to HERD_AGENT_NAME).

    Returns:
        Dict with transition_id and elapsed time in previous status.
    """
    agent_name = agent_name or get_agent_identity()
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
    agent_name: str | None = None,
) -> dict:
    """Submit a code review for a PR.

    Args:
        pr_number: GitHub PR number.
        ticket_id: Associated Linear ticket ID.
        verdict: Review verdict - "approve", "request_changes", or "comment".
        findings: List of finding dicts with category, severity, description, file_path, line_number.
        agent_name: Calling agent identity (falls back to HERD_AGENT_NAME).

    Returns:
        Dict with review_id and posted status.
    """
    agent_name = agent_name or get_agent_identity()
    registry = get_adapter_registry()
    return await review.execute(
        pr_number, ticket_id, verdict, findings, agent_name, registry
    )


@mcp.tool()
async def herd_metrics(
    query: str,
    period: str | None = None,
    group_by: str | None = None,
    agent_name: str | None = None,
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
        agent_name: Calling agent identity (falls back to HERD_AGENT_NAME).

    Returns:
        Dict with data rows and summary statistics.
    """
    agent_name = agent_name or get_agent_identity()
    registry = get_adapter_registry()
    return await metrics.execute(query, period, group_by, agent_name, registry)


@mcp.tool()
async def herd_catchup(agent_name: str | None = None) -> dict:
    """Get a summary of what happened since agent was last active.

    Args:
        agent_name: Calling agent identity (falls back to HERD_AGENT_NAME).

    Returns:
        Dict with timestamp, slack mentions, ticket updates, and summary.
    """
    agent_name = agent_name or get_agent_identity()
    registry = get_adapter_registry()
    return await catchup.execute(agent_name, registry, bus=bus)


@mcp.tool()
async def herd_decommission(agent_name: str, caller_agent: str | None = None) -> dict:
    """Permanently decommission an agent instance.

    Args:
        agent_name: Agent instance to decommission.
        caller_agent: Identity of the requesting agent (falls back to HERD_AGENT_NAME).

    Returns:
        Dict with success status and message.
    """
    caller = caller_agent or get_agent_identity()
    registry = get_adapter_registry()
    return await lifecycle.decommission(agent_name, caller, registry)


@mcp.tool()
async def herd_standdown(agent_name: str, caller_agent: str | None = None) -> dict:
    """Temporarily stand down an agent instance.

    Args:
        agent_name: Agent instance to stand down.
        caller_agent: Identity of the requesting agent (falls back to HERD_AGENT_NAME).

    Returns:
        Dict with success status and message.
    """
    caller = caller_agent or get_agent_identity()
    registry = get_adapter_registry()
    return await lifecycle.standdown(agent_name, caller, registry)


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
    agent_name: str | None = None,
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
        agent_name: Calling agent identity (falls back to HERD_AGENT_NAME).

    Returns:
        Dict with decision_id, posted status, and Slack response.
    """
    agent_name = agent_name or get_agent_identity()
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


@mcp.tool()
async def herd_recall(
    query: str,
    limit: int = 5,
    project: str | None = None,
    agent: str | None = None,
    memory_type: str | None = None,
    repo: str | None = None,
    org: str | None = None,
    team: str | None = None,
    host: str | None = None,
) -> dict:
    """Search semantic memory for relevant cross-session context.

    Formulate queries as conceptual descriptions, not keywords.
    "How we handle configuration across repos" retrieves better than "config".

    Args:
        query: Natural language query describing what context you need.
        limit: Maximum number of results to return (default 5).
        project: Filter by project (e.g., "herd", "dbt-conceptual").
        agent: Filter by agent name (e.g., "steve", "mason").
        memory_type: Filter by type — one of: session_summary, decision_context,
                     pattern, preference, thread.
        repo: Filter by repository name.
        org: Filter by organization scope.
        team: Filter by team scope.
        host: Filter by host/machine scope.

    Returns:
        Dict with matching memories ranked by semantic similarity.
    """
    return await recall.execute(
        query, limit, project, agent, memory_type, repo, org, team, host
    )


@mcp.tool()
async def herd_remember(
    content: str,
    memory_type: str,
    project: str = "herd",
    repo: str | None = None,
    org: str | None = None,
    team: str | None = None,
    host: str | None = None,
    session_id: str | None = None,
    metadata: dict | None = None,
    agent_name: str | None = None,
) -> dict:
    """Store a memory in the semantic memory system for cross-session recall.

    Use this to persist learnings, patterns, preferences, session summaries,
    and decision context so they can be recalled in future sessions.

    Args:
        content: Descriptive text to store. Should be self-contained —
                 this is what gets embedded and searched later.
        memory_type: One of: session_summary, decision_context, pattern,
                     preference, thread.
        project: Project identifier (default "herd").
        repo: Optional repository name (null for cross-repo memories).
        org: Optional organization scope. Falls back to HERD_ORG env var.
        team: Optional team scope. Falls back to HERD_TEAM env var.
        host: Optional host/machine scope. Falls back to HERD_HOST env var.
        session_id: Optional session identifier. Auto-generated if not provided.
        metadata: Optional dict of flexible metadata (hdr_number, ticket_id,
                  principle, etc.).
        agent_name: Calling agent identity (falls back to HERD_AGENT_NAME).

    Returns:
        Dict with success status and the stored memory ID.
    """
    agent_name = agent_name or get_agent_identity()
    org = org or os.getenv("HERD_ORG", "")
    team = team or os.getenv("HERD_TEAM", "")
    host_val = host or os.getenv("HERD_HOST", "")
    return await recall.store(
        content,
        memory_type,
        project,
        agent_name,
        repo,
        org,
        team,
        host_val,
        session_id,
        metadata,
    )


@mcp.tool()
async def herd_graph(
    query: str,
    params: dict | None = None,
) -> dict:
    """Query the structural graph store using Cypher.

    Executes a Cypher query against the KuzuDB graph database, which tracks
    relationships between agents, decisions, tickets, files, repositories,
    sessions, and concepts.

    Args:
        query: Cypher query string (e.g., "MATCH (a:Agent)-[:Decides]->(d:Decision)
               RETURN a.code, d.title").
        params: Optional dict of query parameters (referenced as $name in Cypher).

    Returns:
        Dict with 'results' (list of row dicts) and 'count' on success,
        or 'error' (str) on failure.
    """
    registry = get_adapter_registry()
    return await graph.execute(query, params, registry)


@mcp.tool()
async def herd_send(
    to: str,
    message: str,
    type: str = "inform",
    priority: str = "normal",
    agent_name: str | None = None,
) -> dict:
    """Send a message to an agent, team, or broadcast.

    Args:
        to: Recipient address (mason@avalon, @anyone, @everyone@leonardo, etc.).
        message: Message body.
        type: Message type — "directive", "inform", or "flag".
        priority: "normal" or "urgent".
        agent_name: Sender identity (auto-resolved from env if not provided).

    Returns:
        Dict with message_id and delivery status.
    """
    sender = agent_name or get_agent_identity() or "unknown"
    instance_id = os.getenv("HERD_INSTANCE_ID", "")
    team = os.getenv("HERD_TEAM", "")

    # Build sender address
    from_parts = sender
    if instance_id:
        from_parts = f"{sender}.{instance_id}"
    if team:
        from_parts = f"{from_parts}@{team}"

    msg = await bus.send(from_parts, to, message, msg_type=type, priority=priority)

    return {
        "message_id": msg.id,
        "delivered": True,
        "type": type,
        "priority": priority,
    }


@mcp.tool()
async def herd_checkin(
    status: str,
    agent_name: str | None = None,
) -> dict:
    """Check in with the Herd — report status, receive messages and context.

    Call at natural transition points during work: phase completions, before
    commits, when blocked, before completion. Returns pending messages and
    a context pane showing relevant Herd activity.

    Args:
        status: Brief status update (what you just did / plan to do next).
        agent_name: Calling agent identity (falls back to HERD_AGENT_NAME).

    Returns:
        Dict with messages (list), context (str or null), and heartbeat_ack.
    """
    agent_name = agent_name or get_agent_identity()
    registry = get_adapter_registry()
    return await checkin.execute(
        status, agent_name, registry, bus=bus, checkin_registry=checkin_registry
    )


@mcp.tool()
async def herd_get_messages(
    agent_name: str | None = None,
) -> dict:
    """Read pending messages from the message bus for the calling agent.

    Pure inbox drain — no heartbeat, no context pane. Messages are consumed
    on read (removed from the bus). Mechanical agents (rook, vigil) only
    receive directive-type messages.

    Args:
        agent_name: Calling agent identity (falls back to HERD_AGENT_NAME).

    Returns:
        Dict with agent identity, list of message dicts, and count.
    """
    agent_name = agent_name or get_agent_identity()
    return await get_messages.execute(agent_name, bus=bus)


@mcp.tool()
async def herd_create_ticket(
    title: str,
    description: str | None = None,
    priority: str | None = None,
    labels: list[str] | None = None,
    agent_name: str | None = None,
) -> dict:
    """Create a new ticket in the project management system.

    Creates a ticket via the TicketAdapter (e.g., Linear) and saves it to the
    local store for tracking.

    Args:
        title: Ticket title (required).
        description: Optional ticket description.
        priority: Optional priority level - "none", "urgent", "high", "normal", or "low".
        labels: Optional list of label IDs.
        agent_name: Calling agent identity (falls back to HERD_AGENT_NAME).

    Returns:
        Dict with created ticket identifier and details.
    """
    agent_name = agent_name or get_agent_identity()
    registry = get_adapter_registry()
    return await create_ticket.execute(
        title, description, priority, labels, agent_name, registry
    )


@mcp.tool()
async def herd_list_tickets(
    status: str | None = None,
    assignee: str | None = None,
    agent_name: str | None = None,
) -> dict:
    """List open/active tickets from the project management system.

    Queries Linear via the TicketAdapter to return tickets matching the filters.

    Args:
        status: Optional status filter (e.g., "backlog", "todo", "in_progress").
        assignee: Optional assignee filter (agent name or user ID).
        agent_name: Calling agent identity (falls back to HERD_AGENT_NAME).

    Returns:
        Dict with list of tickets (id, title, status, priority, assignee) and count.
    """
    agent_name = agent_name or get_agent_identity()
    registry = get_adapter_registry()
    return await list_tickets.execute(status, assignee, agent_name, registry)


# ---------------------------------------------------------------------------
# Health check (unauthenticated by design via custom_route)
# ---------------------------------------------------------------------------


def _dir_size_and_mtime(dir_path: str) -> tuple[int, str]:
    """Compute total size and most-recent mtime for a directory tree.

    Walks every file under *dir_path*, sums their sizes, and tracks the
    latest modification time.  Symbolic links are followed.

    Args:
        dir_path: Absolute or relative path to the directory.

    Returns:
        Tuple of (total_size_bytes, iso8601_utc_last_modified).

    Raises:
        FileNotFoundError: If *dir_path* does not exist.
    """
    total_size = 0
    latest_mtime = 0.0

    for root, _dirs, files in os.walk(dir_path):
        for name in files:
            fp = os.path.join(root, name)
            try:
                stat = os.stat(fp)
                total_size += stat.st_size
                if stat.st_mtime > latest_mtime:
                    latest_mtime = stat.st_mtime
            except OSError:
                # Skip files that vanish between walk and stat.
                continue

    iso_mtime = (
        datetime.fromtimestamp(latest_mtime, tz=timezone.utc).isoformat()
        if latest_mtime > 0
        else ""
    )
    return total_size, iso_mtime


def _file_size_and_mtime(file_path: str) -> tuple[int, str]:
    """Return size and mtime for a single file.

    Args:
        file_path: Absolute or relative path to the file.

    Returns:
        Tuple of (size_bytes, iso8601_utc_last_modified).

    Raises:
        FileNotFoundError: If *file_path* does not exist.
    """
    stat = os.stat(file_path)
    iso_mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    return stat.st_size, iso_mtime


def _package_meta_for_object(obj: object) -> tuple[str, str]:
    """Resolve the installed distribution name and version for *obj*.

    Uses ``importlib.metadata.packages_distributions()`` to map the
    top-level import package to its distribution, then reads the version.

    Args:
        obj: Any Python object whose ``__class__.__module__`` identifies
             its origin package.

    Returns:
        Tuple of (distribution_name, version).  Both fall back to
        ``"unknown"`` when metadata resolution fails (e.g. editable
        installs that lack dist-info).
    """
    unknown = ("unknown", "unknown")
    try:
        module = type(obj).__module__
        if not module:
            return unknown
        top_level = module.split(".")[0]

        pkg_map = importlib.metadata.packages_distributions()
        dist_names = pkg_map.get(top_level)
        if not dist_names:
            return unknown

        dist_name = dist_names[0]
        version = importlib.metadata.version(dist_name)
        return dist_name, version
    except Exception:
        return unknown


def _check_store_status() -> dict[str, dict[str, object]]:
    """Check availability and filesystem metadata of each embedded store.

    Returns a dict keyed by store name.  Each value is a dict with at
    least ``status`` (``"ok"`` | ``"unavailable"``), and when available:
    ``path``, ``size_bytes``, ``last_modified``.

    Returns:
        Dict mapping store name to enriched status dict.
    """
    stores: dict[str, dict[str, object]] = {}

    # --- DuckDB (single file) -----------------------------------------
    try:
        registry = get_adapter_registry()
        if registry.store is not None:
            info = registry.store.storage_info()
            stores["duckdb"] = {**info, "status": "ok"}
        else:
            stores["duckdb"] = {"status": "unavailable"}
    except Exception:
        stores["duckdb"] = {"status": "unavailable"}

    # --- LanceDB (directory) ------------------------------------------
    try:
        from .memory import get_lance_path, get_memory_store

        get_memory_store()
        lance_path = get_lance_path()
        entry: dict[str, object] = {"status": "ok", "path": lance_path}
        try:
            if Path(lance_path).is_dir():
                size, mtime = _dir_size_and_mtime(lance_path)
            else:
                size, mtime = _file_size_and_mtime(lance_path)
            entry["size_bytes"] = size
            entry["last_modified"] = mtime
        except FileNotFoundError:
            entry["size_bytes"] = 0
            entry["last_modified"] = ""
        stores["lancedb"] = entry
    except Exception:
        stores["lancedb"] = {"status": "unavailable"}

    # --- KuzuDB (directory) -------------------------------------------
    try:
        from .graph import get_graph_path, is_available

        if is_available():
            kuzu_path = get_graph_path()
            kuzu_entry: dict[str, object] = {"status": "ok", "path": kuzu_path}
            try:
                if Path(kuzu_path).is_dir():
                    size, mtime = _dir_size_and_mtime(kuzu_path)
                else:
                    size, mtime = _file_size_and_mtime(kuzu_path)
                kuzu_entry["size_bytes"] = size
                kuzu_entry["last_modified"] = mtime
            except FileNotFoundError:
                kuzu_entry["size_bytes"] = 0
                kuzu_entry["last_modified"] = ""
            stores["kuzudb"] = kuzu_entry
        else:
            stores["kuzudb"] = {"status": "unavailable"}
    except Exception:
        stores["kuzudb"] = {"status": "unavailable"}

    return stores


def _adapter_info(adapter: object | None) -> dict[str, str]:
    """Build an enriched status dict for a single adapter.

    Args:
        adapter: The adapter instance, or ``None`` if not installed.

    Returns:
        Dict with ``status``, ``package``, and ``version``.
    """
    if adapter is None:
        return {"status": "unavailable", "package": "unknown", "version": "unknown"}

    pkg, ver = _package_meta_for_object(adapter)
    return {"status": "ok", "package": pkg, "version": ver}


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check with enriched adapter and store metadata.

    Returns JSON with top-level ``status``, ``version``, per-adapter
    package/version info, and per-store path/size/mtime data.
    """
    try:
        registry = get_adapter_registry()
        adapters = {
            "store": _adapter_info(registry.store),
            "notify": _adapter_info(registry.notify),
            "tickets": _adapter_info(registry.tickets),
            "repo": _adapter_info(registry.repo),
            "agent": _adapter_info(registry.agent),
        }
    except Exception:
        unavailable = {
            "status": "unavailable",
            "package": "unknown",
            "version": "unknown",
        }
        adapters = {
            "store": unavailable,
            "notify": unavailable,
            "tickets": unavailable,
            "repo": unavailable,
            "agent": unavailable,
        }

    stores = _check_store_status()

    return JSONResponse(
        {
            "status": "ok",
            "server_start_time": _SERVER_START_TIME,
            "running_commit": _RUNNING_COMMIT,
            "version": "0.2.0",
            "adapters": adapters,
            "stores": stores,
        }
    )


# ---------------------------------------------------------------------------
# GitHub OAuth callback route (HDR-0040)
# ---------------------------------------------------------------------------


@mcp.custom_route("/github/callback", methods=["GET"])
async def github_callback(request: Request) -> Response:
    """Handle the GitHub OAuth callback after user authorization.

    GitHub redirects here after the user approves access. This endpoint
    exchanges the GitHub code for a token, verifies the user is in the
    allowed list, issues an MCP authorization code, and redirects back
    to the client's redirect_uri.

    This route is unauthenticated (registered via custom_route).
    """
    if _oauth_provider is None:
        return JSONResponse({"error": "OAuth not configured"}, status_code=500)

    code = request.query_params.get("code")
    state = request.query_params.get("state")

    if not code or not state:
        return JSONResponse(
            {"error": "Missing code or state parameter"}, status_code=400
        )

    redirect_url, error = await _oauth_provider.handle_github_callback(code, state)

    if redirect_url is None:
        return JSONResponse({"error": error}, status_code=403)

    return RedirectResponse(url=redirect_url, status_code=302)


# ---------------------------------------------------------------------------
# Auth debug + bearer token middleware + HTTP app factory
# ---------------------------------------------------------------------------


class _AuthDebugMiddleware(BaseHTTPMiddleware):
    """Temporary debug middleware to log incoming auth headers.

    Logs whether an Authorization header is present on /mcp requests
    before FastMCP's auth middleware processes them. Helps diagnose
    cases where a reverse proxy (e.g., Cloudflare) strips the header.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Log auth header presence on /mcp requests."""
        if request.url.path == "/mcp":
            auth_header = request.headers.get("authorization", "")
            if auth_header:
                logger.warning(
                    "Incoming /mcp request — Auth header present, "
                    "prefix: Bearer %s...",
                    (
                        auth_header[7:19]
                        if auth_header.startswith("Bearer ")
                        else "(non-bearer)"
                    ),
                )
            else:
                logger.warning("Incoming /mcp request — NO Authorization header!")
        return await call_next(request)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Simple bearer token authentication for MCP HTTP transport.

    Skips auth on /health (public) and when no token is configured (local dev).
    """

    def __init__(self, app: Starlette, token: str) -> None:
        super().__init__(app)
        self.token = token

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Check Authorization header on protected routes."""
        if request.url.path == "/health":
            return await call_next(request)

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != self.token:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        return await call_next(request)


def create_http_app() -> Starlette:
    """Create the streamable-HTTP MCP app with optional auth middleware.

    When GITHUB_CLIENT_ID is set, OAuth mode is enabled and the GitHub
    callback route is registered. Otherwise, falls back to optional
    bearer token auth via HERD_API_TOKEN.

    Returns:
        Starlette ASGI app with appropriate authentication configured.
    """
    app = mcp.streamable_http_app()

    if _oauth_provider:
        # CORS: claude.ai makes browser-based requests to /mcp.
        # Without CORS, the browser can't send the Authorization header
        # (non-simple header requires preflight).
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["https://claude.ai"],
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Mcp-Session-Id"],
            expose_headers=["Mcp-Session-Id"],
        )
        # Debug middleware to log incoming auth headers
        app.add_middleware(_AuthDebugMiddleware)
    else:
        # Local/agent mode: optional bearer token auth
        token = os.getenv("HERD_API_TOKEN")
        if token:
            app.add_middleware(BearerAuthMiddleware, token=token)  # type: ignore[arg-type]

    return app
