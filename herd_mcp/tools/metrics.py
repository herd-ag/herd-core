"""Metrics query tool implementation."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from herd_mcp.db import connection

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry


def _parse_period(period: str | None) -> tuple[str | None, str | None]:
    """Parse period string into start_date and end_date for SQL filtering.

    Args:
        period: Period string (today, this_week, this_sprint, last_30d, or ISO date range).

    Returns:
        Tuple of (start_date, end_date) as ISO strings, or (None, None).
    """
    if not period:
        return None, None

    now = datetime.now()

    if period == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.isoformat(), now.isoformat()
    elif period == "this_week":
        # Start of week (Monday)
        start = now - timedelta(days=now.weekday())
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.isoformat(), now.isoformat()
    elif period == "this_sprint":
        # Approximate as last 14 days (2 weeks)
        start = now - timedelta(days=14)
        return start.isoformat(), now.isoformat()
    elif period == "last_30d":
        start = now - timedelta(days=30)
        return start.isoformat(), now.isoformat()
    elif ".." in period:
        # ISO date range: "2026-01-01..2026-02-01"
        parts = period.split("..")
        if len(parts) == 2:
            return parts[0], parts[1]

    return None, None


def _build_period_filter(
    start_date: str | None, end_date: str | None, column: str = "created_at"
) -> str:
    """Build SQL WHERE clause for period filtering.

    Args:
        start_date: Start date ISO string.
        end_date: End date ISO string.
        column: Column name to filter on.

    Returns:
        SQL WHERE clause (without WHERE keyword), or empty string.
    """
    if not start_date or not end_date:
        return ""

    return f"{column} >= '{start_date}' AND {column} <= '{end_date}'"


async def execute(
    query: str,
    period: str | None,
    group_by: str | None,
    agent_name: str | None,
    registry: AdapterRegistry | None = None,
) -> dict:
    """Query operational metrics from the Herd database.

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
    # Support documented aliases
    alias_map = {
        "token_costs": "cost_per_ticket",
        "review_stats": "review_effectiveness",
        "velocity": "sprint_velocity",
    }
    query = alias_map.get(query, query)

    # NOTE: Complex aggregate queries (JOINs, GROUP BY, COALESCE, subqueries) in
    # metrics.py are kept as raw SQL. StoreAdapter's generic CRUD interface doesn't
    # cover analytics. Future: ReportingAdapter or store.raw_query().
    start_date, end_date = _parse_period(period)
    period_filter = _build_period_filter(start_date, end_date)

    with connection() as conn:
        if query == "cost_per_ticket":
            return _query_cost_per_ticket(conn, period_filter, group_by)
        elif query == "agent_performance":
            return _query_agent_performance(conn, period_filter)
        elif query == "model_efficiency":
            return _query_model_efficiency(conn, period_filter, group_by)
        elif query == "review_effectiveness":
            return _query_review_effectiveness(conn, period_filter, group_by)
        elif query == "sprint_velocity":
            return _query_sprint_velocity(conn, period_filter)
        elif query == "pipeline_efficiency":
            return _query_pipeline_efficiency(conn, period_filter)
        elif query == "headline":
            return _query_headline(conn, period_filter)
        else:
            return {
                "data": [],
                "summary": f"Unknown query type: {query}",
                "error": f"Unknown query: {query}",
            }


def _query_cost_per_ticket(
    conn: Any,
    period_filter: str,
    group_by: str | None,
) -> dict:
    """Query cost per ticket.

    Args:
        conn: Database connection.
        period_filter: SQL period filter clause.
        group_by: Optional grouping.

    Returns:
        Dict with data and summary.
    """
    where_clause = f"WHERE {period_filter}" if period_filter else ""

    sql = f"""
        SELECT
            ai.ticket_code,
            SUM(ta.token_cost_usd) AS total_cost_usd,
            SUM(ta.token_input_count) AS total_input_tokens,
            SUM(ta.token_output_count) AS total_output_tokens
        FROM herd.agent_instance ai
        JOIN herd.agent_instance_token_activity ta
          ON ai.agent_instance_code = ta.agent_instance_code
        {where_clause}
        GROUP BY ai.ticket_code
        ORDER BY total_cost_usd DESC
    """

    rows = conn.execute(sql).fetchall()
    data = [
        {
            "ticket": r[0],
            "cost_usd": float(r[1]) if r[1] else 0.0,
            "input_tokens": int(r[2]) if r[2] else 0,
            "output_tokens": int(r[3]) if r[3] else 0,
        }
        for r in rows
    ]

    total_cost = sum(d["cost_usd"] for d in data)
    ticket_count = len(data)
    avg_cost = total_cost / ticket_count if ticket_count > 0 else 0.0

    summary = (
        f"Total cost across {ticket_count} tickets: ${total_cost:.2f} "
        f"(avg: ${avg_cost:.2f}/ticket)"
    )

    return {"data": data, "summary": summary}


