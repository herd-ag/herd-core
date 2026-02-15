"""Integration tests for Herd MCP listener integration and identity resolution."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest import mock

import pytest
from herd_mcp import identity
from herd_mcp.db import connection


@pytest.fixture
def temp_db():
    """Create a temporary in-memory database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.duckdb")
        with connection(db_path) as conn:
            # Schema is initialized by get_connection
            yield conn


@pytest.fixture
def seeded_db(temp_db):
    """Create a seeded database with agent and model definitions."""
    # Insert test agents
    temp_db.execute("""
        INSERT INTO herd.agent_def
          (agent_code, agent_role, agent_status, agent_branch_prefix,
           agent_email, default_model_code, created_at, modified_at)
        VALUES
          ('grunt', 'backend', 'active', 'herd/grunt',
           'grunt@herd.local', 'claude-sonnet-4-5', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
          ('pikasso', 'frontend', 'active', 'herd/pikasso',
           'pikasso@herd.local', 'claude-sonnet-4-5', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """)

    # Insert test models
    temp_db.execute("""
        INSERT INTO herd.model_def
          (model_code, model_provider, model_context_window,
           model_input_cost_per_m, model_output_cost_per_m,
           model_cache_read_cost_per_m, model_cache_create_cost_per_m,
           created_at, modified_at)
        VALUES
          ('claude-sonnet-4-5', 'anthropic', 200000, 3.00, 15.00, 0.30, 3.75,
           CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
          ('claude-haiku-4', 'anthropic', 200000, 0.80, 4.00, 0.08, 1.00,
           CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """)

    return temp_db


