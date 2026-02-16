"""Smoke tests for the KuzuDB structural graph store.

Tests the core graph module (herd_mcp/graph.py) and the graph query
tool (herd_mcp/tools/graph.py) against a temporary database.
"""

from __future__ import annotations

import os
import shutil
import tempfile

import pytest

# Override HERD_KUZU_PATH before importing graph module
_test_dir = tempfile.mkdtemp(prefix="herd_graph_test_")
_test_kuzu_path = os.path.join(_test_dir, "test.kuzu")
os.environ["HERD_KUZU_PATH"] = _test_kuzu_path


@pytest.fixture(autouse=True)
def reset_graph_singletons():
    """Reset graph module singletons between tests."""
    import herd_mcp.graph as graph_mod

    graph_mod._graph_db = None
    graph_mod._schema_initialized = False
    # Ensure fresh path for each test
    os.environ["HERD_KUZU_PATH"] = _test_kuzu_path
    yield
    # Clean up the database after each test
    graph_mod._graph_db = None
    graph_mod._schema_initialized = False
    if os.path.exists(_test_kuzu_path):
        shutil.rmtree(_test_kuzu_path, ignore_errors=True)


class TestGraphPath:
    """Tests for get_graph_path()."""

    def test_explicit_path(self):
        """HERD_KUZU_PATH env var takes precedence."""
        from herd_mcp.graph import get_graph_path

        os.environ["HERD_KUZU_PATH"] = "/custom/path/graph.kuzu"
        assert get_graph_path() == "/custom/path/graph.kuzu"
        # Restore
        os.environ["HERD_KUZU_PATH"] = _test_kuzu_path

    def test_default_path(self):
        """Falls back to data/herd.kuzu under HERD_PROJECT_PATH."""
        from herd_mcp.graph import get_graph_path

        old = os.environ.pop("HERD_KUZU_PATH", None)
        os.environ["HERD_PROJECT_PATH"] = "/tmp/herd-test"
        try:
            assert get_graph_path() == "/tmp/herd-test/data/herd.kuzu"
        finally:
            if old:
                os.environ["HERD_KUZU_PATH"] = old
            os.environ.pop("HERD_PROJECT_PATH", None)


class TestGraphDatabase:
    """Tests for database creation and schema initialization."""

    def test_get_graph_db_returns_database(self):
        """get_graph_db() returns a kuzu.Database instance."""
        from herd_mcp.graph import get_graph_db

        db = get_graph_db()
        assert db is not None

    def test_get_graph_db_is_singleton(self):
        """get_graph_db() returns the same instance on repeated calls."""
        from herd_mcp.graph import get_graph_db

        db1 = get_graph_db()
        db2 = get_graph_db()
        assert db1 is db2

    def test_get_graph_conn_initializes_schema(self):
        """get_graph_conn() triggers schema creation."""
        import herd_mcp.graph as graph_mod

        assert graph_mod._schema_initialized is False
        conn = graph_mod.get_graph_conn()
        assert conn is not None
        assert graph_mod._schema_initialized is True

    def test_schema_is_idempotent(self):
        """ensure_graph_schema() can be called multiple times without error."""
        from herd_mcp.graph import ensure_graph_schema, get_graph_conn

        conn = get_graph_conn()
        # Call again -- should not raise
        ensure_graph_schema(conn)
        ensure_graph_schema(conn)


