"""Agent spawning tool implementation."""

from __future__ import annotations

import logging
import os
import subprocess
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from herd_core.types import (
    AgentRecord,
    AgentState,
    LifecycleEvent,
    TicketEvent,
    TicketRecord,
)

from ._helpers import (
    extract_craft_section,
    find_repo_root,
    get_herd_content_path,
    read_file_safe,
)

if TYPE_CHECKING:
    from herd_mcp.adapters import AdapterRegistry
    from herd_core.adapters.repo import RepoAdapter

logger = logging.getLogger(__name__)

# Backward-compatible aliases
_find_repo_root = find_repo_root
_read_file_safe = read_file_safe
_extract_craft_section = extract_craft_section

# Agent role mapping: resolves role names to agent codes.
# The agent_code is the canonical name used in .herd/roles/{agent_code}.md.
# Role aliases allow spawn by role description (e.g., "backend" -> "mason").
_ROLE_TO_AGENT: dict[str, str] = {
    # Direct agent codes (identity mapping)
    "mason": "mason",
    "fresco": "fresco",
    "scribe": "scribe",
    "wardenstein": "wardenstein",
    "steve": "steve",
    "leonardo": "leonardo",
    "vigil": "vigil",
    "rook": "rook",
    "gauss": "gauss",
    "pikasso": "pikasso",
    "shakesquill": "shakesquill",
    "mini-mao": "mini-mao",
    # Role aliases
    "backend": "mason",
    "frontend": "fresco",
    "qa": "wardenstein",
    "docs": "scribe",
    "documentation": "scribe",
    "coordinator": "steve",
    "architect": "leonardo",
    "monitor": "vigil",
    "executor": "rook",
    "analytics": "gauss",
}

# Default model for each agent (fallback when no model specified)
_AGENT_DEFAULT_MODEL: dict[str, str] = {
    "mason": "claude-sonnet-4",
    "fresco": "claude-sonnet-4",
    "scribe": "claude-sonnet-4",
    "wardenstein": "claude-sonnet-4",
    "steve": "claude-sonnet-4",
    "leonardo": "claude-sonnet-4",
    "vigil": "claude-sonnet-4",
    "rook": "claude-sonnet-4",
    "gauss": "claude-sonnet-4",
    "pikasso": "claude-sonnet-4",
    "shakesquill": "claude-sonnet-4",
    "mini-mao": "claude-sonnet-4",
}


def _resolve_agent_code(role: str) -> str | None:
    """Resolve a role string to an agent code.

    Checks the role mapping first, then checks if a .herd/roles/{role}.md file exists.

    Args:
        role: Role string (agent code or role alias).

    Returns:
        Agent code string, or None if not resolved.
    """
    # Check mapping first
    agent_code = _ROLE_TO_AGENT.get(role.lower())
    if agent_code:
        return agent_code

    # Check if role file exists directly
    role_path = get_herd_content_path(f"roles/{role.lower()}.md")
    if role_path:
        return role.lower()

    return None


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
    instance_code: str = "",
    team: str = "",
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
        instance_code: Instance ID assigned to this agent.
        team: Team the agent belongs to.

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
    slack_token = os.getenv("HERD_NOTIFY_SLACK_TOKEN", "")

    # Branch name
    branch_name = f"herd/{agent_code}/{ticket_id.lower()}-herd-spawn"

    # HDR-0036 Loop 1: Recall rejection patterns for the work area
    rejection_patterns = ""
    try:
        from herd_mcp.memory import recall as semantic_recall

        patterns = semantic_recall(
            f"review rejection patterns and findings for {ticket_id} {agent_code}",
            limit=5,
            memory_type="pattern",
        )
        if patterns:
            lines = ["## Known Quality Patterns (from previous reviews)", ""]
            for p in patterns:
                lines.append(f"- {p.get('content', '')[:200]}")
            rejection_patterns = "\n".join(lines)
    except ImportError:
        pass  # LanceDB not available
    except Exception:
        pass  # Don't block spawn

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
export HERD_NOTIFY_SLACK_TOKEN="{slack_token}"

