"""Agent spawning tool implementation."""

from __future__ import annotations

import logging
import os
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from herd_mcp import linear_client
from herd_mcp.db import connection

from ._helpers import extract_craft_section, find_repo_root, read_file_safe

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry
    from herd_core.adapters.repo import RepoAdapter

logger = logging.getLogger(__name__)

# Backward-compatible aliases
_find_repo_root = find_repo_root
_read_file_safe = read_file_safe
_extract_craft_section = extract_craft_section


def _create_worktree(
    ticket_id: str,
    agent_code: str,
    repo_root: Path,
    repo_adapter: RepoAdapter | None = None,
) -> Path:
    """Create a git worktree for the agent.

    Args:
        ticket_id: Linear ticket ID (e.g., DBC-126).
        agent_code: Agent code (e.g., mason, fresco).
        repo_root: Repository root path.
        repo_adapter: Optional RepoAdapter for git operations.

    Returns:
        Path to created worktree.

    Raises:
        RuntimeError: If worktree creation fails.
    """
    # Format: /private/tmp/{agent}-{ticket-id-lowercase}
    worktree_path = Path(f"/private/tmp/{agent_code}-{ticket_id.lower()}")
    branch_name = f"herd/{agent_code}/{ticket_id.lower()}-herd-spawn"

    try:
        # Adapter path
        if repo_adapter:
            repo_adapter.create_worktree(branch_name, str(worktree_path))
            logger.info(
                f"Created worktree at {worktree_path} on branch {branch_name} (via adapter)"
            )
            return worktree_path
        else:
            # Existing inline subprocess fallback
            subprocess.run(
                ["git", "worktree", "add", str(worktree_path), "-b", branch_name],
                cwd=str(repo_root),
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info(f"Created worktree at {worktree_path} on branch {branch_name}")
            return worktree_path
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Failed to create worktree at {worktree_path}: {e.stderr}"
        ) from e
    except Exception as e:
        raise RuntimeError(f"Failed to create worktree at {worktree_path}: {e}") from e


def _assemble_context_payload(
    ticket_id: str,
    agent_code: str,
    model_code: str,
    repo_root: Path,
    worktree_path: Path,
    ticket_title: str = "",
    ticket_description: str = "",
) -> str:
    """Assemble the full context payload for spawning the agent.

    Args:
        ticket_id: Linear ticket ID.
        agent_code: Agent code.
        model_code: Model to use.
        repo_root: Repository root path.
        worktree_path: Path to agent's worktree.
        ticket_title: Ticket title (pre-fetched).
        ticket_description: Ticket description (pre-fetched).

    Returns:
        Full context payload as a string.
    """
    # Read required files
    role_file_path = repo_root / ".herd" / "roles" / f"{agent_code}.md"
    craft_file_path = repo_root / ".herd" / "craft.md"
    claude_md_path = repo_root / "CLAUDE.md"

    role_content = (
        _read_file_safe(role_file_path) or f"(Role file not found: {role_file_path})"
    )
    craft_full = _read_file_safe(craft_file_path) or ""
    claude_md = _read_file_safe(claude_md_path) or "(CLAUDE.md not found)"

    # Extract agent-specific craft section
    craft_section = _extract_craft_section(craft_full, agent_code) if craft_full else ""

    # Get Slack token from environment
    slack_token = os.getenv("HERD_SLACK_TOKEN", "")

    # Branch name
    branch_name = f"herd/{agent_code}/{ticket_id.lower()}-herd-spawn"

    # Assemble the payload
    payload = f"""You are {agent_code.title()}, spawned to work on {ticket_id}.

## YOUR IDENTITY
{role_content}

## CRITICAL GIT RULES
- NEVER push to main. NEVER run `git push origin main`.
- ALL work goes on your feature branch. Push ONLY your branch: `git push -u origin {branch_name}`
- Create a PR from your branch. The Architect merges. You NEVER merge or push to main.
- NEVER merge PRs. You do NOT have merge authority. Only Mini-Mao merges with --admin after Wardenstein QA. Submitting the PR is the end of your responsibility.

## SLACK TOKEN
export HERD_SLACK_TOKEN="{slack_token}"

## WORKING DIRECTORY
You are working in: {worktree_path}
Branch: {branch_name}

## ASSIGNMENT: {ticket_id} — {ticket_title}

{ticket_description}

## CRAFT STANDARDS ({agent_code.title()} section)
{craft_section}

## PROJECT GUIDELINES (CLAUDE.md)
{claude_md}

START WORKING NOW.
"""

    return payload