class TestNodeOperations:
    """Tests for merge_node()."""

    def test_merge_node_creates_node(self):
        """merge_node() creates a new node."""
        from herd_mcp.graph import merge_node, query_graph

        merge_node(
            "Agent",
            {
                "id": "mason-1",
                "code": "mason",
                "role": "backend",
                "status": "running",
                "team": "core",
                "host": "avalon",
            },
        )
        results = query_graph(
            "MATCH (a:Agent {id: $id}) RETURN a.code, a.role", {"id": "mason-1"}
        )
        assert len(results) == 1
        assert results[0]["a.code"] == "mason"
        assert results[0]["a.role"] == "backend"

    def test_merge_node_updates_existing(self):
        """merge_node() updates an existing node's properties."""
        from herd_mcp.graph import merge_node, query_graph

        merge_node(
            "Agent",
            {
                "id": "mason-1",
                "code": "mason",
                "role": "backend",
                "status": "running",
                "team": "core",
                "host": "avalon",
            },
        )
        merge_node(
            "Agent",
            {
                "id": "mason-1",
                "code": "mason",
                "role": "backend",
                "status": "completed",
                "team": "core",
                "host": "avalon",
            },
        )
        results = query_graph(
            "MATCH (a:Agent {id: $id}) RETURN a.status", {"id": "mason-1"}
        )
        assert len(results) == 1
        assert results[0]["a.status"] == "completed"

    def test_merge_node_requires_id(self):
        """merge_node() raises ValueError without id."""
        from herd_mcp.graph import merge_node

        with pytest.raises(ValueError, match="without 'id'"):
            merge_node("Agent", {"code": "mason"})

    def test_merge_decision_node(self):
        """merge_node() works for Decision node type."""
        from herd_mcp.graph import merge_node, query_graph

        merge_node(
            "Decision",
            {
                "id": "HDR-0035",
                "title": "KuzuDB structural graph store",
                "date": "2026-02-15",
                "status": "accepted",
                "scope": "core",
                "principle": "structural_relationships",
            },
        )
        results = query_graph("MATCH (d:Decision) RETURN d.id, d.title")
        assert len(results) == 1
        assert results[0]["d.id"] == "HDR-0035"


class TestEdgeOperations:
    """Tests for create_edge()."""

    def test_create_edge(self):
        """create_edge() creates a relationship between nodes."""
        from herd_mcp.graph import create_edge, merge_node, query_graph

        merge_node(
            "Agent",
            {
                "id": "mason-1",
                "code": "mason",
                "role": "backend",
                "status": "running",
                "team": "core",
                "host": "avalon",
            },
        )
        merge_node(
            "Decision",
            {
                "id": "HDR-0035",
                "title": "KuzuDB",
                "date": "2026-02-15",
                "status": "accepted",
                "scope": "core",
                "principle": "",
            },
        )

        create_edge("Decides", "Agent", "mason-1", "Decision", "HDR-0035")

        results = query_graph(
            "MATCH (a:Agent)-[r:Decides]->(d:Decision) "
            "RETURN a.code, d.id, r.created_at"
        )
        assert len(results) == 1
        assert results[0]["a.code"] == "mason"
        assert results[0]["d.id"] == "HDR-0035"
        assert results[0]["r.created_at"] is not None

    def test_create_edge_with_properties(self):
        """create_edge() supports extra properties on edges."""
        from herd_mcp.graph import create_edge, merge_node, query_graph

        merge_node(
            "Agent",
            {
                "id": "ward-1",
                "code": "ward",
                "role": "qa",
                "status": "running",
                "team": "core",
                "host": "avalon",
            },
        )
        merge_node(
            "Ticket",
            {
                "id": "DBC-100",
                "title": "Test ticket",
                "status": "in_progress",
                "priority": "normal",
            },
        )

        create_edge(
            "Reviews",
            "Agent",
            "ward-1",
            "Ticket",
            "DBC-100",
            properties={"verdict": "approve", "finding_count": 3},
        )

        results = query_graph(
            "MATCH (a:Agent)-[r:Reviews]->(t:Ticket) "
            "RETURN a.code, t.id, r.verdict, r.finding_count"
        )
        assert len(results) == 1
        assert results[0]["r.verdict"] == "approve"
        assert results[0]["r.finding_count"] == 3


