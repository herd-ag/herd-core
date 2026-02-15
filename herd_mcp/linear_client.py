"""Linear GraphQL API client using urllib (no external dependencies).

This module provides a lightweight client for interacting with Linear's GraphQL API
using only Python's standard library urllib.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

LINEAR_API_URL = "https://api.linear.app/graphql"


def _get_api_key() -> str | None:
    """Get Linear API key from environment.

    Returns:
        Linear API key if set, None otherwise.
    """
    return os.getenv("LINEAR_API_KEY")


def _graphql_request(
    query: str, variables: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Execute a GraphQL request against Linear API using urllib.

    Args:
        query: GraphQL query or mutation string.
        variables: Optional variables for the query.

    Returns:
        Parsed JSON response from Linear API.

    Raises:
        Exception: If API key is missing or request fails.
    """
    api_key = _get_api_key()
    if not api_key:
        raise Exception("LINEAR_API_KEY environment variable not set")

    payload = {"query": query}
    if variables:
        payload["variables"] = variables

    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        LINEAR_API_URL,
        data=data,
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
        },
    )

    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())

            if "errors" in result:
                error_msg = "; ".join(
                    e.get("message", str(e)) for e in result["errors"]
                )
                raise Exception(f"Linear GraphQL error: {error_msg}")

            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else "No error body"
        raise Exception(f"Linear API HTTP error {e.code}: {error_body}") from e
    except urllib.error.URLError as e:
        raise Exception(f"Linear API network error: {e.reason}") from e


def get_issue(identifier: str) -> dict[str, Any] | None:
    """Get an issue by identifier (e.g., 'DBC-120').

    Args:
        identifier: Linear issue identifier (e.g., 'DBC-120').

    Returns:
        Issue data dict if found, None otherwise.
    """
    query = """
    query IssueSearch($query: String!) {
      issueSearch(query: $query) {
        nodes {
          id
          identifier
          title
          description
          state {
            id
            name
          }
          priority
          team {
            id
            name
          }
          project {
            id
            name
          }
        }
      }
    }
    """

    try:
        result = _graphql_request(query, {"query": identifier})
        nodes = result.get("data", {}).get("issueSearch", {}).get("nodes", [])

        # Find exact match on identifier
        for node in nodes:
            if node.get("identifier") == identifier:
                return node

        return None
    except Exception as e:
        logger.warning(f"Failed to fetch Linear issue {identifier}: {e}")
        return None


def create_issue(
    team_id: str,
    title: str,
    description: str | None = None,
    state_id: str | None = None,
    priority: int | None = None,
    project_id: str | None = None,
    labels: list[str] | None = None,
) -> dict[str, Any]:
    """Create a new issue in Linear.

    Args:
        team_id: Linear team ID (UUID).
        title: Issue title.
        description: Optional issue description.
        state_id: Optional workflow state ID.
        priority: Optional priority (0=None, 1=Urgent, 2=High, 3=Normal, 4=Low).
        project_id: Optional project ID.
        labels: Optional list of label IDs.

    Returns:
        Created issue data dict.

    Raises:
        Exception: If creation fails.
    """
    mutation = """
    mutation CreateIssue($input: IssueCreateInput!) {
      issueCreate(input: $input) {
        success
        issue {
          id
          identifier
          title
          state {
            id
            name
          }
        }
      }
    }
    """

    issue_input: dict[str, Any] = {
        "teamId": team_id,
        "title": title,
    }

    if description:
        issue_input["description"] = description
    if state_id:
        issue_input["stateId"] = state_id
    if priority is not None:
        issue_input["priority"] = priority
    if project_id:
        issue_input["projectId"] = project_id
    if labels:
        issue_input["labelIds"] = labels

    result = _graphql_request(mutation, {"input": issue_input})

    data = result.get("data", {}).get("issueCreate", {})
    if not data.get("success"):
        raise Exception("Failed to create Linear issue")

    return data.get("issue", {})


def update_issue_state(issue_id: str, state_id: str) -> dict[str, Any]:
    """Update an issue's workflow state in Linear.

    Args:
        issue_id: Linear issue ID (UUID, not identifier).
        state_id: Target workflow state ID (UUID).

    Returns:
        Updated issue data dict.

    Raises:
        Exception: If update fails.
    """
    mutation = """
    mutation UpdateIssue($id: String!, $input: IssueUpdateInput!) {
      issueUpdate(id: $id, input: $input) {
        success
        issue {
          id
          identifier
          state {
            id
            name
          }
        }
      }
    }
    """

    result = _graphql_request(
        mutation,
        {
            "id": issue_id,
            "input": {"stateId": state_id},
        },
    )

    data = result.get("data", {}).get("issueUpdate", {})
    if not data.get("success"):
        raise Exception(f"Failed to update Linear issue state for {issue_id}")

    return data.get("issue", {})


def search_issues(query: str, team_id: str | None = None) -> list[dict[str, Any]]:
    """Search for issues by query string.

    Args:
        query: Search query string.
        team_id: Optional team ID to filter by.

    Returns:
        List of matching issue dicts.
    """
    graphql_query = """
    query IssueSearch($query: String!) {
      issueSearch(query: $query) {
        nodes {
          id
          identifier
          title
          description
          state {
            id
            name
          }
          team {
            id
            name
          }
        }
      }
    }
    """

    try:
        result = _graphql_request(graphql_query, {"query": query})
        nodes = result.get("data", {}).get("issueSearch", {}).get("nodes", [])

        # Filter by team if specified
        if team_id:
            nodes = [n for n in nodes if n.get("team", {}).get("id") == team_id]

        return nodes
    except Exception as e:
        logger.warning(f"Failed to search Linear issues with query '{query}': {e}")
        return []


def is_linear_identifier(ticket_id: str) -> bool:
    """Check if a ticket ID looks like a Linear identifier.

    Args:
        ticket_id: Ticket ID string to check.

    Returns:
        True if it matches Linear identifier pattern (e.g., 'DBC-120').
    """
    return bool(re.match(r"^[A-Z]+-\d+$", ticket_id))