async def execute(
    count: int,
    role: str,
    model: str | None,
    agent_name: str | None,
    ticket_id: str | None = None,
    registry: AdapterRegistry | None = None,
) -> dict:
    """Spawn new agent instances with full context assembly.

    Args:
        count: Number of agents to spawn (DEPRECATED - use ticket_id for single spawn).
        role: Agent role (backend, frontend, qa, docs).
        model: Optional model override.
        agent_name: Current agent identity (spawner).
        ticket_id: Optional Linear ticket ID for single spawn with full context.
        registry: Optional adapter registry for dependency injection.

    Returns:
        Dict with spawned instance codes and context payload if ticket_id provided.
    """
    # New path: ticket-based spawn with full context assembly
    if ticket_id:
        if count != 1:
            logger.warning(f"ticket_id provided but count={count}, forcing count=1")
            count = 1

        try:
            repo_root = _find_repo_root()
        except RuntimeError as e:
            return {
                "agents": [],
                "error": str(e),
                "spawned": 0,
            }

        with connection() as conn:
            # NOTE: StoreAdapter wiring for CRUD operations kept as raw SQL for now.
            # Future: migrate to store.get() and store.save() once entity mappings are stable.

            # Verify agent_def exists for the role (search by agent_code OR agent_role)
            agent_def = conn.execute(
                """
                SELECT agent_code, default_model_code, agent_status
                FROM herd.agent_def
                WHERE (agent_code = ? OR agent_role = ?)
                  AND deleted_at IS NULL
                LIMIT 1
                """,
                [role, role],
            ).fetchone()

            if not agent_def:
                return {
                    "agents": [],
                    "error": f"No agent definition found for role: {role}",
                    "role": role,
                    "spawned": 0,
                }

            agent_code = agent_def[0]
            default_model = agent_def[1] if agent_def[1] else "claude-sonnet-4"
            model_code = model if model else default_model

            # Verify or register ticket
            ticket = conn.execute(
                """
                SELECT ticket_code, ticket_title, ticket_description
                FROM herd.ticket_def
                WHERE ticket_code = ?
                  AND deleted_at IS NULL
                """,
                [ticket_id],
            ).fetchone()

            # Auto-register from Linear if not found
            if not ticket and linear_client.is_linear_identifier(ticket_id):
                logger.info(
                    f"Ticket {ticket_id} not found in DB, attempting Linear fetch"
                )
                from herd_core.types import TicketRecord

                tr: TicketRecord | None = None
                if registry and registry.tickets:
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
                    conn.execute(
                        """
                        INSERT INTO herd.ticket_def
                          (ticket_code, ticket_title, ticket_description, ticket_current_status,
                           project_code, created_at, modified_at)
                        VALUES (?, ?, ?, 'backlog', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                        """,
                        [tr.id, tr.title or "", tr.description or "", tr.project],
                    )
                    logger.info(f"Auto-registered ticket {ticket_id} from Linear")

                    # Re-fetch
                    ticket = conn.execute(
                        """
                        SELECT ticket_code, ticket_title, ticket_description
                        FROM herd.ticket_def
                        WHERE ticket_code = ?
                        """,
                        [ticket_id],
                    ).fetchone()

            if not ticket:
                return {
                    "agents": [],
                    "error": f"Ticket {ticket_id} not found in DB or Linear",
                    "spawned": 0,
                }

            # Create worktree
            try:
                repo_adapter = registry.repo if registry else None
                worktree_path = _create_worktree(
                    ticket_id, agent_code, repo_root, repo_adapter
                )
            except RuntimeError as e:
                return {
                    "agents": [],
                    "error": f"Failed to create worktree: {e}",
                    "spawned": 0,
                }

            # Get spawning agent's current instance (if available)
            spawned_by_instance = None
            if agent_name:
                spawner = conn.execute(
                    """
                    SELECT agent_instance_code
                    FROM herd.agent_instance
                    WHERE agent_code = ?
                      AND agent_instance_ended_at IS NULL
                    ORDER BY agent_instance_started_at DESC
                    LIMIT 1
                    """,
                    [agent_name],
                ).fetchone()

                if spawner:
                    spawned_by_instance = spawner[0]

            # Create agent instance
            instance_code = f"inst-{uuid.uuid4().hex[:8]}"

            conn.execute(
                """
                INSERT INTO herd.agent_instance
                  (agent_instance_code, agent_code, model_code, ticket_code,
                   spawned_by_agent_instance_code, agent_instance_started_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                [instance_code, agent_code, model_code, ticket_id, spawned_by_instance],
            )

            # Record lifecycle activity
            conn.execute(
                """
                INSERT INTO herd.agent_instance_lifecycle_activity
                  (agent_instance_code, lifecycle_event_type, lifecycle_detail, created_at)
                VALUES (?, 'spawned', ?, CURRENT_TIMESTAMP)
                """,
                [
                    instance_code,
                    f"Spawned by {agent_name or 'system'} for {ticket_id} with model {model_code}",
                ],
            )

            # Transition ticket to In Progress
            conn.execute(
                """
                INSERT INTO herd.agent_instance_ticket_activity
                  (agent_instance_code, ticket_code, ticket_event_type, ticket_status,
                   ticket_activity_comment, created_at)
                VALUES (?, ?, 'status_changed', 'in_progress', ?, CURRENT_TIMESTAMP)
                """,
                [instance_code, ticket_id, "Transitioned to in_progress by spawn"],
            )

            conn.execute(
                """
                UPDATE herd.ticket_def
                SET ticket_current_status = 'in_progress', modified_at = CURRENT_TIMESTAMP
                WHERE ticket_code = ?
                """,
                [ticket_id],
            )

            # Sync to Linear - use adapter if available
            linear_synced = False
            if linear_client.is_linear_identifier(ticket_id):
                try:
                    if registry and registry.tickets:
                        registry.tickets.transition(ticket_id, "in_progress")
                        linear_synced = True
                        logger.info(
                            f"Synced ticket {ticket_id} to In Progress in Linear (via adapter)"
                        )
                    else:
                        linear_issue = linear_client.get_issue(ticket_id)
                        if linear_issue:
                            # In Progress state UUID
                            linear_client.update_issue_state(
                                linear_issue["id"],
                                "77631f63-b27b-45a5-8b04-f9f82b4facde",
                            )
                            linear_synced = True
                            logger.info(
                                f"Synced ticket {ticket_id} to In Progress in Linear"
                            )
                except Exception as e:
                    logger.warning(f"Failed to sync ticket {ticket_id} to Linear: {e}")

            # Assemble context payload
            context_payload = _assemble_context_payload(
                ticket_id,
                agent_code,
                model_code,
                repo_root,
                worktree_path,
                ticket_title=ticket[1] if ticket else "",
                ticket_description=ticket[2] if ticket else "",
            )

            return {
                "agents": [instance_code],
                "spawned": 1,
                "role": role,
                "agent_code": agent_code,
                "model": model_code,
                "spawned_by": agent_name,
                "spawned_by_instance": spawned_by_instance,
                "ticket_id": ticket_id,
                "worktree_path": str(worktree_path),
                "branch_name": f"herd/{agent_code}/{ticket_id.lower()}-herd-spawn",
                "linear_synced": linear_synced,
                "context_payload": context_payload,
            }

    # Legacy path: multi-spawn without ticket (backward compatibility)
    if count < 1:
        return {
            "agents": [],
            "error": "count must be at least 1",
            "spawned": 0,
        }

    with connection() as conn:
        # Verify agent_def exists for the role (search by agent_code OR agent_role)
        agent_def = conn.execute(
            """
            SELECT agent_code, default_model_code, agent_status
            FROM herd.agent_def
            WHERE (agent_code = ? OR agent_role = ?)
              AND deleted_at IS NULL
            LIMIT 1
            """,
            [role, role],
        ).fetchone()

        if not agent_def:
            return {
                "agents": [],
                "error": f"No agent definition found for role: {role}",
                "role": role,
                "spawned": 0,
            }

        agent_code = agent_def[0]
        default_model = agent_def[1] if agent_def[1] else "claude-sonnet-4"
        model_code = model if model else default_model

        # Get spawning agent's current instance (if available)
        spawned_by_instance = None
        if agent_name:
            spawner = conn.execute(
                """
                SELECT agent_instance_code
                FROM herd.agent_instance
                WHERE agent_code = ?
                  AND agent_instance_ended_at IS NULL
                ORDER BY agent_instance_started_at DESC
                LIMIT 1
                """,
                [agent_name],
            ).fetchone()

            if spawner:
                spawned_by_instance = spawner[0]

        # Spawn the requested number of agents
        spawned_instances = []
        for _ in range(count):
            instance_code = f"inst-{uuid.uuid4().hex[:8]}"

            # Insert agent_instance
            conn.execute(
                """
                INSERT INTO herd.agent_instance
                  (agent_instance_code, agent_code, model_code, ticket_code,
                   spawned_by_agent_instance_code, agent_instance_started_at)
                VALUES (?, ?, ?, NULL, ?, CURRENT_TIMESTAMP)
                """,
                [instance_code, agent_code, model_code, spawned_by_instance],
            )

            # Record lifecycle activity
            conn.execute(
                """
                INSERT INTO herd.agent_instance_lifecycle_activity
                  (agent_instance_code, lifecycle_event_type, lifecycle_detail, created_at)
                VALUES (?, 'spawned', ?, CURRENT_TIMESTAMP)
                """,
                [
                    instance_code,
                    f"Spawned by {agent_name or 'system'} with model {model_code}",
                ],
            )

            spawned_instances.append(instance_code)

        return {
            "agents": spawned_instances,
            "spawned": len(spawned_instances),
            "role": role,
            "agent_code": agent_code,
            "model": model_code,
            "spawned_by": agent_name,
            "spawned_by_instance": spawned_by_instance,
        }