class TestQueryGraph:
    """Tests for query_graph()."""

    def test_query_returns_list_of_dicts(self):
        """query_graph() returns results as list of dicts."""
        from herd_mcp.graph import merge_node, query_graph

        merge_node("Concept", {"id": "graph-db", "name": "Graph Database"})
        merge_node("Concept", {"id": "embedded-db", "name": "Embedded Database"})

        results = query_graph("MATCH (c:Concept) RETURN c.name ORDER BY c.name")
        assert isinstance(results, list)
        assert len(results) == 2
        assert all(isinstance(r, dict) for r in results)
        assert results[0]["c.name"] == "Embedded Database"
        assert results[1]["c.name"] == "Graph Database"

    def test_query_with_params(self):
        """query_graph() supports parameterized queries."""
        from herd_mcp.graph import merge_node, query_graph

        merge_node(
            "Agent",
            {
                "id": "steve-1",
                "code": "steve",
                "role": "leader",
                "status": "running",
                "team": "core",
                "host": "avalon",
            },
        )

        results = query_graph(
            "MATCH (a:Agent) WHERE a.code = $code RETURN a.id",
            {"code": "steve"},
        )
        assert len(results) == 1
        assert results[0]["a.id"] == "steve-1"

    def test_query_invalid_cypher_raises(self):
        """query_graph() raises RuntimeError on invalid Cypher."""
        from herd_mcp.graph import get_graph_conn, query_graph

        # Force schema init
        get_graph_conn()

        with pytest.raises(RuntimeError, match="KuzuDB query failed"):
            query_graph("THIS IS NOT VALID CYPHER")

    def test_empty_result(self):
        """query_graph() returns empty list when no matches."""
        from herd_mcp.graph import get_graph_conn, merge_node, query_graph

        get_graph_conn()
        # Insert one node so we know the table has data
        merge_node(
            "Agent",
            {
                "id": "real-agent",
                "code": "mason",
                "role": "backend",
                "status": "active",
                "team": "",
                "host": "",
            },
        )
        # Query for a non-matching value — should return empty
        results = query_graph(
            "MATCH (a:Agent) WHERE a.code = $code RETURN a.id",
            {"code": "does-not-exist"},
        )
        assert results == []


class TestIsAvailable:
    """Tests for is_available()."""

    def test_is_available_returns_true(self):
        """is_available() returns True when kuzu is installed."""
        from herd_mcp.graph import is_available

        assert is_available() is True


class TestGraphTool:
    """Tests for the graph query tool (herd_mcp/tools/graph.py)."""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """Tool execute() returns results on success."""
        from herd_mcp.graph import merge_node
        from herd_mcp.tools.graph import execute

        merge_node(
            "Repository", {"id": "herd-core", "name": "herd-core", "org": "herd-ag"}
        )

        result = await execute("MATCH (r:Repository) RETURN r.name, r.org")

        assert "error" not in result
        assert result["count"] == 1
        assert result["results"][0]["r.name"] == "herd-core"

    @pytest.mark.asyncio
    async def test_execute_invalid_query(self):
        """Tool execute() returns error dict on bad query."""
        from herd_mcp.graph import get_graph_conn
        from herd_mcp.tools.graph import execute

        get_graph_conn()

        result = await execute("NOT VALID CYPHER")

        assert "error" in result
        assert "KuzuDB query failed" in result["error"]


class TestAllNodeTypes:
    """Verify all 7 node types can be created."""

    def test_all_node_types(self):
        """All 7 node types accept merges."""
        from herd_mcp.graph import merge_node, query_graph

        merge_node(
            "Decision",
            {
                "id": "d1",
                "title": "Test",
                "date": "2026-01-01",
                "status": "accepted",
                "scope": "core",
                "principle": "",
            },
        )
        merge_node(
            "Agent",
            {
                "id": "a1",
                "code": "test",
                "role": "backend",
                "status": "running",
                "team": "core",
                "host": "avalon",
            },
        )
        merge_node(
            "Ticket",
            {
                "id": "t1",
                "title": "Test ticket",
                "status": "todo",
                "priority": "normal",
            },
        )
        merge_node("File", {"id": "f1", "path": "src/main.py", "repo": "herd-core"})
        merge_node("Repository", {"id": "r1", "name": "herd-core", "org": "herd-ag"})
        merge_node(
            "Session",
            {"id": "s1", "agent": "mason", "started_at": "2026-02-15T00:00:00Z"},
        )
        merge_node("Concept", {"id": "c1", "name": "graph"})

        for label in (
            "Decision",
            "Agent",
            "Ticket",
            "File",
            "Repository",
            "Session",
            "Concept",
        ):
            results = query_graph(f"MATCH (n:{label}) RETURN count(n) AS cnt")
            assert results[0]["cnt"] >= 1, f"Expected at least 1 {label} node"