class TestIdentityResolution:
    """Tests for identity resolution functionality."""

    def test_get_agent_name_from_env_returns_none_when_not_set(self):
        """Test that get_agent_name_from_env returns None when variable not set."""
        with mock.patch.dict(os.environ, {}, clear=True):
            assert identity.get_agent_name_from_env() is None

    def test_get_agent_name_from_env_returns_value_when_set(self):
        """Test that get_agent_name_from_env returns value when variable is set."""
        with mock.patch.dict(os.environ, {"HERD_AGENT_NAME": "grunt"}):
            assert identity.get_agent_name_from_env() == "grunt"

    def test_resolve_agent_code_returns_none_when_agent_not_found(self, seeded_db):
        """Test that resolve_agent_code returns None for unknown agent."""
        with mock.patch("herd_mcp.identity.connection") as mock_conn:
            mock_conn.return_value.__enter__.return_value = seeded_db
            result = identity.resolve_agent_code("unknown-agent")
            assert result is None

    def test_resolve_agent_code_returns_code_when_agent_found(self, seeded_db):
        """Test that resolve_agent_code returns agent_code for known agent."""
        with mock.patch("herd_mcp.identity.connection") as mock_conn:
            mock_conn.return_value.__enter__.return_value = seeded_db
            result = identity.resolve_agent_code("grunt")
            assert result == "grunt"

    def test_resolve_or_create_agent_instance_creates_new_instance(self, seeded_db):
        """Test that resolve_or_create_agent_instance creates a new instance."""
        with mock.patch("herd_mcp.identity.connection") as mock_conn:
            mock_conn.return_value.__enter__.return_value = seeded_db

            instance_code = identity.resolve_or_create_agent_instance(
                "grunt",
                model_code="claude-sonnet-4-5",
            )

            assert instance_code is not None
            assert instance_code.startswith("inst-")

            # Verify instance was created
            result = seeded_db.execute(
                """
                SELECT agent_code, model_code
                FROM herd.agent_instance
                WHERE agent_instance_code = ?
                """,
                [instance_code],
            ).fetchone()

            assert result is not None
            assert result[0] == "grunt"
            assert result[1] == "claude-sonnet-4-5"

            # Verify lifecycle activity was logged
            activity = seeded_db.execute(
                """
                SELECT lifecycle_event_type
                FROM herd.agent_instance_lifecycle_activity
                WHERE agent_instance_code = ?
                """,
                [instance_code],
            ).fetchone()

            assert activity is not None
            assert activity[0] == "spawned"

    def test_resolve_or_create_agent_instance_returns_existing_instance(
        self, seeded_db
    ):
        """Test that resolve_or_create_agent_instance returns existing active instance."""
        with mock.patch("herd_mcp.identity.connection") as mock_conn:
            mock_conn.return_value.__enter__.return_value = seeded_db

            # Create first instance
            instance1 = identity.resolve_or_create_agent_instance("grunt")

            # Try to create second instance - should return first
            instance2 = identity.resolve_or_create_agent_instance("grunt")

            assert instance1 == instance2

            # Verify only one instance exists
            count = seeded_db.execute("""
                SELECT COUNT(*)
                FROM herd.agent_instance
                WHERE agent_code = 'grunt'
                  AND agent_instance_ended_at IS NULL
                """).fetchone()[0]

            assert count == 1

    def test_resolve_or_create_agent_instance_uses_default_model(self, seeded_db):
        """Test that resolve_or_create_agent_instance uses default model when not specified."""
        with mock.patch("herd_mcp.identity.connection") as mock_conn:
            mock_conn.return_value.__enter__.return_value = seeded_db

            instance_code = identity.resolve_or_create_agent_instance("grunt")

            result = seeded_db.execute(
                """
                SELECT model_code
                FROM herd.agent_instance
                WHERE agent_instance_code = ?
                """,
                [instance_code],
            ).fetchone()

            assert result[0] == "claude-sonnet-4-5"

    def test_resolve_identity_returns_full_identity(self, seeded_db):
        """Test that resolve_identity returns complete identity information."""
        with mock.patch.dict(os.environ, {"HERD_AGENT_NAME": "grunt"}):
            with mock.patch("herd_mcp.identity.connection") as mock_conn:
                mock_conn.return_value.__enter__.return_value = seeded_db

                result = identity.resolve_identity()

                assert result["is_resolved"] is True
                assert result["agent_name"] == "grunt"
                assert result["agent_code"] == "grunt"
                assert result["agent_instance_code"] is not None
                assert result["agent_instance_code"].startswith("inst-")
                assert "error" not in result

    def test_resolve_identity_returns_error_when_env_not_set(self):
        """Test that resolve_identity returns error when HERD_AGENT_NAME not set."""
        with mock.patch.dict(os.environ, {}, clear=True):
            result = identity.resolve_identity()

            assert result["is_resolved"] is False
            assert result["agent_name"] is None
            assert result["agent_code"] is None
            assert result["agent_instance_code"] is None
            assert "error" in result
            assert "HERD_AGENT_NAME not set" in result["error"]

    def test_resolve_identity_returns_error_when_agent_not_found(self, seeded_db):
        """Test that resolve_identity returns error when agent not in database."""
        with mock.patch.dict(os.environ, {"HERD_AGENT_NAME": "unknown-agent"}):
            with mock.patch("herd_mcp.identity.connection") as mock_conn:
                mock_conn.return_value.__enter__.return_value = seeded_db

                result = identity.resolve_identity()

                assert result["is_resolved"] is False
                assert result["agent_name"] == "unknown-agent"
                assert result["agent_code"] is None
                assert result["agent_instance_code"] is None
                assert "error" in result
                assert "not found in agent_def" in result["error"]


