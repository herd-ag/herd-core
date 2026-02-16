"""Ticket transition tool implementation."""

from __future__ import annotations

import logging
import subprocess
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from herd_core.types import (
    AgentRecord,
    AgentState,
    TicketEvent,
    TicketRecord,
)
from herd_mcp.vault_refresh import get_manager

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry

logger = logging.getLogger(__name__)


def _get_ticket_commits(
    ticket_id: str, since: datetime, repo_root: str | None = None
) -> list[dict[str, str]]:
    """Get git commits mentioning a ticket ID since a timestamp.

    Runs ``git log`` as a subprocess and filters for commits whose
    subject line contains the ticket ID (case-insensitive).

    Args:
        ticket_id: The ticket identifier to search for (e.g. "DBC-123").
        since: Only consider commits after this timestamp.
        repo_root: Working directory for the git command. Defaults to ".".

    Returns:
        List of dicts with keys: sha, author, date, message.
        Returns an empty list if git is unavailable or no commits match.
    """
    try:
        cwd = repo_root or "."
        result = subprocess.run(
            [
                "git",
                "log",
                f"--since={since.isoformat()}",
                "--format=%H|||%an|||%ai|||%s",
                "--all",
            ],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        commits: list[dict[str, str]] = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|||")
            if len(parts) == 4 and ticket_id.lower() in parts[3].lower():
                commits.append(
                    {
                        "sha": parts[0][:8],
                        "author": parts[1],
                        "date": parts[2],
                        "message": parts[3],
                    }
                )
        return commits
    except (subprocess.SubprocessError, FileNotFoundError, OSError) as exc:
        logger.debug("Could not collect git commits for %s: %s", ticket_id, exc)
        return []


def _build_session_narrative(
    ticket_id: str,
    ticket_title: str,
    agent_name: str,
    started_at: datetime,
    completed_at: datetime,
    commits: list[dict[str, str]],
    note: str | None,
) -> tuple[str, str]:
    """Build a session narrative and focused summary for LanceDB storage.

    Args:
        ticket_id: The ticket identifier.
        ticket_title: Human-readable ticket title.
        agent_name: Name of the agent that completed the ticket.
        started_at: When the agent started working on the ticket.
        completed_at: When the ticket was marked done.
        commits: List of commit dicts from _get_ticket_commits.
        note: Optional transition note.

    Returns:
        Tuple of (full_narrative, focused_summary). The narrative is the
        detailed content; the summary is the concise text that gets embedded.
    """
    duration = completed_at - started_at
    hours = duration.total_seconds() / 3600.0

    # Build commit section
    if commits:
        commit_lines = [f"  - {c['sha']} {c['message']}" for c in commits[:10]]
        commit_section = f"Commits ({len(commits)} total):\n" + "\n".join(commit_lines)
        if len(commits) > 10:
            commit_section += f"\n  ... and {len(commits) - 10} more"
    else:
        commit_section = "Commits: 0 found matching ticket ID in git log."

    # Full narrative (stored as content)
    parts = [
        f"Session summary for {ticket_id} ({ticket_title}).",
        f"Agent: {agent_name}.",
        f"Duration: {hours:.1f} hours"
        f" ({started_at.strftime('%Y-%m-%d %H:%M')}"
        f" to {completed_at.strftime('%Y-%m-%d %H:%M')} UTC).",
        commit_section,
    ]
    if note:
        parts.append(f"Note: {note}")
    full_narrative = "\n".join(parts)

    # Focused summary (embedded for semantic search)
    if commits:
        key_messages = "; ".join(c["message"] for c in commits[:3])
        focused_summary = (
            f"{agent_name} completed {ticket_id} ({ticket_title})"
            f" in {hours:.1f}h with {len(commits)} commits: {key_messages}"
        )
    else:
        focused_summary = (
            f"{agent_name} completed {ticket_id} ({ticket_title})"
            f" in {hours:.1f}h (no commits matched ticket ID in git log)"
        )

    return full_narrative, focused_summary


async def execute(
    ticket_id: str,
    to_status: str,
    blocked_by: str | None,
    note: str | None,
    agent_name: str | None,
    registry: AdapterRegistry | None = None,
) -> dict:
    """Transition a ticket to a new status.

    Args:
        ticket_id: Linear ticket ID.
        to_status: Target status.
        blocked_by: Optional blocker ticket ID.
        note: Optional note about the transition.
        agent_name: Current agent identity.
        registry: Optional adapter registry for dependency injection.

    Returns:
        Dict with transition_id and elapsed time in previous status.
    """
    if not registry or not registry.store:
        return {"error": "StoreAdapter not configured"}

    store = registry.store

    # Look up ticket
    ticket_record = store.get(TicketRecord, ticket_id)

    # Auto-register from Linear if not found and looks like Linear ID
    if not ticket_record:
        from herd_mcp import linear_client

        if linear_client.is_linear_identifier(ticket_id):
            logger.info(
                f"Ticket {ticket_id} not found in store, attempting Linear fetch"
            )

            tr: TicketRecord | None = None
            if registry.tickets:
                try:
                    tr = registry.tickets.get(ticket_id)
                except Exception:
                    pass

            if tr is None:
                d = linear_client.get_issue(ticket_id)
                if d:
                    tr = TicketRecord(
                        id=d.get("identifier", d.get("id", "")),
                        title=d.get("title", ""),
                        description=d.get("description"),
                        status=(d.get("state") or {}).get("name", ""),
                        project=(d.get("project") or {}).get("name"),
                    )

            if tr:
                async with registry.write_lock:
                    store.save(tr)
                logger.info(f"Auto-registered ticket {ticket_id} from Linear")
                ticket_record = store.get(TicketRecord, ticket_id)

    if not ticket_record:
        return {
            "transition_id": None,
            "ticket": ticket_id,
            "to_status": to_status,
            "error": f"Ticket {ticket_id} not found in store or Linear",
        }

    current_status = ticket_record.status

    # Get agent's current instance
    agent_instance_code = None
    if agent_name:
        instances = store.list(AgentRecord, agent=agent_name, active=True)
        for inst in instances:
            if inst.state in (AgentState.RUNNING, AgentState.SPAWNING):
                agent_instance_code = inst.id
                break

    # Calculate elapsed time from last ticket event
    elapsed_minutes = None
    ticket_events = store.events(TicketEvent, entity_id=ticket_id)
    if ticket_events:
        last_event = ticket_events[-1]  # events ordered by created_at ascending
        if last_event.created_at:
            now = datetime.now(timezone.utc)
            if last_event.created_at.tzinfo is None:
                # Assume UTC if naive
                last_ts = last_event.created_at.replace(tzinfo=timezone.utc)
            else:
                last_ts = last_event.created_at
            elapsed_minutes = (now - last_ts).total_seconds() / 60.0

    # Determine event type based on transition
    event_type = "status_changed"
    if to_status == "blocked" or blocked_by:
        event_type = "blocked"
    elif current_status == "blocked" and to_status != "blocked":
        event_type = "unblocked"

    # Generate transition ID
    transition_id = str(uuid.uuid4())

    # Record transition as ticket event
    async with registry.write_lock:
        store.append(
            TicketEvent(
                entity_id=ticket_id,
                event_type=event_type,
                instance_id=agent_instance_code or "",
                previous_status=current_status,
                new_status=to_status,
                elapsed_minutes=elapsed_minutes,
                note=note,
                blocked_by=[blocked_by] if blocked_by else [],
            )
        )

        # Update ticket status
        ticket_record.status = to_status
        store.save(ticket_record)

    # Auto-shadow to KuzuDB graph
    try:
        from herd_mcp.graph import create_edge, merge_node

        merge_node(
            "Ticket",
            {
                "id": ticket_id,
                "title": ticket_record.title,
                "status": to_status,
                "priority": "",
            },
        )

        if to_status == "done" and agent_name:
            merge_node(
                "Agent",
                {
                    "id": agent_name,
                    "code": agent_name,
                    "role": agent_name,
                    "status": "active",
                    "team": "",
                    "host": "",
                },
            )
            create_edge("CompletedBy", "Ticket", ticket_id, "Agent", agent_name)

        if to_status == "blocked" and blocked_by:
            merge_node(
                "Ticket",
                {
                    "id": blocked_by,
                    "title": "",
                    "status": "",
                    "priority": "",
                },
            )
            create_edge("BlockedBy", "Ticket", ticket_id, "Ticket", blocked_by)
    except ImportError:
        pass  # KuzuDB not installed
    except Exception:
        logger.warning("Failed to auto-shadow transition to graph", exc_info=True)

    result = {
        "transition_id": transition_id,
        "ticket": {
            "id": ticket_record.id,
            "title": ticket_record.title,
            "previous_status": current_status,
            "new_status": to_status,
        },
        "elapsed_in_previous_minutes": elapsed_minutes,
        "event_type": event_type,
        "blocked_by": blocked_by,
        "agent": agent_name,
        "agent_instance_code": agent_instance_code,
        "note": ("No active agent instance found" if not agent_instance_code else None),
        "linear_synced": False,
    }

    # Sync to Linear if ticket looks like a Linear identifier
    from herd_mcp import linear_client

    if linear_client.is_linear_identifier(ticket_id):
        if registry.tickets:
            try:
                registry.tickets.transition(ticket_id, to_status)
                result["linear_synced"] = True
                logger.info(
                    f"Synced ticket {ticket_id} transition to {to_status} in Linear (via adapter)"
                )
            except Exception as e:
                logger.warning(f"Failed to sync ticket {ticket_id} to Linear: {e}")
                result["linear_sync_error"] = str(e)
        else:
            # Fall back to direct Linear client
            status_to_state_map = {
                "backlog": "f98ff170-87bd-4a1c-badc-4b67cd37edec",
                "assigned": "408b4cda-4d6e-403a-8030-78e8b0a6ffee",
                "in_progress": "77631f63-b27b-45a5-8b04-f9f82b4facde",
                "pr_submitted": "20590520-1bfc-4861-9cb8-e9f2a374d65b",
                "review": "20590520-1bfc-4861-9cb8-e9f2a374d65b",
                "qa_review": "dcbf4d63-b06e-4c1d-ba23-764d95b74193",
                "architect_review": "7a749bd4-bdbc-4924-aee7-9f9f6f8cdd8c",
                "done": "42bad6cf-cfb7-4dd2-9dc4-c0c3014bfc5f",
                "cancelled": "5034b57d-4204-4917-8f18-85e367f0d867",
            }

            linear_state_id = status_to_state_map.get(to_status)

            if linear_state_id:
                try:
                    linear_issue = linear_client.get_issue(ticket_id)
                    if linear_issue:
                        linear_client.update_issue_state(
                            linear_issue["id"], linear_state_id
                        )
                        result["linear_synced"] = True
                        logger.info(
                            f"Synced ticket {ticket_id} transition to {to_status} in Linear"
                        )
                    else:
                        logger.warning(
                            f"Could not find Linear issue {ticket_id} for sync"
                        )
                except Exception as e:
                    logger.warning(f"Failed to sync ticket {ticket_id} to Linear: {e}")
                    result["linear_sync_error"] = str(e)
            else:
                logger.info(f"Status {to_status} has no Linear mapping, skipping sync")

    # Trigger vault refresh if ticket transitioned to done
    if to_status == "done":
        # Auto-shadow ticket completion to LanceDB
        try:
            from herd_mcp.memory import store_memory

            completion_summary = f"Ticket {ticket_id} ({ticket_record.title}) completed. Transitioned from {current_status} to done by {agent_name}."
            if note:
                completion_summary += f" Note: {note}"
            store_memory(
                project="herd",
                agent=agent_name or "unknown",
                memory_type="session_summary",
                content=completion_summary,
                summary=completion_summary,
                session_id=f"{agent_name or 'unknown'}-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}",
                metadata={"ticket_id": ticket_id, "ticket_title": ticket_record.title},
            )
        except Exception:
            logger.warning(
                "Failed to auto-shadow ticket completion to LanceDB", exc_info=True
            )

        # Git-log-informed session summary — enriches the completion shadow
        # with commit history and duration data for better cross-session recall.
        try:
            from herd_mcp.memory import store_memory as store_mem

            effective_agent = agent_name or "unknown"
            completed_at = datetime.now(timezone.utc)

            # Find the agent instance that worked on this ticket to get started_at
            agent_instances = store.list(AgentRecord, ticket_id=ticket_id)
            started_at: datetime | None = None
            for inst in agent_instances:
                if inst.started_at is not None:
                    if inst.started_at.tzinfo is None:
                        started_at = inst.started_at.replace(tzinfo=timezone.utc)
                    else:
                        started_at = inst.started_at
                    break

            # Fall back: scan ticket events for the "assigned" event timestamp
            if started_at is None:
                for evt in ticket_events:
                    if evt.event_type == "assigned" and evt.created_at:
                        if evt.created_at.tzinfo is None:
                            started_at = evt.created_at.replace(tzinfo=timezone.utc)
                        else:
                            started_at = evt.created_at
                        break

            # Last resort: use the earliest ticket event timestamp
            if started_at is None and ticket_events:
                first_evt = ticket_events[0]
                if first_evt.created_at:
                    if first_evt.created_at.tzinfo is None:
                        started_at = first_evt.created_at.replace(tzinfo=timezone.utc)
                    else:
                        started_at = first_evt.created_at

            if started_at is not None:
                commits = _get_ticket_commits(ticket_id, started_at)

                full_narrative, focused_summary = _build_session_narrative(
                    ticket_id=ticket_id,
                    ticket_title=ticket_record.title,
                    agent_name=effective_agent,
                    started_at=started_at,
                    completed_at=completed_at,
                    commits=commits,
                    note=note,
                )

                store_mem(
                    project="herd",
                    agent=effective_agent,
                    memory_type="session_summary",
                    content=full_narrative,
                    summary=focused_summary,
                    session_id=f"{effective_agent}-{ticket_id}",
                    metadata={
                        "ticket_id": ticket_id,
                        "agent": effective_agent,
                        "commits": len(commits),
                        "duration_hours": round(
                            (completed_at - started_at).total_seconds() / 3600.0,
                            1,
                        ),
                        "source": "transition_done",
                    },
                )
                logger.info(
                    "Stored git-log session summary for %s (%d commits)",
                    ticket_id,
                    len(commits),
                )
            else:
                logger.info(
                    "Skipped git-log session summary for %s: "
                    "no started_at timestamp found",
                    ticket_id,
                )
        except ImportError:
            logger.debug(
                "LanceDB not available; skipped git-log session summary " "for %s",
                ticket_id,
            )
        except Exception:
            logger.warning(
                "Failed to store git-log session summary for %s",
                ticket_id,
                exc_info=True,
            )

        refresh_manager = get_manager()
        refresh_result = await refresh_manager.trigger_refresh(
            "ticket_done",
            {
                "ticket_id": ticket_id,
                "ticket_title": ticket_record.title,
                "agent": agent_name,
                "previous_status": current_status,
            },
        )
        logger.info(
            f"Vault refresh triggered after ticket done: {refresh_result.get('status')}",
            extra={"refresh_result": refresh_result},
        )

    return result