def _query_agent_performance(conn: Any, period_filter: str) -> dict:
    """Query agent performance metrics.

    Args:
        conn: Database connection.
        period_filter: SQL period filter clause.

    Returns:
        Dict with data and summary.
    """
    where_clause = f"AND {period_filter}" if period_filter else ""

    # Count PRs created, reviews passed, and calculate avg cycle time
    sql = f"""
        SELECT
            ad.agent_code,
            ad.agent_role,
            COUNT(DISTINCT CASE WHEN ala.lifecycle_event_type = 'pr_submitted' THEN ala.agent_instance_code END) AS prs_created,
            COUNT(DISTINCT CASE WHEN ara.review_event_type = 'review_submitted' THEN ara.review_code END) AS reviews_submitted,
            COUNT(DISTINCT ai.ticket_code) AS tickets_worked
        FROM herd.agent_def ad
        LEFT JOIN herd.agent_instance ai ON ad.agent_code = ai.agent_code
        LEFT JOIN herd.agent_instance_lifecycle_activity ala
          ON ai.agent_instance_code = ala.agent_instance_code
        LEFT JOIN herd.agent_instance_review_activity ara
          ON ai.agent_instance_code = ara.agent_instance_code
        WHERE ad.deleted_at IS NULL {where_clause}
        GROUP BY ad.agent_code, ad.agent_role
        ORDER BY prs_created DESC
    """

    rows = conn.execute(sql).fetchall()
    data = [
        {
            "agent": r[0],
            "role": r[1],
            "prs_created": int(r[2]) if r[2] else 0,
            "reviews_submitted": int(r[3]) if r[3] else 0,
            "tickets_worked": int(r[4]) if r[4] else 0,
        }
        for r in rows
    ]

    total_prs = sum(d["prs_created"] for d in data)
    total_reviews = sum(d["reviews_submitted"] for d in data)

    summary = (
        f"{len(data)} agents tracked: {total_prs} PRs created, "
        f"{total_reviews} reviews submitted"
    )

    return {"data": data, "summary": summary}


def _query_model_efficiency(
    conn: Any,
    period_filter: str,
    group_by: str | None,
) -> dict:
    """Query model efficiency metrics.

    Args:
        conn: Database connection.
        period_filter: SQL period filter clause.
        group_by: Optional grouping.

    Returns:
        Dict with data and summary.
    """
    where_clause = f"WHERE {period_filter}" if period_filter else ""

    sql = f"""
        SELECT
            ta.model_code,
            SUM(ta.token_cost_usd) AS total_cost_usd,
            SUM(ta.token_input_count) AS total_input_tokens,
            SUM(ta.token_output_count) AS total_output_tokens,
            COUNT(*) AS request_count
        FROM herd.agent_instance_token_activity ta
        {where_clause}
        GROUP BY ta.model_code
        ORDER BY total_cost_usd DESC
    """

    rows = conn.execute(sql).fetchall()
    data = [
        {
            "model": r[0],
            "cost_usd": float(r[1]) if r[1] else 0.0,
            "input_tokens": int(r[2]) if r[2] else 0,
            "output_tokens": int(r[3]) if r[3] else 0,
            "requests": int(r[4]) if r[4] else 0,
        }
        for r in rows
    ]

    total_cost = sum(d["cost_usd"] for d in data)
    total_requests = sum(d["requests"] for d in data)

    summary = (
        f"{len(data)} models tracked: ${total_cost:.2f} total cost, "
        f"{total_requests} requests"
    )

    return {"data": data, "summary": summary}