class TestAllEdgeTypes:
    """Verify all 12 edge types can be created."""

    def test_standard_edge_types(self):
        """All 11 standard edge types can be created."""
        from herd_mcp.graph import create_edge, merge_node

        # Create nodes for all edge types
        merge_node(
            "Agent",
            {
                "id": "a1",
                "code": "mason",
                "role": "backend",
                "status": "running",
                "team": "core",
                "host": "avalon",
            },
        )
        merge_node(
            "Agent",
            {
                "id": "a2",
                "code": "steve",
                "role": "leader",
                "status": "running",
                "team": "core",
                "host": "avalon",
            },
        )
        merge_node(
            "Decision",
            {
                "id": "d1",
                "title": "D1",
                "date": "2026-01-01",
                "status": "accepted",
                "scope": "core",
                "principle": "",
            },
        )
        merge_node(
            "Decision",
            {
                "id": "d2",
                "title": "D2",
                "date": "2026-01-02",
                "status": "accepted",
                "scope": "core",
                "principle": "",
            },
        )
        merge_node(
            "Ticket",
            {"id": "t1", "title": "T1", "status": "todo", "priority": "normal"},
        )
        merge_node(
            "Ticket",
            {"id": "t2", "title": "T2", "status": "blocked", "priority": "high"},
        )
        merge_node("File", {"id": "f1", "path": "src/main.py", "repo": "herd-core"})
        merge_node("Repository", {"id": "r1", "name": "herd-core", "org": "herd-ag"})

        # Test each edge type
        create_edge("Decides", "Agent", "a1", "Decision", "d1")
        create_edge("Implements", "Ticket", "t1", "Decision", "d1")
        create_edge(
            "Touches", "Agent", "a1", "File", "f1", properties={"session_id": "s1"}
        )
        create_edge(
            "Reviews",
            "Agent",
            "a1",
            "Ticket",
            "t1",
            properties={"verdict": "approve", "finding_count": 0},
        )
        create_edge("Supersedes", "Decision", "d2", "Decision", "d1")
        create_edge("DependsOn", "Decision", "d1", "Decision", "d2")
        create_edge("SpawnedBy", "Agent", "a1", "Agent", "a2")
        create_edge("AssignedTo", "Ticket", "t1", "Agent", "a1")
        create_edge("BlockedBy", "Ticket", "t2", "Ticket", "t1")
        create_edge("CompletedBy", "Ticket", "t1", "Agent", "a1")
        create_edge("BelongsTo", "File", "f1", "Repository", "r1")

    def test_tagged_with_edge(self):
        """TaggedWith REL TABLE GROUP supports multiple source types."""
        from herd_mcp.graph import create_edge, merge_node, query_graph

        merge_node(
            "Decision",
            {
                "id": "d1",
                "title": "D1",
                "date": "2026-01-01",
                "status": "accepted",
                "scope": "core",
                "principle": "",
            },
        )
        merge_node(
            "Agent",
            {
                "id": "a1",
                "code": "mason",
                "role": "backend",
                "status": "running",
                "team": "core",
                "host": "avalon",
            },
        )
        merge_node(
            "Ticket",
            {"id": "t1", "title": "T1", "status": "todo", "priority": "normal"},
        )
        merge_node("Concept", {"id": "c1", "name": "graph"})

        # TaggedWith from Decision -> Concept
        create_edge("TaggedWith", "Decision", "d1", "Concept", "c1")

        # TaggedWith from Agent -> Concept
        create_edge("TaggedWith", "Agent", "a1", "Concept", "c1")

        # TaggedWith from Ticket -> Concept
        create_edge("TaggedWith", "Ticket", "t1", "Concept", "c1")

        # Verify all three edges exist
        results = query_graph(
            "MATCH (n)-[:TaggedWith]->(c:Concept {id: 'c1'}) RETURN count(n) AS cnt"
        )
        assert results[0]["cnt"] == 3