class TestSeedScript:
    """Tests for seed_db.py script idempotency."""

    def test_seed_script_is_idempotent_for_agents(self, temp_db):
        """Test that running seed script multiple times doesn't create duplicates."""
        # Import seed functions
        import sys
        from pathlib import Path

        scripts_path = Path(__file__).parent.parent / "scripts"
        sys.path.insert(0, str(scripts_path))

        # Import after path is set
        import seed_db

        # First run
        with mock.patch("herd_mcp.db.connection") as mock_conn:
            mock_conn.return_value.__enter__.return_value = temp_db
            seed_db.seed_agent_def(temp_db)

        count1 = temp_db.execute("SELECT COUNT(*) FROM herd.agent_def").fetchone()[0]

        # Second run
        with mock.patch("herd_mcp.db.connection") as mock_conn:
            mock_conn.return_value.__enter__.return_value = temp_db
            seed_db.seed_agent_def(temp_db)

        count2 = temp_db.execute("SELECT COUNT(*) FROM herd.agent_def").fetchone()[0]

        # Counts should be the same (no duplicates)
        assert count1 == count2
        assert count1 == 6  # mini-mao, grunt, pikasso, wardenstein, shakesquill, gauss

    def test_seed_script_is_idempotent_for_models(self, temp_db):
        """Test that running seed script multiple times doesn't create duplicate models."""
        import sys
        from pathlib import Path

        scripts_path = Path(__file__).parent.parent / "scripts"
        sys.path.insert(0, str(scripts_path))

        import seed_db

        # First run
        with mock.patch("herd_mcp.db.connection") as mock_conn:
            mock_conn.return_value.__enter__.return_value = temp_db
            seed_db.seed_model_def(temp_db)

        count1 = temp_db.execute("SELECT COUNT(*) FROM herd.model_def").fetchone()[0]

        # Second run
        with mock.patch("herd_mcp.db.connection") as mock_conn:
            mock_conn.return_value.__enter__.return_value = temp_db
            seed_db.seed_model_def(temp_db)

        count2 = temp_db.execute("SELECT COUNT(*) FROM herd.model_def").fetchone()[0]

        # Counts should be the same (no duplicates)
        assert count1 == count2
        assert count1 == 4  # opus-4-6, sonnet-4-5, sonnet-4, haiku-4

    def test_seed_script_updates_existing_records(self, temp_db):
        """Test that seed script updates existing records with new values."""
        import sys
        from pathlib import Path

        scripts_path = Path(__file__).parent.parent / "scripts"
        sys.path.insert(0, str(scripts_path))

        import seed_db

        # First insert
        temp_db.execute("""
            INSERT INTO herd.agent_def
              (agent_code, agent_role, agent_status, agent_branch_prefix,
               agent_email, default_model_code, created_at, modified_at)
            VALUES
              ('grunt', 'backend', 'active', 'old/prefix',
               'old@email.com', 'claude-haiku-4', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """)

        # Run seed script
        with mock.patch("herd_mcp.db.connection") as mock_conn:
            mock_conn.return_value.__enter__.return_value = temp_db
            seed_db.seed_agent_def(temp_db)

        # Verify record was updated
        result = temp_db.execute("""
            SELECT agent_branch_prefix, agent_email, default_model_code
            FROM herd.agent_def
            WHERE agent_code = 'grunt'
            """).fetchone()

        assert result[0] == "herd/grunt"  # Updated prefix
        assert result[1] == "grunt@herd.local"  # Updated email
        assert result[2] == "claude-sonnet-4-5"  # Updated model


class TestMCPConfiguration:
    """Tests for MCP configuration template."""

    def test_mcp_config_exists(self):
        """Test that mcp-config.json template exists."""
        config_path = Path(__file__).parent.parent / "mcp-config.json"
        assert config_path.exists()

    def test_mcp_config_is_valid_json(self):
        """Test that mcp-config.json is valid JSON."""
        import json

        config_path = Path(__file__).parent.parent / "mcp-config.json"
        with open(config_path) as f:
            config = json.load(f)

        assert "mcpServers" in config
        assert "herd" in config["mcpServers"]
        assert "command" in config["mcpServers"]["herd"]
        assert "args" in config["mcpServers"]["herd"]
        assert "env" in config["mcpServers"]["herd"]

    def test_mcp_config_has_required_env_vars(self):
        """Test that mcp-config.json includes required environment variables."""
        import json

        config_path = Path(__file__).parent.parent / "mcp-config.json"
        with open(config_path) as f:
            config = json.load(f)

        env = config["mcpServers"]["herd"]["env"]
        assert "HERD_AGENT_NAME" in env
        assert "HERD_DB_PATH" in env
