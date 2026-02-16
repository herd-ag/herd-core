"""LanceDB semantic memory for agent cross-session recall.

Per HDR-0033: LanceDB stores agent-queryable memory as a single `memories`
table with metadata filters. Markdown files remain the human-readable
system of record.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Valid memory types per HDR-0033, HDR-0042, HDR-0043
MEMORY_TYPES = frozenset(
    {
        "session_summary",
        "decision_context",
        "pattern",
        "preference",
        "thread",
        "lesson",
        "observation",
    }
)

# Embedding model config
_EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
_EMBEDDING_DIMENSION = 384

# Singletons — lazy-initialized on first use
_db_connection = None
_embedding_model = None


def get_lance_path() -> str:
    """Get the LanceDB database path from environment.

    Returns:
        Path string for the LanceDB database directory.
    """
    return os.getenv("HERD_LANCE_PATH", "data/herd.lance")


def get_memory_store():
    """Open or create a LanceDB database connection (singleton).

    Returns:
        LanceDB connection object.

    Raises:
        ImportError: If lancedb is not installed (logged as warning).
    """
    global _db_connection

    if _db_connection is not None:
        return _db_connection

    try:
        import lancedb
    except ImportError:
        logger.warning(
            "lancedb is not installed. Semantic memory is unavailable. "
            "Install with: pip install 'lancedb>=0.6'"
        )
        raise

    path = get_lance_path()
    logger.info("Opening LanceDB at %s", path)
    _db_connection = lancedb.connect(path)
    return _db_connection


def _get_embedding_model():
    """Lazy-load the sentence-transformers embedding model (singleton).

    Returns:
        SentenceTransformer model instance.

    Raises:
        ImportError: If sentence-transformers is not installed.
    """
    global _embedding_model

    if _embedding_model is not None:
        return _embedding_model

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        logger.warning(
            "sentence-transformers is not installed. Embedding is unavailable. "
            "Install with: pip install 'sentence-transformers>=2.0'"
        )
        raise

    logger.info("Loading embedding model: %s", _EMBEDDING_MODEL_NAME)
    _embedding_model = SentenceTransformer(_EMBEDDING_MODEL_NAME)
    return _embedding_model


def embed_text(text: str) -> list[float]:
    """Generate an embedding vector for the given text.

    Uses the all-MiniLM-L6-v2 model (384 dimensions, fast, good quality).

    Args:
        text: The text to embed.

    Returns:
        List of floats representing the embedding vector.
    """
    model = _get_embedding_model()
    embedding = model.encode(text, convert_to_numpy=True)
    return embedding.tolist()


def ensure_memories_table(db):
    """Create the memories table if it does not already exist.

    Schema per HDR-0033:
        id, project, repo, session_id, agent, memory_type, content,
        summary, vector, created_at, metadata

    The summary field holds the text that was actually embedded. When
    present, semantic search matches against the summary rather than
    the full content, improving retrieval quality.

    If an existing table is missing the summary column (pre-summary-embed
    schema), it is dropped and recreated.

    Args:
        db: LanceDB connection from get_memory_store().

    Returns:
        The LanceDB table object.
    """
    import pyarrow as pa

    table_name = "memories"

    if table_name in db.table_names():
        existing = db.open_table(table_name)
        column_names = [field.name for field in existing.schema]
        if "summary" not in column_names:
            logger.info(
                "Existing memories table missing 'summary' column; "
                "dropping and recreating with updated schema"
            )
            db.drop_table(table_name)
        else:
            return existing

    schema = pa.schema(
        [
            pa.field("id", pa.utf8()),
            pa.field("project", pa.utf8()),
            pa.field("repo", pa.utf8()),
            pa.field("org", pa.utf8()),
            pa.field("team", pa.utf8()),
            pa.field("host", pa.utf8()),
            pa.field("session_id", pa.utf8()),
            pa.field("agent", pa.utf8()),
            pa.field("memory_type", pa.utf8()),
            pa.field("content", pa.utf8()),
            pa.field("summary", pa.utf8()),
            pa.field("vector", pa.list_(pa.float32(), list_size=_EMBEDDING_DIMENSION)),
            pa.field("created_at", pa.utf8()),
            pa.field("metadata", pa.utf8()),
        ]
    )

    logger.info("Creating memories table in LanceDB")
    table = db.create_table(table_name, schema=schema)
    return table


def store_memory(
    project: str,
    agent: str,
    memory_type: str,
    content: str,
    session_id: str,
    summary: str | None = None,
    repo: str | None = None,
    org: str | None = None,
    team: str | None = None,
    host: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Store a memory in the LanceDB memories table.

    The summary field controls what text is embedded for semantic search.
    When provided, the summary is embedded instead of content, allowing
    callers to store verbose content while embedding a focused description
    that retrieves better. The full content remains stored and returned
    on recall.

    Args:
        project: Project identifier (e.g., "herd", "dbt-conceptual").
        agent: Agent name (e.g., "steve", "mason").
        memory_type: One of: session_summary, decision_context, pattern,
                     preference, thread.
        content: The full text content to store and retrieve.
        session_id: Session identifier (e.g., "steve-2026-02-15").
        summary: Optional focused text to embed for semantic search.
                 If None, content is embedded instead (backward compatible).
        repo: Optional repository name (null for cross-repo memories).
        org: Optional organization scope (e.g., "herd-ag").
        team: Optional team scope (e.g., "backend").
        host: Optional host/machine scope (e.g., "ci-runner-1").
        metadata: Optional dict of flexible metadata (hdr_number, ticket_id,
                  principle, etc.). Stored as JSON string.

    Returns:
        The UUID string of the stored memory.

    Raises:
        ValueError: If memory_type is not one of the valid types.
    """
    if memory_type not in MEMORY_TYPES:
        raise ValueError(
            f"Invalid memory_type '{memory_type}'. Must be one of: "
            f"{', '.join(sorted(MEMORY_TYPES))}"
        )

    db = get_memory_store()
    table = ensure_memories_table(db)

    memory_id = str(uuid.uuid4())
    embed_source = summary if summary else content
    vector = embed_text(embed_source)
    now = datetime.now(timezone.utc).isoformat()
    metadata_str = json.dumps(metadata) if metadata else "{}"

    record = {
        "id": memory_id,
        "project": project,
        "repo": repo or "",
        "org": org or "",
        "team": team or "",
        "host": host or "",
        "session_id": session_id,
        "agent": agent,
        "memory_type": memory_type,
        "content": content,
        "summary": summary or "",
        "vector": vector,
        "created_at": now,
        "metadata": metadata_str,
    }

    table.add([record])
    logger.info(
        "Stored memory %s (type=%s, agent=%s, project=%s)",
        memory_id,
        memory_type,
        agent,
        project,
    )
    return memory_id


