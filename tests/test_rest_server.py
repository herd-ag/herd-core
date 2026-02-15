"""Tests for REST API server."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase
from herd_mcp.rest_server import create_app


class TestRestAPI(AioHTTPTestCase):
    """Test cases for REST API endpoints."""

    async def get_application(self) -> web.Application:
        """Return the application instance for testing.

        Returns:
            Configured aiohttp application.
        """
        return create_app()

    async def test_health_endpoint(self) -> None:
        """Test health endpoint returns status without auth."""
        resp = await self.client.get("/api/health")
        assert resp.status == 200

        data = await resp.json()
        assert data["status"] == "ok"
        assert data["version"] == "0.1.0"

    @patch.dict(os.environ, {}, clear=True)
    async def test_no_auth_mode(self) -> None:
        """Test endpoints work without auth when HERD_API_TOKEN not set."""
        with patch(
            "herd_mcp.rest_server.status.execute", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"agents": []}

            resp = await self.client.get("/api/status")
            assert resp.status == 200

    @patch.dict(os.environ, {"HERD_API_TOKEN": "test-token-123"})
    async def test_valid_auth(self) -> None:
        """Test endpoint with valid bearer token."""
        with patch(
            "herd_mcp.rest_server.status.execute", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"agents": []}

            resp = await self.client.get(
                "/api/status", headers={"Authorization": "Bearer test-token-123"}
            )
            assert resp.status == 200

    @patch.dict(os.environ, {"HERD_API_TOKEN": "test-token-123"})
    async def test_invalid_auth(self) -> None:
        """Test endpoint with invalid bearer token."""
        resp = await self.client.get(
            "/api/status", headers={"Authorization": "Bearer wrong-token"}
        )
        assert resp.status == 401

        data = await resp.json()
        assert data["error"] == "unauthorized"

    @patch.dict(os.environ, {"HERD_API_TOKEN": "test-token-123"})
    async def test_missing_auth(self) -> None:
        """Test endpoint without auth header when auth required."""
        resp = await self.client.get("/api/status")
        assert resp.status == 401

        data = await resp.json()
        assert data["error"] == "unauthorized"

    async def test_log_endpoint(self) -> None:
        """Test POST /api/log endpoint."""
        with patch("herd_mcp.rest_server.log.execute", new_callable=AsyncMock) as mock:
            mock.return_value = {
                "posted": True,
                "event_id": "test-123",
                "agent": "grunt",
            }

            resp = await self.client.post(
                "/api/log",
                json={"message": "Test message", "channel": "#herd-feed"},
            )
            assert resp.status == 200

            data = await resp.json()
            assert data["posted"] is True
            assert data["event_id"] == "test-123"

            # Verify execute was called with correct args
            mock.assert_called_once()
            args = mock.call_args
            assert args[1]["message"] == "Test message"
            assert args[1]["channel"] == "#herd-feed"

    async def test_log_endpoint_missing_message(self) -> None:
        """Test POST /api/log without required message field."""
        resp = await self.client.post("/api/log", json={"channel": "#test"})
        assert resp.status == 400

        data = await resp.json()
        assert "missing required field: message" in data["error"]

    async def test_status_endpoint(self) -> None:
        """Test GET /api/status endpoint."""
        with patch(
            "herd_mcp.rest_server.status.execute", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"agents": [], "sprint": {}, "blockers": []}

            resp = await self.client.get("/api/status?scope=all")
            assert resp.status == 200

            data = await resp.json()
            assert "agents" in data

            # Verify execute was called with correct args
            mock.assert_called_once()
            args = mock.call_args
            assert args[0][0] == "all"

    async def test_spawn_endpoint(self) -> None:
        """Test POST /api/spawn endpoint."""
        with patch(
            "herd_mcp.rest_server.spawn.execute", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"spawned": ["grunt-001"]}

            resp = await self.client.post(
                "/api/spawn",
                json={"count": 1, "role": "grunt", "model": "claude-sonnet-4"},
            )
            assert resp.status == 200

            data = await resp.json()
            assert "spawned" in data

            # Verify execute was called with correct args
            mock.assert_called_once()
            args = mock.call_args
            assert args[1]["count"] == 1
            assert args[1]["role"] == "grunt"
            assert args[1]["model"] == "claude-sonnet-4"

    async def test_spawn_endpoint_missing_fields(self) -> None:
        """Test POST /api/spawn without required fields."""
        resp = await self.client.post("/api/spawn", json={"count": 1})
        assert resp.status == 400

        data = await resp.json()
        assert "missing required field: role" in data["error"]

    async def test_assign_endpoint(self) -> None:
        """Test POST /api/assign endpoint."""
        with patch(
            "herd_mcp.rest_server.assign.execute", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"assigned": True, "ticket_id": "DBC-130"}

            resp = await self.client.post(
                "/api/assign",
                json={
                    "ticket_id": "DBC-130",
                    "agent_name": "grunt",
                    "priority": "high",
                },
            )
            assert resp.status == 200

            data = await resp.json()
            assert data["assigned"] is True

            # Verify execute was called with correct args
            mock.assert_called_once()
            args = mock.call_args
            assert args[1]["ticket_id"] == "DBC-130"
            assert args[1]["agent_name"] == "grunt"
            assert args[1]["priority"] == "high"

    async def test_transition_endpoint(self) -> None:
        """Test POST /api/transition endpoint."""
        with patch(
            "herd_mcp.rest_server.transition.execute", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"transition_id": "trans-123"}

            resp = await self.client.post(
                "/api/transition",
                json={
                    "ticket_id": "DBC-130",
                    "to_status": "in_progress",
                    "note": "Starting work",
                },
            )
            assert resp.status == 200

            data = await resp.json()
            assert "transition_id" in data

            # Verify execute was called with correct args
            mock.assert_called_once()
            args = mock.call_args
            assert args[1]["ticket_id"] == "DBC-130"
            assert args[1]["to_status"] == "in_progress"
            assert args[1]["note"] == "Starting work"

    async def test_review_endpoint(self) -> None:
        """Test POST /api/review endpoint."""
        with patch(
            "herd_mcp.rest_server.review.execute", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"review_id": "rev-123", "posted": True}

            resp = await self.client.post(
                "/api/review",
                json={
                    "pr_number": 127,
                    "ticket_id": "DBC-130",
                    "verdict": "approve",
                    "findings": [],
                },
            )
            assert resp.status == 200

            data = await resp.json()
            assert "review_id" in data

            # Verify execute was called with correct args
            mock.assert_called_once()
            args = mock.call_args
            assert args[1]["pr_number"] == 127
            assert args[1]["ticket_id"] == "DBC-130"
            assert args[1]["verdict"] == "approve"

    async def test_metrics_endpoint(self) -> None:
        """Test GET /api/metrics endpoint."""
        with patch(
            "herd_mcp.rest_server.metrics.execute", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"data": [], "summary": {}}

            resp = await self.client.get(
                "/api/metrics?query=token_costs&period=sprint&group_by=agent"
            )
            assert resp.status == 200

            data = await resp.json()
            assert "data" in data

            # Verify execute was called with correct args
            mock.assert_called_once()
            args = mock.call_args
            assert args[1]["query"] == "token_costs"
            assert args[1]["period"] == "sprint"
            assert args[1]["group_by"] == "agent"

    async def test_metrics_endpoint_missing_query(self) -> None:
        """Test GET /api/metrics without required query parameter."""
        resp = await self.client.get("/api/metrics")
        assert resp.status == 400

        data = await resp.json()
        assert "missing required parameter: query" in data["error"]

    async def test_catchup_endpoint(self) -> None:
        """Test GET /api/catchup endpoint."""
        with patch(
            "herd_mcp.rest_server.catchup.execute", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"updates": [], "summary": "No updates"}

            resp = await self.client.get("/api/catchup")
            assert resp.status == 200

            data = await resp.json()
            assert "summary" in data

            # Verify execute was called
            mock.assert_called_once()

    async def test_decommission_endpoint(self) -> None:
        """Test POST /api/decommission endpoint."""
        with patch(
            "herd_mcp.rest_server.lifecycle.decommission", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"success": True, "message": "Decommissioned"}

            resp = await self.client.post(
                "/api/decommission", json={"agent_name": "grunt-001"}
            )
            assert resp.status == 200

            data = await resp.json()
            assert data["success"] is True

            # Verify decommission was called with correct args
            mock.assert_called_once()
            args = mock.call_args
            assert args[0][0] == "grunt-001"

    async def test_standdown_endpoint(self) -> None:
        """Test POST /api/standdown endpoint."""
        with patch(
            "herd_mcp.rest_server.lifecycle.standdown", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"success": True, "message": "Stood down"}

            resp = await self.client.post(
                "/api/standdown", json={"agent_name": "grunt-001"}
            )
            assert resp.status == 200

            data = await resp.json()
            assert data["success"] is True

            # Verify standdown was called with correct args
            mock.assert_called_once()
            args = mock.call_args
            assert args[0][0] == "grunt-001"

    async def test_harvest_endpoint(self) -> None:
        """Test POST /api/harvest endpoint."""
        with patch(
            "herd_mcp.rest_server.token_harvest.execute", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"records_written": 5, "total_cost": 0.15}

            resp = await self.client.post(
                "/api/harvest",
                json={
                    "agent_instance_code": "grunt-001",
                    "project_path": "/tmp/test",
                },
            )
            assert resp.status == 200

            data = await resp.json()
            assert data["records_written"] == 5

            # Verify execute was called with correct args
            mock.assert_called_once()
            args = mock.call_args
            assert args[1]["agent_instance_code"] == "grunt-001"
            assert args[1]["project_path"] == "/tmp/test"

    async def test_agent_identity_from_header(self) -> None:
        """Test agent identity resolution from X-Agent-Name header."""
        with patch(
            "herd_mcp.rest_server.status.execute", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"agents": []}

            resp = await self.client.get(
                "/api/status", headers={"X-Agent-Name": "wardenstein"}
            )
            assert resp.status == 200

            # Verify agent_name was passed from header
            mock.assert_called_once()
            args = mock.call_args
            assert args[0][1] == "wardenstein"

    @patch.dict(os.environ, {"HERD_AGENT_NAME": "shakesquill"})
    async def test_agent_identity_from_env(self) -> None:
        """Test agent identity resolution from HERD_AGENT_NAME env var."""
        with patch(
            "herd_mcp.rest_server.status.execute", new_callable=AsyncMock
        ) as mock:
            mock.return_value = {"agents": []}

            resp = await self.client.get("/api/status")
            assert resp.status == 200

            # Verify agent_name was passed from env
            mock.assert_called_once()
            args = mock.call_args
            assert args[0][1] == "shakesquill"

    async def test_tool_exception_returns_500(self) -> None:
        """Test that tool exceptions return 500 status."""
        with patch(
            "herd_mcp.rest_server.status.execute", new_callable=AsyncMock
        ) as mock:
            mock.side_effect = Exception("Database error")

            resp = await self.client.get("/api/status")
            assert resp.status == 500

            data = await resp.json()
            assert "Database error" in data["error"]

    async def test_invalid_json_returns_400(self) -> None:
        """Test that invalid JSON in request body returns 400."""
        resp = await self.client.post(
            "/api/log",
            data="not valid json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status == 400

        data = await resp.json()
        assert "invalid JSON" in data["error"]
