"""REST API server for Herd MCP operations.

Provides HTTP REST endpoints for all MCP tools, enabling agents to
interact via curl without needing MCP protocol access.
"""

from __future__ import annotations

import os
from typing import Any

from aiohttp import web

from .tools import (
    assign,
    catchup,
    lifecycle,
    log,
    metrics,
    review,
    spawn,
    status,
    token_harvest,
    transition,
)


def _get_agent_name(request: web.Request) -> str | None:
    """Extract agent name from request headers or environment.

    Args:
        request: The aiohttp request object.

    Returns:
        Agent name from X-Agent-Name header or HERD_AGENT_NAME env var.
    """
    return request.headers.get("X-Agent-Name") or os.getenv("HERD_AGENT_NAME")


@web.middleware
async def auth_middleware(request: web.Request, handler: Any) -> web.Response:
    """Authenticate requests using bearer token.

    Args:
        request: The aiohttp request object.
        handler: The request handler.

    Returns:
        Response from handler or 401 if unauthorized.
    """
    # Health endpoint doesn't require auth
    if request.path == "/api/health":
        return await handler(request)

    # Check if auth is required
    required_token = os.getenv("HERD_API_TOKEN")
    if not required_token:
        # No-auth mode (local dev)
        return await handler(request)

    # Extract token from Authorization header
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return web.json_response({"error": "unauthorized"}, status=401)

    token = auth_header[7:]  # Remove "Bearer " prefix
    if token != required_token:
        return web.json_response({"error": "unauthorized"}, status=401)

    return await handler(request)


async def handle_health(request: web.Request) -> web.Response:
    """Health check endpoint.

    Args:
        request: The aiohttp request object.

    Returns:
        JSON response with status and version.
    """
    return web.json_response({"status": "ok", "version": "0.1.0"})