## WORKING DIRECTORY
You are working in: {worktree_path}
Branch: {branch_name}

## ASSIGNMENT: {ticket_id} — {ticket_title}

{ticket_description}

{rejection_patterns}

## CRAFT STANDARDS ({agent_code.title()} section)
{craft_section}

## YOUR INSTANCE
Instance ID: {instance_code}
Team: {team}
Address: {agent_code}.{instance_code}@{team}
Pass agent_name and instance_id on every MCP tool call.

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
    if not registry or not registry.store:
        return {"error": "StoreAdapter not configured"}

    store = registry.store

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

        # Resolve agent code from role
        agent_code = _resolve_agent_code(role)
        if not agent_code:
            return {
                "agents": [],
                "error": f"No agent definition found for role: {role}",
                "role": role,
                "spawned": 0,
            }

        default_model = _AGENT_DEFAULT_MODEL.get(agent_code, "claude-sonnet-4")
        model_code = model if model else default_model

        # Verify or fetch ticket via store
        ticket_record = store.get(TicketRecord, ticket_id)

        # Auto-register from Linear if not found
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
                "agents": [],
                "error": f"Ticket {ticket_id} not found in store or Linear",
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
        spawner_team = os.getenv("HERD_TEAM", "")
        if agent_name:
            spawner_instances = store.list(AgentRecord, agent=agent_name, active=True)
            for inst in spawner_instances:
                if inst.state in (AgentState.RUNNING, AgentState.SPAWNING):
                    spawned_by_instance = inst.id
                    if inst.team:
                        spawner_team = inst.team
                    break

        # Create agent instance record
        instance_code = f"inst-{uuid.uuid4().hex[:8]}"
        branch_name = f"herd/{agent_code}/{ticket_id.lower()}-herd-spawn"

        agent_record = AgentRecord(
            id=instance_code,
            agent=agent_code,
            model=model_code,
            ticket_id=ticket_id,
            state=AgentState.SPAWNING,
            worktree=str(worktree_path),
            branch=branch_name,
            spawned_by=spawned_by_instance,
            team=spawner_team,
        )
        async with registry.write_lock:
            store.save(agent_record)

            # Record lifecycle event
            store.append(
                LifecycleEvent(
                    entity_id=instance_code,
                    event_type="spawned",
                    instance_id=instance_code,
                    detail=f"Spawned by {agent_name or 'system'} for {ticket_id} with model {model_code}",
                )
            )

            # Auto-shadow to KuzuDB graph (ticket-based spawn)
            try:
                from herd_mcp.graph import create_edge, merge_node

                merge_node(
                    "Agent",
                    {
                        "id": instance_code,
                        "code": agent_code,
                        "role": agent_code,
                        "status": "spawning",
                        "team": spawner_team,
                        "host": os.getenv("HERD_HOST", ""),
                    },
                )
                if spawned_by_instance:
                    create_edge(
                        "SpawnedBy",
                        "Agent",
                        instance_code,
                        "Agent",
                        spawned_by_instance,
                    )
                merge_node(
                    "Ticket",
                    {
                        "id": ticket_id,
                        "title": ticket_record.title if ticket_record else "",
                        "status": "in_progress",
                        "priority": "",
                    },
                )
                create_edge("AssignedTo", "Ticket", ticket_id, "Agent", instance_code)
            except ImportError:
                pass  # KuzuDB not installed
            except Exception:
                logger.warning("Failed to auto-shadow spawn to graph", exc_info=True)

            # Transition ticket to In Progress via store
            store.append(
                TicketEvent(
                    entity_id=ticket_id,
                    event_type="status_changed",
                    instance_id=instance_code,
                    previous_status=ticket_record.status,
                    new_status="in_progress",
                    note="Transitioned to in_progress by spawn",
                )
            )

            ticket_record.status = "in_progress"
            store.save(ticket_record)

        # Sync to Linear - use adapter if available
        linear_synced = False
        from herd_mcp import linear_client

        if linear_client.is_linear_identifier(ticket_id):
            try:
                if registry.tickets:
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
            ticket_title=ticket_record.title if ticket_record else "",
            ticket_description=(
                (ticket_record.description or "") if ticket_record else ""
            ),
            instance_code=instance_code,
            team=spawner_team,
        )

        # Graph enrichment: related context for spawn
        graph_spawn_context: dict = {}
        try:
            from herd_mcp.graph import is_available, query_graph

            if is_available():
                # Find files previously touched for this ticket
                related_files = query_graph(
                    "MATCH (t:Ticket {id: $tid})<-[:AssignedTo]-(a:Agent)"
                    "-[:Touches]->(f:File) "
                    "RETURN DISTINCT f.path AS path, a.code AS agent",
                    {"tid": ticket_id},
                )
                # Find related decisions
                related_decisions = query_graph(
                    "MATCH (t:Ticket {id: $tid})-[:Implements]->(d:Decision) "
                    "RETURN d.id AS id, d.title AS title",
                    {"tid": ticket_id},
                )
                graph_spawn_context = {
                    "related_files": related_files[:10],
                    "related_decisions": related_decisions[:5],
                }
        except ImportError:
            pass
        except Exception:
            logger.warning("Failed to enrich spawn with graph context", exc_info=True)

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
            "branch_name": branch_name,
            "linear_synced": linear_synced,
            "context_payload": context_payload,
            "graph_context": graph_spawn_context,
        }

    # Legacy path: multi-spawn without ticket (backward compatibility)
    if count < 1:
        return {
            "agents": [],
            "error": "count must be at least 1",
            "spawned": 0,
        }

    # Resolve agent code from role
    agent_code = _resolve_agent_code(role)
    if not agent_code:
        return {
            "agents": [],
            "error": f"No agent definition found for role: {role}",
            "role": role,
            "spawned": 0,
        }

    default_model = _AGENT_DEFAULT_MODEL.get(agent_code, "claude-sonnet-4")
    model_code = model if model else default_model

    # Get spawning agent's current instance (if available)
    spawned_by_instance = None
    if agent_name:
        spawner_instances = store.list(AgentRecord, agent=agent_name, active=True)
        for inst in spawner_instances:
            if inst.state in (AgentState.RUNNING, AgentState.SPAWNING):
                spawned_by_instance = inst.id
                break

    # Spawn the requested number of agents
    spawned_instances = []
    for _ in range(count):
        instance_code = f"inst-{uuid.uuid4().hex[:8]}"

        # Create agent instance record
        agent_record = AgentRecord(
            id=instance_code,
            agent=agent_code,
            model=model_code,
            state=AgentState.SPAWNING,
            spawned_by=spawned_by_instance,
        )
        async with registry.write_lock:
            store.save(agent_record)

            # Record lifecycle event
            store.append(
                LifecycleEvent(
                    entity_id=instance_code,
                    event_type="spawned",
                    instance_id=instance_code,
                    detail=f"Spawned by {agent_name or 'system'} with model {model_code}",
                )
            )

        # Auto-shadow to KuzuDB graph (legacy spawn)
        try:
            from herd_mcp.graph import create_edge, merge_node

            merge_node(
                "Agent",
                {
                    "id": instance_code,
                    "code": agent_code,
                    "role": agent_code,
                    "status": "spawning",
                    "team": "",
                    "host": "",
                },
            )
            if spawned_by_instance:
                create_edge(
                    "SpawnedBy",
                    "Agent",
                    instance_code,
                    "Agent",
                    spawned_by_instance,
                )
        except ImportError:
            pass  # KuzuDB not installed
        except Exception:
            logger.warning("Failed to auto-shadow spawn to graph", exc_info=True)

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