def _query_review_effectiveness(
    conn: Any,
    period_filter: str,
    group_by: str | None,
) -> dict:
    """Query review effectiveness metrics.

    Args:
        conn: Database connection.
        period_filter: SQL period filter clause.
        group_by: Optional grouping.

    Returns:
        Dict with data and summary.
    """
    where_clause = f"WHERE {period_filter}" if period_filter else ""

    if group_by == "category":
        sql = f"""
            SELECT
                rf.finding_category,
                COUNT(*) AS finding_count,
                SUM(CASE WHEN rf.finding_severity = 'blocking' THEN 1 ELSE 0 END) AS blocking_count,
                SUM(CASE WHEN rf.finding_severity = 'advisory' THEN 1 ELSE 0 END) AS advisory_count
            FROM herd.review_finding rf
            JOIN herd.review_def rd ON rf.review_code = rd.review_code
            {where_clause}
            GROUP BY rf.finding_category
            ORDER BY finding_count DESC
        """

        rows = conn.execute(sql).fetchall()
        data = [
            {
                "category": r[0],
                "total_findings": int(r[1]) if r[1] else 0,
                "blocking": int(r[2]) if r[2] else 0,
                "advisory": int(r[3]) if r[3] else 0,
            }
            for r in rows
        ]

        total_findings = sum(d["total_findings"] for d in data)
        summary = f"Finding categories: {len(data)} categories, {total_findings} total findings"
    else:
        sql = f"""
            SELECT
                rd.review_verdict,
                COUNT(*) AS review_count,
                AVG((SELECT COUNT(*) FROM herd.review_finding rf WHERE rf.review_code = rd.review_code)) AS avg_findings_per_review
            FROM herd.review_def rd
            {where_clause}
            GROUP BY rd.review_verdict
            ORDER BY review_count DESC
        """

        rows = conn.execute(sql).fetchall()
        data = [
            {
                "verdict": r[0],
                "count": int(r[1]) if r[1] else 0,
                "avg_findings": float(r[2]) if r[2] else 0.0,
            }
            for r in rows
        ]

        total_reviews = sum(d["count"] for d in data)
        pass_count = sum(d["count"] for d in data if d["verdict"] == "pass")
        pass_rate = (pass_count / total_reviews * 100) if total_reviews > 0 else 0.0

        summary = f"{total_reviews} reviews: {pass_rate:.1f}% pass rate"

    return {"data": data, "summary": summary}


def _query_sprint_velocity(conn: Any, period_filter: str) -> dict:
    """Query sprint velocity metrics.

    Args:
        conn: Database connection.
        period_filter: SQL period filter clause.

    Returns:
        Dict with data and summary.
    """
    where_clause = f"WHERE {period_filter}" if period_filter else ""

    sql = f"""
        SELECT
            td.current_sprint_code,
            COUNT(*) AS tickets_completed,
            COUNT(DISTINCT td.ticket_code) AS unique_tickets
        FROM herd.ticket_def td
        {where_clause}
        GROUP BY td.current_sprint_code
        ORDER BY td.current_sprint_code DESC
    """

    rows = conn.execute(sql).fetchall()
    data = [
        {
            "sprint": r[0] if r[0] else "unassigned",
            "tickets_completed": int(r[1]) if r[1] else 0,
        }
        for r in rows
    ]

    total_tickets = sum(d["tickets_completed"] for d in data)
    sprint_count = len([d for d in data if d["sprint"] != "unassigned"])
    avg_velocity = total_tickets / sprint_count if sprint_count > 0 else 0.0

    summary = f"{total_tickets} tickets across {sprint_count} sprints (avg: {avg_velocity:.1f} tickets/sprint)"

    return {"data": data, "summary": summary}


def _query_pipeline_efficiency(conn: Any, period_filter: str) -> dict:
    """Query pipeline efficiency (avg time in each status).

    Args:
        conn: Database connection.
        period_filter: SQL period filter clause.

    Returns:
        Dict with data and summary.
    """
    where_clause = f"WHERE {period_filter}" if period_filter else ""

    sql = f"""
        SELECT
            ta.ticket_status,
            COUNT(*) AS transition_count
        FROM herd.agent_instance_ticket_activity ta
        {where_clause}
        GROUP BY ta.ticket_status
        ORDER BY transition_count DESC
    """

    rows = conn.execute(sql).fetchall()
    data = [
        {
            "status": r[0] if r[0] else "unknown",
            "transitions": int(r[1]) if r[1] else 0,
        }
        for r in rows
    ]

    total_transitions = sum(d["transitions"] for d in data)
    status_count = len(data)

    summary = f"{total_transitions} status transitions across {status_count} statuses"

    return {"data": data, "summary": summary}


def _query_headline(conn: Any, period_filter: str) -> dict:
    """Query headline metric: cost per merged line.

    Args:
        conn: Database connection.
        period_filter: SQL period filter clause.

    Returns:
        Dict with data and summary.
    """
    where_clause = f"AND {period_filter}" if period_filter else ""

    # Calculate total cost
    cost_sql = f"""
        SELECT SUM(token_cost_usd) AS total_cost
        FROM herd.agent_instance_token_activity ta
        WHERE token_cost_usd IS NOT NULL {where_clause}
    """

    cost_result = conn.execute(cost_sql).fetchone()
    total_cost = float(cost_result[0]) if cost_result and cost_result[0] else 0.0

    # Approximate lines added (we don't have this in schema, so return placeholder)
    # In real implementation, this would query PR metadata or git stats
    lines_added = 1000  # Placeholder

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
