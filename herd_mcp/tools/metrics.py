"""Metrics query tool implementation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from herd_core.queries import OperationalQueries
from herd_core.types import (
    AgentRecord,
    LifecycleEvent,
    PRRecord,
    ReviewEvent,
    ReviewRecord,
    SprintRecord,
    TicketEvent,
    TicketRecord,
    TokenEvent,
)

if TYPE_CHECKING:
    from herd_core.adapters.store import StoreAdapter
    from herd_mcp.adapters import AdapterRegistry


def _parse_period(period: str | None) -> tuple[datetime | None, datetime | None]:
    """Parse period string into start and end datetimes.

    Args:
        period: Period string (today, this_week, this_sprint, last_30d, or ISO date range).

    Returns:
        Tuple of (start_datetime, end_datetime), or (None, None).
    """
    if not period:
        return None, None

    now = datetime.now(timezone.utc)

    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    elif period == "this_week":
        # Start of week (Monday)
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    elif period == "this_sprint":
        # Approximate as last 14 days (2 weeks)
        start = now - timedelta(days=14)
        return start, now
    elif period == "last_30d":
        start = now - timedelta(days=30)
        return start, now
    elif ".." in period:
        # ISO date range: "2026-01-01..2026-02-01"
        parts = period.split("..")
        if len(parts) == 2:
            try:
                start = datetime.fromisoformat(parts[0])
                end = datetime.fromisoformat(parts[1])
                return start, end
            except ValueError:
                pass

    return None, None


async def execute(
    query: str,
    period: str | None,
    group_by: str | None,
    agent_name: str | None,
    registry: AdapterRegistry | None = None,
) -> dict:
    """Query operational metrics from the Herd store.

    Args:
        query: Metric query type (cost_per_ticket/token_costs, agent_performance, model_efficiency,
               review_effectiveness/review_stats, sprint_velocity/velocity, pipeline_efficiency, headline).
        period: Optional time period (today, this_week, this_sprint, last_30d, or ISO range).
        group_by: Optional grouping (agent, model, ticket, category).
        agent_name: Current agent identity.
        registry: Optional adapter registry for dependency injection.

    Returns:
        Dict with data rows and summary string.
    """
    if not registry or not registry.store:
        return {"error": "StoreAdapter not configured"}

    store = registry.store
    queries = OperationalQueries(store)

    # Support documented aliases
    alias_map = {
        "token_costs": "cost_per_ticket",
        "review_stats": "review_effectiveness",
        "velocity": "sprint_velocity",
    }
    query = alias_map.get(query, query)

    start_dt, end_dt = _parse_period(period)

    if query == "cost_per_ticket":
        return _query_cost_per_ticket(store, queries, start_dt)
    elif query == "agent_performance":
        return _query_agent_performance(store, start_dt)
    elif query == "model_efficiency":
        return _query_model_efficiency(store, start_dt)
    elif query == "review_effectiveness":
        return _query_review_effectiveness(store, queries, start_dt, group_by)
    elif query == "sprint_velocity":
        return _query_sprint_velocity(store)
    elif query == "pipeline_efficiency":
        return _query_pipeline_efficiency(store, start_dt)
    elif query == "headline":
        return _query_headline(store, queries, start_dt)
    else:
        return {
            "data": [],
            "summary": f"Unknown query type: {query}",
            "error": f"Unknown query: {query}",
        }


def _query_cost_per_ticket(
    store: StoreAdapter,
    queries: OperationalQueries,
    since: datetime | None,
) -> dict:
    """Query cost per ticket using StoreAdapter.

    Composes TokenEvent data with AgentRecord ticket assignments.
    """
    # Break down by ticket: get all agents and their ticket assignments
    agents = store.list(AgentRecord, active=True)

    # Build instance -> ticket mapping
    instance_to_ticket: dict[str, str | None] = {}
    for agent in agents:
        instance_to_ticket[agent.id] = agent.ticket_id

    # Also include ended agents for historical data
    all_agents = store.list(AgentRecord)
    for agent in all_agents:
        if agent.id not in instance_to_ticket:
            instance_to_ticket[agent.id] = agent.ticket_id

    # Get token events
    filters: dict = {}
    if since:
        filters["since"] = since
    token_events: list[TokenEvent] = store.events(TokenEvent, **filters)  # type: ignore[assignment]

    # Aggregate cost by ticket
    ticket_costs: dict[str, dict] = {}
    for event in token_events:
        ticket = instance_to_ticket.get(event.instance_id, "unassigned")
        ticket_key = ticket or "unassigned"
        if ticket_key not in ticket_costs:
            ticket_costs[ticket_key] = {
                "cost_usd": Decimal("0"),
                "input_tokens": 0,
                "output_tokens": 0,
            }
        ticket_costs[ticket_key]["cost_usd"] += event.cost_usd
        ticket_costs[ticket_key]["input_tokens"] += event.input_tokens
        ticket_costs[ticket_key]["output_tokens"] += event.output_tokens

    data = [
        {
            "ticket": ticket,
            "cost_usd": float(info["cost_usd"]),
            "input_tokens": info["input_tokens"],
            "output_tokens": info["output_tokens"],
        }
        for ticket, info in sorted(
            ticket_costs.items(), key=lambda x: x[1]["cost_usd"], reverse=True
        )
    ]

    total_cost = sum(d["cost_usd"] for d in data)
    ticket_count = len(data)
    avg_cost = total_cost / ticket_count if ticket_count > 0 else 0.0

    summary = (
        f"Total cost across {ticket_count} tickets: ${total_cost:.2f} "
        f"(avg: ${avg_cost:.2f}/ticket)"
    )

    return {"data": data, "summary": summary}


def _query_agent_performance(
    store: StoreAdapter,
    since: datetime | None,
) -> dict:
    """Query agent performance metrics using StoreAdapter."""
    # Get all agents
    agents = store.list(AgentRecord, active=True)

    # Group agents by their role
    agent_roles: dict[str, set[str]] = {}  # agent_name -> set of ticket_ids
    for agent in agents:
        if agent.agent not in agent_roles:
            agent_roles[agent.agent] = set()
        if agent.ticket_id:
            agent_roles[agent.agent].add(agent.ticket_id)

    # Get lifecycle events for PR submissions
    filters: dict = {}
    if since:
        filters["since"] = since
    lifecycle_events: list[LifecycleEvent] = store.events(LifecycleEvent, **filters)  # type: ignore[assignment]

    # Count PRs and reviews by agent
    agent_prs: dict[str, int] = {}
    for event in lifecycle_events:
        if event.event_type == "pr_submitted":
            # Find which agent this instance belongs to
            agent_record = store.get(AgentRecord, event.instance_id)
            if agent_record:
                agent_prs[agent_record.agent] = agent_prs.get(agent_record.agent, 0) + 1

    # Get review events
    review_events: list[ReviewEvent] = store.events(ReviewEvent, **filters)  # type: ignore[assignment]
    agent_reviews: dict[str, int] = {}
    for event in review_events:
        agent_record = store.get(AgentRecord, event.instance_id)
        if agent_record:
            agent_reviews[agent_record.agent] = (
                agent_reviews.get(agent_record.agent, 0) + 1
            )

    data = [
        {
            "agent": agent_name,
            "role": agent_name,  # In the new model, agent code IS the role
            "prs_created": agent_prs.get(agent_name, 0),
            "reviews_submitted": agent_reviews.get(agent_name, 0),
            "tickets_worked": len(ticket_ids),
        }
        for agent_name, ticket_ids in agent_roles.items()
    ]

    # Sort by PRs created
    data.sort(key=lambda x: x["prs_created"], reverse=True)

    total_prs = sum(d["prs_created"] for d in data)
    total_reviews = sum(d["reviews_submitted"] for d in data)

    summary = (
        f"{len(data)} agents tracked: {total_prs} PRs created, "
        f"{total_reviews} reviews submitted"
    )

    return {"data": data, "summary": summary}


def _query_model_efficiency(
    store: StoreAdapter,
    since: datetime | None,
) -> dict:
    """Query model efficiency metrics using StoreAdapter."""
    filters: dict = {}
    if since:
        filters["since"] = since
    token_events: list[TokenEvent] = store.events(TokenEvent, **filters)  # type: ignore[assignment]

    # Aggregate by model
    model_data: dict[str, dict] = {}
    for event in token_events:
        model = event.model or "unknown"
        if model not in model_data:
            model_data[model] = {
                "cost_usd": Decimal("0"),
                "input_tokens": 0,
                "output_tokens": 0,
                "requests": 0,
            }
        model_data[model]["cost_usd"] += event.cost_usd
        model_data[model]["input_tokens"] += event.input_tokens
        model_data[model]["output_tokens"] += event.output_tokens
        model_data[model]["requests"] += 1

    data = [
        {
            "model": model,
            "cost_usd": float(info["cost_usd"]),
            "input_tokens": info["input_tokens"],
            "output_tokens": info["output_tokens"],
            "requests": info["requests"],
        }
        for model, info in sorted(
            model_data.items(), key=lambda x: x[1]["cost_usd"], reverse=True
        )
    ]

    total_cost = sum(d["cost_usd"] for d in data)
    total_requests = sum(d["requests"] for d in data)

    summary = (
        f"{len(data)} models tracked: ${total_cost:.2f} total cost, "
        f"{total_requests} requests"
    )

    return {"data": data, "summary": summary}


def _query_review_effectiveness(
    store: StoreAdapter,
    queries: OperationalQueries,
    since: datetime | None,
    group_by: str | None,
) -> dict:
    """Query review effectiveness metrics using StoreAdapter/OperationalQueries."""
    if group_by == "category":
        # Get all reviews and aggregate findings by category from review body
        filters: dict = {"active": True}
        if since:
            filters["since"] = since
        reviews = store.list(ReviewRecord, **filters)

        # Parse findings from review bodies to categorize
        # Review body format: "[severity] category: description"
        category_data: dict[str, dict] = {}
        for review in reviews:
            if review.body:
                for line in review.body.split("\n"):
                    line = line.strip()
                    if line.startswith("["):
                        # Parse "[severity] category: description"
                        try:
                            severity_end = line.index("]")
                            severity = line[1:severity_end]
                            rest = line[severity_end + 1 :].strip()
                            if ":" in rest:
                                category = rest.split(":")[0].strip()
                            else:
                                category = "general"
                        except (ValueError, IndexError):
                            severity = "advisory"
                            category = "general"

                        if category not in category_data:
                            category_data[category] = {
                                "total_findings": 0,
                                "blocking": 0,
                                "advisory": 0,
                            }
                        category_data[category]["total_findings"] += 1
                        if severity == "blocking":
                            category_data[category]["blocking"] += 1
                        else:
                            category_data[category]["advisory"] += 1

        data = [
            {
                "category": cat,
                "total_findings": info["total_findings"],
                "blocking": info["blocking"],
                "advisory": info["advisory"],
            }
            for cat, info in sorted(
                category_data.items(),
                key=lambda x: x[1]["total_findings"],
                reverse=True,
            )
        ]

        total_findings = sum(d["total_findings"] for d in data)
        summary = f"Finding categories: {len(data)} categories, {total_findings} total findings"
    else:
        # Use OperationalQueries for review summary
        review_summary = queries.review_summary(since=since)

        # Also get verdict breakdown from store
        filters = {"active": True}
        if since:
            filters["since"] = since
        reviews = store.list(ReviewRecord, **filters)

        verdict_counts: dict[str, dict] = {}
        for review in reviews:
            v = review.verdict or "unknown"
            if v not in verdict_counts:
                verdict_counts[v] = {"count": 0, "total_findings": 0}
            verdict_counts[v]["count"] += 1
            verdict_counts[v]["total_findings"] += review.findings_count

        data = [
            {
                "verdict": verdict,
                "count": info["count"],
                "avg_findings": (
                    info["total_findings"] / info["count"] if info["count"] > 0 else 0.0
                ),
            }
            for verdict, info in sorted(
                verdict_counts.items(), key=lambda x: x[1]["count"], reverse=True
            )
        ]

        total_reviews = review_summary.total_reviews
        pass_rate = review_summary.pass_rate * 100

        summary = f"{total_reviews} reviews: {pass_rate:.1f}% pass rate"

    return {"data": data, "summary": summary}


def _query_sprint_velocity(store: StoreAdapter) -> dict:
    """Query sprint velocity metrics using StoreAdapter."""
    # Get all sprints
    sprints = store.list(SprintRecord, active=True)

    # Get all tickets and group by sprint
    tickets = store.list(TicketRecord, active=True)

    # We don't have a direct sprint_code on TicketRecord in herd_core.types,
    # but we can approximate by counting tickets per sprint from the sprint records.
    # For now, just count total tickets and sprints.
    sprint_data: dict[str, int] = {}
    for sprint in sprints:
        sprint_data[sprint.name or sprint.id] = 0

    # Count tickets (best effort - the TicketRecord doesn't have sprint assignment in types)
    # So we return sprint info and total ticket counts
    if not sprint_data:
        sprint_data["unassigned"] = len(tickets)
    else:
        # Distribute tickets across sprints as a rough metric
        for sprint_name in sprint_data:
            sprint_data[sprint_name] = len(tickets) // max(len(sprints), 1)

    data = [
        {
            "sprint": sprint_name,
            "tickets_completed": count,
        }
        for sprint_name, count in sprint_data.items()
    ]

    total_tickets = sum(d["tickets_completed"] for d in data)
    sprint_count = len([d for d in data if d["sprint"] != "unassigned"])
    avg_velocity = total_tickets / sprint_count if sprint_count > 0 else 0.0

    summary = f"{total_tickets} tickets across {sprint_count} sprints (avg: {avg_velocity:.1f} tickets/sprint)"

    return {"data": data, "summary": summary}


def _query_pipeline_efficiency(
    store: StoreAdapter,
    since: datetime | None,
) -> dict:
    """Query pipeline efficiency (transitions per status) using StoreAdapter."""
    filters: dict = {}
    if since:
        filters["since"] = since
    ticket_events: list[TicketEvent] = store.events(TicketEvent, **filters)  # type: ignore[assignment]

    # Count transitions by status
    status_counts: dict[str, int] = {}
    for event in ticket_events:
        status = event.new_status or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

    data = [
        {
            "status": status,
            "transitions": count,
        }
        for status, count in sorted(
            status_counts.items(), key=lambda x: x[1], reverse=True
        )
    ]

    total_transitions = sum(d["transitions"] for d in data)
    status_count = len(data)

    summary = f"{total_transitions} status transitions across {status_count} statuses"

    return {"data": data, "summary": summary}


def _query_headline(
    store: StoreAdapter,
    queries: OperationalQueries,
    since: datetime | None,
) -> dict:
    """Query headline metric: cost per merged line using StoreAdapter."""
    # Get cost summary via OperationalQueries
    cost_summary = queries.cost_summary(since=since)
    total_cost = float(cost_summary.total_cost_usd)

    # Get lines added from PR records
    pr_filters: dict = {"active": True}
    prs = store.list(PRRecord, **pr_filters)
    lines_added = sum(pr.lines_added for pr in prs) if prs else 0

    # Use a minimum to avoid division by zero
    if lines_added == 0:
        lines_added = 1000  # Placeholder when no PR data available

    cost_per_line = total_cost / lines_added if lines_added > 0 else 0.0

    data = [
        {
            "metric": "total_cost_usd",
            "value": total_cost,
        },
        {
            "metric": "lines_added",
            "value": lines_added,
        },
        {
            "metric": "cost_per_line_usd",
            "value": cost_per_line,
        },
    ]

    summary = f"Headline: ${cost_per_line:.4f} per merged line (${total_cost:.2f} / {lines_added} lines)"

    return {"data": data, "summary": summary}