async def handle_log(request: web.Request) -> web.Response:
    """POST /api/log - Post message to Slack.

    Args:
        request: The aiohttp request object.

    Returns:
        JSON response with log result.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON in request body"}, status=400)

    if "message" not in body:
        return web.json_response(
            {"error": "missing required field: message"}, status=400
        )

    try:
        agent_name = _get_agent_name(request)
        result = await log.execute(
            message=body["message"],
            channel=body.get("channel"),
            await_response=body.get("await_response", False),
            agent_name=agent_name,
        )
        return web.json_response(result)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_status(request: web.Request) -> web.Response:
    """GET /api/status - Query herd status.

    Args:
        request: The aiohttp request object.

    Returns:
        JSON response with status result.
    """
    try:
        scope = request.query.get("scope", "all")
        agent_name = _get_agent_name(request)
        result = await status.execute(scope, agent_name)
        return web.json_response(result)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_spawn(request: web.Request) -> web.Response:
    """POST /api/spawn - Spawn new agents.

    Args:
        request: The aiohttp request object.

    Returns:
        JSON response with spawn result.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON in request body"}, status=400)

    if "count" not in body:
        return web.json_response({"error": "missing required field: count"}, status=400)
    if "role" not in body:
        return web.json_response({"error": "missing required field: role"}, status=400)

    try:
        agent_name = _get_agent_name(request)
        result = await spawn.execute(
            count=body["count"],
            role=body["role"],
            model=body.get("model"),
            agent_name=agent_name,
        )
        return web.json_response(result)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_assign(request: web.Request) -> web.Response:
    """POST /api/assign - Assign ticket to agent.

    Args:
        request: The aiohttp request object.

    Returns:
        JSON response with assignment result.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON in request body"}, status=400)

    if "ticket_id" not in body:
        return web.json_response(
            {"error": "missing required field: ticket_id"}, status=400
        )

    try:
        agent_name = _get_agent_name(request)
        result = await assign.execute(
            ticket_id=body["ticket_id"],
            agent_name=body.get("agent_name") or agent_name,
            priority=body.get("priority", "normal"),
        )
        return web.json_response(result)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_transition(request: web.Request) -> web.Response:
    """POST /api/transition - Transition ticket status.

    Args:
        request: The aiohttp request object.

    Returns:
        JSON response with transition result.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON in request body"}, status=400)

    if "ticket_id" not in body:
        return web.json_response(
            {"error": "missing required field: ticket_id"}, status=400
        )
    if "to_status" not in body:
        return web.json_response(
            {"error": "missing required field: to_status"}, status=400
        )

    try:
        agent_name = _get_agent_name(request)
        result = await transition.execute(
            ticket_id=body["ticket_id"],
            to_status=body["to_status"],
            blocked_by=body.get("blocked_by"),
            note=body.get("note"),
            agent_name=agent_name,
        )
        return web.json_response(result)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_review(request: web.Request) -> web.Response:
    """POST /api/review - Submit code review.

    Args:
        request: The aiohttp request object.

    Returns:
        JSON response with review result.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON in request body"}, status=400)

    if "pr_number" not in body:
        return web.json_response(
            {"error": "missing required field: pr_number"}, status=400
        )
    if "ticket_id" not in body:
        return web.json_response(
            {"error": "missing required field: ticket_id"}, status=400
        )
    if "verdict" not in body:
        return web.json_response(
            {"error": "missing required field: verdict"}, status=400
        )
    if "findings" not in body:
        return web.json_response(
            {"error": "missing required field: findings"}, status=400
        )

    try:
        agent_name = _get_agent_name(request)
        result = await review.execute(
            pr_number=body["pr_number"],
            ticket_id=body["ticket_id"],
            verdict=body["verdict"],
            findings=body["findings"],
            agent_name=agent_name,
        )
        return web.json_response(result)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_metrics(request: web.Request) -> web.Response:
    """GET /api/metrics - Query operational metrics.

    Args:
        request: The aiohttp request object.

    Returns:
        JSON response with metrics result.
    """
    query = request.query.get("query")
    if not query:
        return web.json_response(
            {"error": "missing required parameter: query"}, status=400
        )

    try:
        agent_name = _get_agent_name(request)
        result = await metrics.execute(
            query=query,
            period=request.query.get("period"),
            group_by=request.query.get("group_by"),
            agent_name=agent_name,
        )
        return web.json_response(result)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_catchup(request: web.Request) -> web.Response:
    """GET /api/catchup - Get session recovery summary.

    Args:
        request: The aiohttp request object.

    Returns:
        JSON response with catchup result.
    """
    try:
        agent_name = _get_agent_name(request)
        result = await catchup.execute(agent_name)
        return web.json_response(result)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_decommission(request: web.Request) -> web.Response:
    """POST /api/decommission - Permanently decommission an agent.

    Args:
        request: The aiohttp request object.

    Returns:
        JSON response with decommission result.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON in request body"}, status=400)

    if "agent_name" not in body:
        return web.json_response(
            {"error": "missing required field: agent_name"}, status=400
        )

    try:
        current_agent = _get_agent_name(request)
        result = await lifecycle.decommission(body["agent_name"], current_agent)
        return web.json_response(result)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_standdown(request: web.Request) -> web.Response:
    """POST /api/standdown - Temporarily stand down an agent.

    Args:
        request: The aiohttp request object.

    Returns:
        JSON response with standdown result.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON in request body"}, status=400)

    if "agent_name" not in body:
        return web.json_response(
            {"error": "missing required field: agent_name"}, status=400
        )

    try:
        current_agent = _get_agent_name(request)
        result = await lifecycle.standdown(body["agent_name"], current_agent)
        return web.json_response(result)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def handle_harvest(request: web.Request) -> web.Response:
    """POST /api/harvest - Harvest token usage.

    Args:
        request: The aiohttp request object.

    Returns:
        JSON response with harvest result.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON in request body"}, status=400)

    if "agent_instance_code" not in body:
        return web.json_response(
            {"error": "missing required field: agent_instance_code"}, status=400
        )
    if "project_path" not in body:
        return web.json_response(
            {"error": "missing required field: project_path"}, status=400
        )

    try:
        result = await token_harvest.execute(
            agent_instance_code=body["agent_instance_code"],
            project_path=body["project_path"],
        )
        return web.json_response(result)
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


def create_app() -> web.Application:
    """Create and configure the aiohttp application.

    Returns:
        Configured aiohttp Application instance.
    """
    app = web.Application(middlewares=[auth_middleware])

    # Register routes
    app.router.add_get("/api/health", handle_health)
    app.router.add_post("/api/log", handle_log)
    app.router.add_get("/api/status", handle_status)
    app.router.add_post("/api/spawn", handle_spawn)
    app.router.add_post("/api/assign", handle_assign)
    app.router.add_post("/api/transition", handle_transition)
    app.router.add_post("/api/review", handle_review)
    app.router.add_get("/api/metrics", handle_metrics)
    app.router.add_get("/api/catchup", handle_catchup)
    app.router.add_post("/api/decommission", handle_decommission)
    app.router.add_post("/api/standdown", handle_standdown)
    app.router.add_post("/api/harvest", handle_harvest)

    return app


def run_server(host: str = "0.0.0.0", port: int = 8420) -> None:
    """Run the REST API server.

    Args:
        host: Host to bind to (default: 0.0.0.0).
        port: Port to bind to (default: 8420).
    """
    app = create_app()
    web.run_app(app, host=host, port=port)
