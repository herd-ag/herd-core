"""KuzuDB structural graph store for agent relationship tracking.

Per HDR-0035: KuzuDB stores the structural graph of relationships between
agents, decisions, tickets, files, repositories, sessions, and concepts.
This is the third embedded store alongside DuckDB (operational) and
LanceDB (semantic).

Connection management, schema creation, and query/mutation helpers live here.
All graph operations fail gracefully -- they never break the MCP server.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Node table definitions: (table_name, {column_name: column_type}, primary_key)
_NODE_TABLES: list[tuple[str, dict[str, str], str]] = [
    (
        "Decision",
        {
            "id": "STRING",
            "title": "STRING",
            "date": "STRING",
            "status": "STRING",
            "scope": "STRING",
            "principle": "STRING",
        },
        "id",
    ),
    (
        "Agent",
        {
            "id": "STRING",
            "code": "STRING",
            "role": "STRING",
            "status": "STRING",
            "team": "STRING",
            "host": "STRING",
        },
        "id",
    ),
    (
        "Ticket",
        {
            "id": "STRING",
            "title": "STRING",
            "status": "STRING",
            "priority": "STRING",
        },
        "id",
    ),
    (
        "File",
        {
            "id": "STRING",
            "path": "STRING",
            "repo": "STRING",
        },
        "id",
    ),
    (
        "Repository",
        {
            "id": "STRING",
            "name": "STRING",
            "org": "STRING",
        },
        "id",
    ),
    (
        "Session",
        {
            "id": "STRING",
            "agent": "STRING",
            "started_at": "STRING",
        },
        "id",
    ),
    (
        "Concept",
        {
            "id": "STRING",
            "name": "STRING",
        },
        "id",
    ),
]

# Edge table definitions: (table_name, from_label, to_label, extra_columns)
# extra_columns is a dict of {column_name: column_type} beyond the standard created_at
_EDGE_TABLES: list[tuple[str, str, str, dict[str, str]]] = [
    ("Decides", "Agent", "Decision", {}),
    ("Implements", "Ticket", "Decision", {}),
    ("Touches", "Agent", "File", {"session_id": "STRING"}),
    ("Reviews", "Agent", "Ticket", {"verdict": "STRING", "finding_count": "INT64"}),
    ("Supersedes", "Decision", "Decision", {}),
    ("DependsOn", "Decision", "Decision", {}),
    ("SpawnedBy", "Agent", "Agent", {}),
    ("AssignedTo", "Ticket", "Agent", {}),
    ("BlockedBy", "Ticket", "Ticket", {}),
    ("CompletedBy", "Ticket", "Agent", {}),
    ("BelongsTo", "File", "Repository", {}),
]

# TaggedWith is a REL TABLE GROUP -- multiple source node types to Concept
_TAGGED_WITH_SOURCES = ["Decision", "Agent", "Ticket"]

# Singletons -- lazy-initialized on first use
_graph_db = None
_schema_initialized = False


def get_graph_path() -> str:
    """Get the KuzuDB database path from environment.

    Reads HERD_KUZU_PATH env var. Falls back to data/herd.kuzu under
    HERD_PROJECT_PATH (or cwd if that is also unset).

    Returns:
        Absolute path string for the KuzuDB database directory.
    """
    explicit = os.getenv("HERD_KUZU_PATH")
    if explicit:
        return explicit

    project_path = os.getenv("HERD_PROJECT_PATH", os.getcwd())
    return os.path.join(project_path, "data", "herd.kuzu")


def get_graph_db():
    """Get or create the KuzuDB database instance (singleton).

    Returns:
        kuzu.Database instance.

    Raises:
        ImportError: If kuzu is not installed.
    """
    global _graph_db

    if _graph_db is not None:
        return _graph_db

    try:
        import kuzu
    except ImportError:
        logger.warning(
            "kuzu is not installed. Structural graph store is unavailable. "
            "Install with: pip install 'kuzu>=0.11'"
        )
        raise

    path = get_graph_path()
    logger.info("Opening KuzuDB at %s", path)

    # Ensure parent directory exists
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    _graph_db = kuzu.Database(path)
    return _graph_db


def get_graph_conn():
    """Get a KuzuDB connection for executing queries.

    Creates a new connection from the singleton database instance.
    Also ensures the schema is initialized on first use.

    Returns:
        kuzu.Connection instance.

    Raises:
        ImportError: If kuzu is not installed.
    """
    import kuzu

    db = get_graph_db()
    conn = kuzu.Connection(db)

    global _schema_initialized
    if not _schema_initialized:
        ensure_graph_schema(conn)
        _schema_initialized = True

    return conn


def ensure_graph_schema(conn=None) -> None:
    """Create all node and edge tables if they do not already exist.

    Idempotent -- safe to call multiple times. Uses IF NOT EXISTS on
    every CREATE statement.

    Args:
        conn: Optional kuzu.Connection. If None, one is created from
              the singleton database.
    """
    if conn is None:
        import kuzu

        db = get_graph_db()
        conn = kuzu.Connection(db)

    # Create node tables
    for table_name, columns, pk in _NODE_TABLES:
        col_defs = ", ".join(f"{name} {dtype}" for name, dtype in columns.items())
        ddl = (
            f"CREATE NODE TABLE IF NOT EXISTS {table_name}"
            f"({col_defs}, PRIMARY KEY ({pk}))"
        )
        try:
            conn.execute(ddl)
            logger.debug("Ensured node table: %s", table_name)
        except Exception as exc:
            logger.warning(
                "Failed to create node table %s: %s. DDL was: %s",
                table_name,
                exc,
                ddl,
            )

    # Create standard edge tables (single FROM -> TO)
    for table_name, from_label, to_label, extra_cols in _EDGE_TABLES:
        all_cols = {"created_at": "STRING"}
        all_cols.update(extra_cols)
        col_defs = ", ".join(f"{name} {dtype}" for name, dtype in all_cols.items())
        ddl = (
            f"CREATE REL TABLE IF NOT EXISTS {table_name}"
            f"(FROM {from_label} TO {to_label}, {col_defs})"
        )
        try:
            conn.execute(ddl)
            logger.debug("Ensured edge table: %s", table_name)
        except Exception as exc:
            logger.warning(
                "Failed to create edge table %s: %s. DDL was: %s",
                table_name,
                exc,
                ddl,
            )

    # Create TaggedWith as a REL TABLE GROUP (multiple source types -> Concept)
    _create_tagged_with_group(conn)

    logger.info("KuzuDB graph schema initialized (7 node tables, 12 edge types)")


def _create_tagged_with_group(conn) -> None:
    """Create the TaggedWith REL TABLE GROUP for multi-source tagging.

    TaggedWith connects Decision, Agent, and Ticket nodes to Concept nodes.
    Uses REL TABLE GROUP to allow multiple source node types.

    Args:
        conn: kuzu.Connection instance.
    """
    entries = []
    for src in _TAGGED_WITH_SOURCES:
        entries.append(f"FROM {src} TO Concept")

    entries_str = ", ".join(entries)
    ddl = (
        f"CREATE REL TABLE GROUP IF NOT EXISTS TaggedWith"
        f"({entries_str}, created_at STRING)"
    )
    try:
        conn.execute(ddl)
        logger.debug("Ensured edge table group: TaggedWith")
    except Exception as exc:
        logger.warning(
            "Failed to create TaggedWith REL TABLE GROUP: %s. DDL was: %s",
            exc,
            ddl,
        )


def query_graph(cypher: str, params: dict | None = None) -> list[dict]:
    """Execute a Cypher query and return results as a list of dicts.

    Column names are derived from the query's RETURN clause. Each row
    is returned as a dict mapping column name to value.

    Args:
        cypher: Cypher query string.
        params: Optional dict of query parameters (referenced as $name
                in the Cypher query).

    Returns:
        List of dicts, one per result row.

    Raises:
        RuntimeError: If the query fails (includes the original error message).
    """
    conn = get_graph_conn()

    try:
        if params:
            result = conn.execute(cypher, params)
        else:
            result = conn.execute(cypher)
    except Exception as exc:
        raise RuntimeError(f"KuzuDB query failed: {exc}. Query was: {cypher}") from exc

    # Extract column names from the result
    columns = result.get_column_names()
    rows: list[dict] = []

    while result.has_next():
        values = result.get_next()
        row = dict(zip(columns, values))
        rows.append(row)

    return rows


def merge_node(label: str, properties: dict) -> None:
    """Create or update a node using MERGE for idempotency.

    The properties dict must include the primary key field (typically 'id').
    If a node with the same primary key exists, its non-key properties
    are updated via ON MATCH SET. If it does not exist, it is created
    with all properties via ON CREATE SET.

    Args:
        label: Node table name (e.g., "Agent", "Decision", "Ticket").
        properties: Dict of property name -> value. Must include the
                    primary key ('id' for all tables).

    Raises:
        ValueError: If 'id' is not in properties.
    """
    if "id" not in properties:
        raise ValueError(
            f"Cannot merge node of type '{label}' without 'id' property. "
            f"Provided keys: {list(properties.keys())}"
        )

    conn = get_graph_conn()

    # Build the MERGE statement
    node_id = properties["id"]
    non_key_props = {k: v for k, v in properties.items() if k != "id"}

    if non_key_props:
        set_clause_parts = []
        for key in non_key_props:
            set_clause_parts.append(f"n.{key} = ${key}")
        set_clause = ", ".join(set_clause_parts)

        cypher = (
            f"MERGE (n:{label} {{id: $id}}) "
            f"ON CREATE SET {set_clause} "
            f"ON MATCH SET {set_clause}"
        )
    else:
        cypher = f"MERGE (n:{label} {{id: $id}})"

    params = {"id": node_id}
    params.update(non_key_props)

    try:
        conn.execute(cypher, params)
        logger.debug("Merged %s node: %s", label, node_id)
    except Exception as exc:
        logger.warning(
            "Failed to merge %s node (id=%s): %s. Query was: %s",
            label,
            node_id,
            exc,
            cypher,
        )


def create_edge(
    rel_type: str,
    from_label: str,
    from_id: str,
    to_label: str,
    to_id: str,
    properties: dict | None = None,
) -> None:
    """Create an edge between two existing nodes.

    Automatically adds a created_at timestamp if not provided in properties.

    Args:
        rel_type: Relationship table name (e.g., "Decides", "Implements").
        from_label: Source node table name (e.g., "Agent").
        from_id: Primary key of the source node.
        to_label: Target node table name (e.g., "Decision").
        to_id: Primary key of the target node.
        properties: Optional dict of edge properties beyond created_at.
    """
    conn = get_graph_conn()

    edge_props = {"created_at": datetime.now(timezone.utc).isoformat()}
    if properties:
        edge_props.update(properties)

    # Build the property assignment clause
    prop_assignments = []
    params: dict = {"from_id": from_id, "to_id": to_id}

    for key, value in edge_props.items():
        param_name = f"prop_{key}"
        prop_assignments.append(f"{key}: ${param_name}")
        params[param_name] = value

    props_str = ", ".join(prop_assignments)

    cypher = (
        f"MATCH (a:{from_label} {{id: $from_id}}), (b:{to_label} {{id: $to_id}}) "
        f"CREATE (a)-[:{rel_type} {{{props_str}}}]->(b)"
    )

    try:
        conn.execute(cypher, params)
        logger.debug(
            "Created %s edge: %s(%s) -> %s(%s)",
            rel_type,
            from_label,
            from_id,
            to_label,
            to_id,
        )
    except Exception as exc:
        logger.warning(
            "Failed to create %s edge from %s(%s) to %s(%s): %s. Query was: %s",
            rel_type,
            from_label,
            from_id,
            to_label,
            to_id,
            exc,
            cypher,
        )


def is_available() -> bool:
    """Check whether the KuzuDB graph store is operational.

    Returns True if kuzu is importable and the database can be opened.
    Never raises -- returns False on any failure.

    Returns:
        True if graph store is available, False otherwise.
    """
    try:
        get_graph_conn()
        return True
    except Exception:
        return False
