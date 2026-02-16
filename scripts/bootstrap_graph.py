#!/usr/bin/env python3
"""Seed KuzuDB graph store from existing HDR decision files.

Parses all .herd/decisions/*.md files, extracts YAML frontmatter and
the HDR title, then creates Decision nodes and relationship edges
(Supersedes, Decides) in KuzuDB.

Idempotent: uses merge_node so it is safe to run multiple times.

Usage:
    cd /path/to/herd-core
    python scripts/bootstrap_graph.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def find_repo_root() -> Path:
    """Walk up from the script location to find the repository root.

    Looks for a directory containing a .git directory.

    Returns:
        Path to the repository root.

    Raises:
        SystemExit: If no .git directory is found in any ancestor.
    """
    current = Path(__file__).resolve().parent
    while current != current.parent:
        if (current / ".git").exists():
            return current
        current = current.parent

    print("ERROR: Could not find repository root (.git directory).", file=sys.stderr)
    sys.exit(1)


def parse_frontmatter(text: str) -> dict[str, str | None]:
    """Parse YAML frontmatter from markdown text using regex.

    Extracts key-value pairs from the YAML block delimited by --- lines.
    Handles null values and quoted strings. Does not require PyYAML.

    Args:
        text: Full markdown file content.

    Returns:
        Dict of frontmatter fields. Missing fields are absent from the dict.
    """
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        return {}

    frontmatter: dict[str, str | None] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        kv_match = re.match(r"^([a-zA-Z_-]+)\s*:\s*(.*?)\s*$", line)
        if not kv_match:
            continue

        key = kv_match.group(1)
        value = kv_match.group(2)

        # Normalize null values
        if value.lower() in ("null", "~", ""):
            frontmatter[key] = None
        else:
            # Strip optional quotes
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            frontmatter[key] = value

    return frontmatter


def extract_title(text: str, hdr_number: str) -> str:
    """Extract the HDR title from the first H1 heading in the markdown body.

    Handles both formats:
        # HDR-0037: Async Write Serialization
        # Remove --create-stubs flag -- sync is bidirectional by default

    Args:
        text: Full markdown file content.
        hdr_number: The HDR identifier (e.g., "HDR-0037") for fallback.

    Returns:
        The title string, stripped of the HDR-NNNN: prefix if present.
    """
    # Find the first H1 heading after the frontmatter
    match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    if not match:
        return hdr_number

    heading = match.group(1).strip()

    # Strip "HDR-NNNN: " prefix if present
    prefix_match = re.match(r"^HDR-\d{4}:\s*(.+)$", heading)
    if prefix_match:
        return prefix_match.group(1)

    return heading


def extract_hdr_references(value: str) -> list[str]:
    """Extract HDR-NNNN references from a string value.

    Args:
        value: String that may contain HDR references like "HDR-0029".

    Returns:
        List of HDR identifiers found (e.g., ["HDR-0029"]).
    """
    return re.findall(r"HDR-\d{4}", value)


def parse_hdr_file(filepath: Path) -> dict | None:
    """Parse a single HDR decision file into a structured dict.

    Args:
        filepath: Path to the .md file.

    Returns:
        Dict with keys: id, title, date, status, scope, principle,
        superseded_by, decision_maker. Returns None if the file cannot
        be parsed.
    """
    try:
        text = filepath.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"  WARNING: Could not read {filepath.name}: {exc}", file=sys.stderr)
        return None

    # Extract HDR number from filename: 0037-async-write-serialization.md -> HDR-0037
    stem = filepath.stem
    num_match = re.match(r"^(\d{4})-", stem)
    if not num_match:
        print(
            f"  WARNING: Filename {filepath.name} does not match expected "
            f"pattern NNNN-description.md, skipping.",
            file=sys.stderr,
        )
        return None

    hdr_id = f"HDR-{num_match.group(1)}"

    frontmatter = parse_frontmatter(text)
    title = extract_title(text, hdr_id)

    return {
        "id": hdr_id,
        "title": title,
        "date": frontmatter.get("date", ""),
        "status": frontmatter.get("status", ""),
        "scope": frontmatter.get("scope", ""),
        "principle": frontmatter.get("principle", ""),
        "superseded_by": frontmatter.get("superseded-by"),
        "decision_maker": frontmatter.get("decision-maker"),
    }


def main() -> None:
    """Bootstrap KuzuDB graph with Decision nodes from HDR files."""
    repo_root = find_repo_root()
    decisions_dir = repo_root / ".herd" / "decisions"

    if not decisions_dir.is_dir():
        print(
            f"ERROR: Decisions directory not found at {decisions_dir}",
            file=sys.stderr,
        )
        sys.exit(1)

    # Import the graph module -- this will fail clearly if kuzu is missing
    try:
        sys.path.insert(0, str(repo_root))
        from herd_mcp.graph import create_edge, is_available, merge_node
    except ImportError as exc:
        print(
            f"ERROR: Could not import graph module: {exc}\n"
            f"Ensure kuzu is installed: pip install 'kuzu>=0.11'",
            file=sys.stderr,
        )
        sys.exit(1)

    if not is_available():
        print(
            "ERROR: KuzuDB graph store is not available. "
            "Ensure kuzu is installed and HERD_KUZU_PATH is set.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Discover HDR files
    hdr_files = sorted(decisions_dir.glob("*.md"))
    if not hdr_files:
        print("No decision files found in", decisions_dir)
        sys.exit(0)

    print(f"Found {len(hdr_files)} decision files in {decisions_dir}")
    print()

    # Parse all HDR files
    hdrs: list[dict] = []
    for filepath in hdr_files:
        parsed = parse_hdr_file(filepath)
        if parsed:
            hdrs.append(parsed)

    # Track counts for summary
    nodes_created = 0
    agent_nodes_created: set[str] = set()
    supersedes_edges = 0
    decides_edges = 0

    # Phase 1: Create all Decision nodes
    print("--- Creating Decision nodes ---")
    for hdr in hdrs:
        node_props = {
            "id": hdr["id"],
            "title": hdr["title"],
            "date": str(hdr["date"]) if hdr["date"] else "",
            "status": hdr["status"] or "",
            "scope": hdr["scope"] or "",
            "principle": hdr["principle"] or "",
        }
        merge_node("Decision", node_props)
        nodes_created += 1
        print(f"  {hdr['id']}: {hdr['title']}")

    print()

    # Phase 2: Create Agent nodes and Decides edges for decision-makers
    print("--- Creating Agent nodes and Decides edges ---")
    for hdr in hdrs:
        decision_maker = hdr["decision_maker"]
        if not decision_maker:
            continue

        # Create Agent node (merge is idempotent)
        agent_id = decision_maker.lower()
        if agent_id not in agent_nodes_created:
            merge_node(
                "Agent",
                {
                    "id": agent_id,
                    "code": agent_id,
                    "role": "architect" if decision_maker == "Faust" else "",
                    "status": "active",
                    "team": "",
                    "host": "",
                },
            )
            agent_nodes_created.add(agent_id)
            print(f"  Agent node: {decision_maker} (id={agent_id})")

        # Create Decides edge: Agent -> Decision
        create_edge("Decides", "Agent", agent_id, "Decision", hdr["id"])
        decides_edges += 1

    print()

    # Phase 3: Create Supersedes edges
    print("--- Creating Supersedes edges ---")
    # Build a lookup of known HDR IDs for validation
    known_ids = {h["id"] for h in hdrs}

    for hdr in hdrs:
        superseded_by = hdr["superseded_by"]
        if not superseded_by:
            continue

        # Extract HDR references from the superseded-by value
        refs = extract_hdr_references(str(superseded_by))
        for ref in refs:
            if ref in known_ids:
                # The new HDR supersedes this one: new -> old
                create_edge("Supersedes", "Decision", ref, "Decision", hdr["id"])
                supersedes_edges += 1
                print(f"  {ref} supersedes {hdr['id']}")
            else:
                print(
                    f"  WARNING: {hdr['id']} references unknown {ref} "
                    f"in superseded-by field",
                    file=sys.stderr,
                )

    if supersedes_edges == 0:
        print("  (no supersedes relationships found)")

    # Summary
    print()
    print("=" * 50)
    print("Bootstrap complete.")
    print(f"  Decision nodes: {nodes_created}")
    print(f"  Agent nodes:    {len(agent_nodes_created)}")
    print(f"  Decides edges:  {decides_edges}")
    print(f"  Supersedes edges: {supersedes_edges}")
    print(f"  Total nodes:    {nodes_created + len(agent_nodes_created)}")
    print(f"  Total edges:    {decides_edges + supersedes_edges}")
    print("=" * 50)


if __name__ == "__main__":
    main()
