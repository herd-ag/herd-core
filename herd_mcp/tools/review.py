"""Code review tool implementation."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from herd_core.queries import OperationalQueries
from herd_core.types import (
    AgentRecord,
    AgentState,
    ReviewEvent,
    ReviewRecord,
)
from herd_mcp.vault_refresh import get_manager

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry
    from herd_core.adapters.repo import RepoAdapter

logger = logging.getLogger(__name__)


def _post_to_slack(message: str, channel: str = "#herd-feed") -> dict[str, Any]:
    """Post message to Slack using urllib (no external deps).

    Args:
        message: Message to post.
        channel: Slack channel (with # prefix).

    Returns:
        Dict with success status and response data.
    """
    token = os.getenv("HERD_NOTIFY_SLACK_TOKEN")
    if not token:
        return {"success": False, "error": "HERD_NOTIFY_SLACK_TOKEN not set"}

    try:
        import urllib.request

        data = json.dumps(
            {
                "channel": channel,
                "text": message,
                "username": "Herd Review Bot",
                "icon_emoji": ":mag:",
            }
        ).encode()

        req = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
        )

        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())

        return {"success": result.get("ok", False), "response": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _post_review_to_github(
    pr_number: int, review_body: str, repo_adapter: RepoAdapter | None = None
) -> bool:
    """Post review to GitHub PR via gh CLI.

    Args:
        pr_number: GitHub PR number.
        review_body: Review comment body.
        repo_adapter: Optional RepoAdapter for git operations.

    Returns:
        True if posted successfully, False otherwise.
    """
    try:
        # Adapter path
        if repo_adapter:
            # RepoAdapter.add_pr_comment expects pr_id (string) and body
            repo_adapter.add_pr_comment(str(pr_number), review_body)
            return True
        else:
            # Existing inline subprocess fallback
            result = subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/dbt-conceptual/dbt-conceptual/issues/{pr_number}/comments",
                    "-f",
                    f"body={review_body}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            return result.returncode == 0
    except Exception:
        return False


def _format_review_body(verdict: str, findings: list[dict], review_code: str) -> str:
    """Format review findings into markdown for GitHub.

    Args:
        verdict: Review verdict (pass, fail, pass_with_advisory).
        findings: List of finding dicts.
        review_code: Review code for tracking.

    Returns:
        Formatted markdown review body.
    """
    verdict_emoji = {
        "pass": "✅",
        "fail": "❌",
        "pass_with_advisory": "⚠️",
    }

    lines = [
        f"## Code Review: {verdict_emoji.get(verdict, '❓')} {verdict.replace('_', ' ').title()}",
        "",
        f"**Review ID:** `{review_code}`",
        "",
    ]

    if findings:
        # Group findings by severity
        blocking = [f for f in findings if f.get("severity") == "blocking"]
        advisory = [f for f in findings if f.get("severity") == "advisory"]

        if blocking:
            lines.append("### 🚫 Blocking Issues")
            lines.append("")
            for f in blocking:
                category = f.get("category", "general")
                desc = f.get("description", "No description")
                lines.append(f"- **{category}**: {desc}")
            lines.append("")

        if advisory:
            lines.append("### 💡 Advisory Notes")
            lines.append("")
            for f in advisory:
                category = f.get("category", "general")
                desc = f.get("description", "No description")
                lines.append(f"- **{category}**: {desc}")
            lines.append("")
    else:
        lines.append("No specific findings noted.")
        lines.append("")

    lines.append("---")
    lines.append("*Review submitted via Herd MCP*")

    return "\n".join(lines)


async def execute(
    pr_number: int,
    ticket_id: str,
    verdict: str,
    findings: list[dict],
    agent_name: str | None,
    registry: AdapterRegistry | None = None,
) -> dict:
    """Submit a code review for a PR.

    Args:
        pr_number: GitHub PR number.
        ticket_id: Associated Linear ticket ID.
        verdict: Review verdict (pass, fail, pass_with_advisory).
        findings: List of finding dicts with severity, category, description.
        agent_name: Current agent identity (reviewer).
        registry: Optional adapter registry for dependency injection.

    Returns:
        Dict with review_id, posted status, and findings_count.
    """
    # Validate verdict
    valid_verdicts = {"pass", "fail", "pass_with_advisory"}
    if verdict not in valid_verdicts:
        return {
            "review_id": None,
            "posted": False,
            "error": f"Invalid verdict: {verdict}. Must be one of {valid_verdicts}",
        }

    if not registry or not registry.store:
        return {"error": "StoreAdapter not configured"}

    store = registry.store
    queries = OperationalQueries(store)

    # Recall relevant past review patterns for context enrichment
    past_review_context = []
    try:
        from herd_mcp.memory import recall as semantic_recall

        past_review_context = semantic_recall(
            f"review findings and patterns for ticket {ticket_id} or PR #{pr_number}",
            limit=3,
            memory_type="pattern",
        )
    except (ImportError, Exception):
        pass  # Semantic memory unavailable or failed

    # Graph enrichment: impact surface for reviewed files
    graph_impact: dict[str, list[dict]] = {}
    try:
        from herd_mcp.graph import is_available, query_graph

        if is_available():
            # Find decisions connected to this ticket
            connected_decisions = query_graph(
                "MATCH (t:Ticket {id: $tid})-[:Implements]->(d:Decision) "
                "RETURN d.id AS id, d.title AS title",
                {"tid": ticket_id},
            )
            # Find other agents who have touched files related to this ticket
            related_agents = query_graph(
                "MATCH (t:Ticket {id: $tid})<-[:AssignedTo]-(a:Agent)-[:Touches]->(f:File) "
                "RETURN DISTINCT a.code AS agent, f.path AS file_path",
                {"tid": ticket_id},
            )
            graph_impact = {
                "connected_decisions": connected_decisions[:5],
                "related_file_touches": related_agents[:10],
            }
    except ImportError:
        pass
    except Exception:
        logger.warning("Failed to enrich review with graph impact", exc_info=True)

    # Get current agent instance
    agent_instance_code = None
    if agent_name:
        instances = store.list(AgentRecord, agent=agent_name, active=True)
        for inst in instances:
            if inst.state in (AgentState.RUNNING, AgentState.SPAWNING):
                agent_instance_code = inst.id
                break

    # Generate codes
    review_code = f"REV-{uuid.uuid4().hex[:8]}"
    pr_code = f"PR-{pr_number}"

    # Determine review round using OperationalQueries
    review_round = queries.review_round_count(pr_code) + 1

    # Format findings body for the review record
    findings_body_parts = []
    for finding in findings:
        severity = finding.get("severity", "advisory")
        category = finding.get("category", "general")
        desc = finding.get("description", "")
        findings_body_parts.append(f"[{severity}] {category}: {desc}")
    findings_body = "\n".join(findings_body_parts) if findings_body_parts else ""

    # Save review record via store
    review_record = ReviewRecord(
        id=review_code,
        pr_id=pr_code,
        ticket_id=ticket_id,
        reviewer_instance_id=agent_instance_code,
        verdict=verdict,
        body=findings_body,
        findings_count=len(findings),
    )
    async with registry.write_lock:
        store.save(review_record)

        # Record review event
        if agent_instance_code:
            verdict_summary = f"{verdict} with {len(findings)} findings"
            store.append(
                ReviewEvent(
                    entity_id=pr_code,
                    event_type="review_submitted",
                    instance_id=agent_instance_code,
                    review_id=review_code,
                    pr_id=pr_code,
                    verdict=verdict,
                    detail=verdict_summary,
                )
            )

    # Auto-shadow review findings to LanceDB as patterns
    if findings:
        try:
            from herd_mcp.memory import store_memory

            summary = f"Review {verdict} for PR #{pr_number} (ticket {ticket_id}): {len(findings)} findings."
            review_content = f"{summary}\n{findings_body}"
            store_memory(
                project="herd",
                agent=agent_name or "unknown",
                memory_type="pattern",
                content=review_content,
                summary=summary,
                session_id=f"{agent_name or 'unknown'}-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                metadata={
                    "pr_number": pr_number,
                    "ticket_id": ticket_id,
                    "verdict": verdict,
                },
            )
        except Exception:
            logger.warning("Failed to auto-shadow review to LanceDB", exc_info=True)

    # Auto-shadow to KuzuDB graph
    try:
        from herd_mcp.graph import create_edge, merge_node

        reviewer_id = agent_name or "unknown"
        merge_node(
            "Agent",
            {
                "id": reviewer_id,
                "code": reviewer_id,
                "role": reviewer_id,
                "status": "active",
                "team": "",
                "host": "",
            },
        )
        merge_node(
            "Ticket",
            {
                "id": ticket_id,
                "title": "",
                "status": "",
                "priority": "",
            },
        )
        create_edge(
            "Reviews",
            "Agent",
            reviewer_id,
            "Ticket",
            ticket_id,
            {"verdict": verdict, "finding_count": len(findings)},
        )

        # Extract touched files from findings
        seen_files: set[str] = set()
        for finding in findings:
            file_path = finding.get("file_path", "")
            if file_path and file_path not in seen_files:
                seen_files.add(file_path)
                merge_node(
                    "File",
                    {
                        "id": file_path,
                        "path": file_path,
                        "repo": "herd-core",
                    },
                )
                create_edge(
                    "Touches",
                    "Agent",
                    reviewer_id,
                    "File",
                    file_path,
                    {"session_id": ""},
                )
    except ImportError:
        pass  # KuzuDB not installed
    except Exception:
        logger.warning("Failed to auto-shadow review to graph", exc_info=True)

    # Format and post review to GitHub
    review_body = _format_review_body(verdict, findings, review_code)
    repo_adapter = registry.repo if registry else None
    github_posted = _post_review_to_github(pr_number, review_body, repo_adapter)

    # Post summary to Slack - use adapter if available
    verdict_emoji = {
        "pass": "✅",
        "fail": "❌",
        "pass_with_advisory": "⚠️",
    }
    emoji = verdict_emoji.get(verdict, "❓")
    slack_message = (
        f"{emoji} Review submitted for PR #{pr_number} (Ticket: {ticket_id})\n"
        f"Verdict: *{verdict.replace('_', ' ').title()}*\n"
        f"Findings: {len(findings)} ({sum(1 for f in findings if f.get('severity') == 'blocking')} blocking)\n"
        f"Review ID: `{review_code}`"
    )

    if registry.notify:
        try:
            registry.notify.post(
                message=slack_message,
                channel="#herd-feed",
                username="Herd Review Bot",
            )
            slack_result: dict[str, Any] = {"success": True}
        except Exception as e:
            slack_result = {"success": False, "error": str(e)}
    else:
        slack_result = _post_to_slack(slack_message)

    result = {
        "review_id": review_code,
        "posted": github_posted and slack_result.get("success", False),
        "github_posted": github_posted,
        "slack_posted": slack_result.get("success", False),
        "findings_count": len(findings),
        "verdict": verdict,
        "review_round": review_round,
        "pr_number": pr_number,
        "ticket": ticket_id,
        "reviewer": agent_name,
        "past_review_patterns": (
            [
                {"content": m["content"], "created_at": m.get("created_at")}
                for m in past_review_context
            ]
            if past_review_context
            else []
        ),
        "graph_impact": graph_impact,
    }

    # Trigger vault refresh after review submission
    refresh_manager = get_manager()
    refresh_result = await refresh_manager.trigger_refresh(
        "review_submitted",
        {
            "pr_number": pr_number,
            "ticket_id": ticket_id,
            "verdict": verdict,
            "review_code": review_code,
            "reviewer": agent_name,
        },
    )
    logger.info(
        f"Vault refresh triggered after review: {refresh_result.get('status')}",
        extra={"refresh_result": refresh_result},
    )

    return result