def next_hdr_number() -> str:
    """Query LanceDB for the maximum HDR number and return the next in sequence.

    Scans all decision_context memories for hdr_number metadata fields,
    finds the maximum number, and returns the next sequential HDR number.

    Returns:
        Next HDR number in format "HDR-NNNN" (e.g., "HDR-0041").
        Returns "HDR-0001" if no HDRs exist yet.

    Raises:
        ImportError: If lancedb is not installed.
    """
    try:
        db = get_memory_store()
        table = ensure_memories_table(db)

        # Query all decision_context memories
        all_decisions = (
            table.search([0.0] * _EMBEDDING_DIMENSION)
            .where("memory_type = 'decision_context'")
            .limit(10000)
            .to_list()
        )

        max_number = 0
        for row in all_decisions:
            metadata_str = row.get("metadata", "{}")
            if metadata_str:
                try:
                    metadata = json.loads(metadata_str)
                    hdr_number = metadata.get("hdr_number", "")
                    if hdr_number and hdr_number.startswith("HDR-"):
                        # Parse the numeric part
                        number_part = hdr_number[4:]
                        try:
                            num = int(number_part)
                            if num > max_number:
                                max_number = num
                        except ValueError:
                            # Malformed HDR number, skip
                            continue
                except (json.JSONDecodeError, TypeError):
                    # Skip invalid metadata
                    continue

        # Return next number in sequence
        next_num = max_number + 1
        return f"HDR-{next_num:04d}"

    except ImportError:
        logger.warning("LanceDB not available for HDR numbering")
        raise


def recall(
    query: str,
    limit: int = 5,
    **filters: Any,
) -> list[dict[str, Any]]:
    """Search semantic memory for relevant cross-session context.

    Embeds the query and performs vector similarity search against the
    memories table, with optional metadata filters applied as WHERE
    predicates.

    Formulate queries as conceptual descriptions, not keywords.
    "How we handle configuration across repos" retrieves better than "config".

    Args:
        query: Natural language query string.
        limit: Maximum number of results to return (default 5).
        **filters: Optional metadata filters. Supported keys:
            project, agent, memory_type, repo, session_id, org, team, host.

    Returns:
        List of dicts, each containing the memory fields plus a
        '_distance' key with the similarity score (lower is more similar).
    """
    db = get_memory_store()
    table = ensure_memories_table(db)

    query_vector = embed_text(query)

    search = table.search(query_vector).limit(limit)

    # Build WHERE clause from filters
    where_clauses = []
    valid_filter_keys = {
        "project",
        "agent",
        "memory_type",
        "repo",
        "session_id",
        "org",
        "team",
        "host",
    }

    for key, value in filters.items():
        if key in valid_filter_keys and value is not None:
            # Escape single quotes in values
            escaped = str(value).replace("'", "''")
            where_clauses.append(f"{key} = '{escaped}'")

    if where_clauses:
        where_str = " AND ".join(where_clauses)
        search = search.where(where_str)

    results = search.to_list()

    # Format results — drop the raw vector to keep output clean
    formatted = []
    for row in results:
        entry = {
            "id": row.get("id"),
            "project": row.get("project"),
            "repo": row.get("repo"),
            "org": row.get("org"),
            "team": row.get("team"),
            "host": row.get("host"),
            "session_id": row.get("session_id"),
            "agent": row.get("agent"),
            "memory_type": row.get("memory_type"),
            "content": row.get("content"),
            "summary": row.get("summary"),
            "created_at": row.get("created_at"),
            "metadata": row.get("metadata"),
            "_distance": row.get("_distance"),
        }
        formatted.append(entry)

    return formatted
