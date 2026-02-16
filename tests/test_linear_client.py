"""Tests for Linear API client."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest
from herd_mcp.linear_client import (
    _get_api_key,
    _graphql_request,
    create_issue,
    get_issue,
    is_linear_identifier,
    search_issues,
    update_issue_state,
)


class MockResponse:
    """Mock urllib response."""

    def __init__(self, data: dict):
        self.data = data

    def read(self):
        return json.dumps(self.data).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_get_api_key_from_env():
    """Test getting API key from environment."""
    with patch.dict(os.environ, {"HERD_TICKET_LINEAR_API_KEY": "test-key-123"}):
        assert _get_api_key() == "test-key-123"


def test_get_api_key_missing():
    """Test getting API key when not set."""
    with patch.dict(os.environ, {}, clear=True):
        assert _get_api_key() is None


def test_graphql_request_success():
    """Test successful GraphQL request."""
    mock_response = MockResponse({"data": {"test": "value"}})

    with patch.dict(os.environ, {"HERD_TICKET_LINEAR_API_KEY": "test-key"}):
        with patch("urllib.request.urlopen", return_value=mock_response):
            result = _graphql_request("query { test }")
            assert result == {"data": {"test": "value"}}


def test_graphql_request_auth_header():
    """Test that auth header uses raw API key without Bearer prefix."""
    mock_response = MockResponse({"data": {"test": "value"}})

    with patch.dict(os.environ, {"HERD_TICKET_LINEAR_API_KEY": "test-api-key-123"}):
        with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
            _graphql_request("query { test }")

            # Check that the Request object was created with correct auth header
            call_args = mock_urlopen.call_args
            request = call_args[0][0]
            # Linear API uses raw API key, not Bearer token
            assert request.headers.get("Authorization") == "test-api-key-123"
            # Should NOT have Bearer prefix
            assert not request.headers.get("Authorization", "").startswith("Bearer ")


def test_graphql_request_missing_api_key():
    """Test GraphQL request without API key."""
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(Exception, match="HERD_TICKET_LINEAR_API_KEY"):
            _graphql_request("query { test }")


def test_graphql_request_with_errors():
    """Test GraphQL request that returns errors."""
    mock_response = MockResponse(
        {"errors": [{"message": "Field not found"}, {"message": "Invalid query"}]}
    )

    with patch.dict(os.environ, {"HERD_TICKET_LINEAR_API_KEY": "test-key"}):
        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(Exception, match="Linear GraphQL error"):
                _graphql_request("query { invalid }")


def test_get_issue_found():
    """Test getting an issue that exists."""
    mock_response = MockResponse(
        {
            "data": {
                "issueSearch": {
                    "nodes": [
                        {
                            "id": "issue-uuid-123",
                            "identifier": "DBC-120",
                            "title": "Fix bug",
                            "description": "Bug description",
                            "state": {"id": "state-1", "name": "Todo"},
                            "team": {"id": "team-1", "name": "DBC"},
                        }
                    ]
                }
            }
        }
    )

    with patch.dict(os.environ, {"HERD_TICKET_LINEAR_API_KEY": "test-key"}):
        with patch("urllib.request.urlopen", return_value=mock_response):
            issue = get_issue("DBC-120")
            assert issue is not None
            assert issue["identifier"] == "DBC-120"
            assert issue["title"] == "Fix bug"


def test_get_issue_not_found():
    """Test getting an issue that doesn't exist."""
    mock_response = MockResponse({"data": {"issueSearch": {"nodes": []}}})

    with patch.dict(os.environ, {"HERD_TICKET_LINEAR_API_KEY": "test-key"}):
        with patch("urllib.request.urlopen", return_value=mock_response):
            issue = get_issue("DBC-999")
            assert issue is None


def test_get_issue_multiple_results():
    """Test getting issue when search returns multiple results."""
    mock_response = MockResponse(
        {
            "data": {
                "issueSearch": {
                    "nodes": [
                        {"identifier": "DBC-119", "title": "Other issue"},
                        {"identifier": "DBC-120", "title": "Target issue"},
                        {"identifier": "DBC-121", "title": "Another issue"},
                    ]
                }
            }
        }
    )

    with patch.dict(os.environ, {"HERD_TICKET_LINEAR_API_KEY": "test-key"}):
        with patch("urllib.request.urlopen", return_value=mock_response):
            issue = get_issue("DBC-120")
            assert issue is not None
            assert issue["identifier"] == "DBC-120"
            assert issue["title"] == "Target issue"


def test_get_issue_api_error():
    """Test getting issue when API returns error."""
    with patch.dict(os.environ, {"HERD_TICKET_LINEAR_API_KEY": "test-key"}):
        with patch("urllib.request.urlopen", side_effect=Exception("Network error")):
            issue = get_issue("DBC-120")
            assert issue is None


def test_update_issue_state_success():
    """Test successfully updating issue state."""
    mock_response = MockResponse(
        {
            "data": {
                "issueUpdate": {
                    "success": True,
                    "issue": {
                        "id": "issue-uuid-123",
                        "identifier": "DBC-120",
                        "state": {"id": "new-state-id", "name": "In Progress"},
                    },
                }
            }
        }
    )

    with patch.dict(os.environ, {"HERD_TICKET_LINEAR_API_KEY": "test-key"}):
        with patch("urllib.request.urlopen", return_value=mock_response):
            result = update_issue_state("issue-uuid-123", "new-state-id")
            assert result["id"] == "issue-uuid-123"
            assert result["state"]["name"] == "In Progress"


def test_update_issue_state_failure():
    """Test update issue state when mutation returns failure."""
    mock_response = MockResponse({"data": {"issueUpdate": {"success": False}}})

    with patch.dict(os.environ, {"HERD_TICKET_LINEAR_API_KEY": "test-key"}):
        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(Exception, match="Failed to update Linear issue state"):
                update_issue_state("issue-uuid-123", "new-state-id")


def test_create_issue_minimal():
    """Test creating issue with minimal fields."""
    mock_response = MockResponse(
        {
            "data": {
                "issueCreate": {
                    "success": True,
                    "issue": {
                        "id": "new-issue-uuid",
                        "identifier": "DBC-125",
                        "title": "New issue",
                        "state": {"id": "state-1", "name": "Todo"},
                    },
                }
            }
        }
    )

    with patch.dict(os.environ, {"HERD_TICKET_LINEAR_API_KEY": "test-key"}):
        with patch("urllib.request.urlopen", return_value=mock_response):
            result = create_issue("team-id-123", "New issue")
            assert result["identifier"] == "DBC-125"
            assert result["title"] == "New issue"


def test_create_issue_full():
    """Test creating issue with all optional fields."""
    mock_response = MockResponse(
        {
            "data": {
                "issueCreate": {
                    "success": True,
                    "issue": {
                        "id": "new-issue-uuid",
                        "identifier": "DBC-126",
                        "title": "Full issue",
                    },
                }
            }
        }
    )

    with patch.dict(os.environ, {"HERD_TICKET_LINEAR_API_KEY": "test-key"}):
        with patch("urllib.request.urlopen", return_value=mock_response):
            result = create_issue(
                team_id="team-id-123",
                title="Full issue",
                description="Issue description",
                state_id="state-id",
                priority=2,
                project_id="project-id",
                labels=["label-1", "label-2"],
            )
            assert result["identifier"] == "DBC-126"


def test_create_issue_failure():
    """Test create issue when mutation returns failure."""
    mock_response = MockResponse({"data": {"issueCreate": {"success": False}}})

    with patch.dict(os.environ, {"HERD_TICKET_LINEAR_API_KEY": "test-key"}):
        with patch("urllib.request.urlopen", return_value=mock_response):
            with pytest.raises(Exception, match="Failed to create Linear issue"):
                create_issue("team-id", "Title")


def test_search_issues_success():
    """Test searching for issues."""
    mock_response = MockResponse(
        {
            "data": {
                "issueSearch": {
                    "nodes": [
                        {
                            "identifier": "DBC-120",
                            "title": "Issue 1",
                            "team": {"id": "team-1"},
                        },
                        {
                            "identifier": "DBC-121",
                            "title": "Issue 2",
                            "team": {"id": "team-1"},
                        },
                    ]
                }
            }
        }
    )

    with patch.dict(os.environ, {"HERD_TICKET_LINEAR_API_KEY": "test-key"}):
        with patch("urllib.request.urlopen", return_value=mock_response):
            results = search_issues("bug")
            assert len(results) == 2
            assert results[0]["identifier"] == "DBC-120"


def test_search_issues_with_team_filter():
    """Test searching issues with team filter."""
    mock_response = MockResponse(
        {
            "data": {
                "issueSearch": {
                    "nodes": [
                        {"identifier": "DBC-120", "team": {"id": "team-1"}},
                        {"identifier": "ENG-50", "team": {"id": "team-2"}},
                    ]
                }
            }
        }
    )

    with patch.dict(os.environ, {"HERD_TICKET_LINEAR_API_KEY": "test-key"}):
        with patch("urllib.request.urlopen", return_value=mock_response):
            results = search_issues("bug", team_id="team-1")
            assert len(results) == 1
            assert results[0]["identifier"] == "DBC-120"


def test_search_issues_api_error():
    """Test search issues when API fails."""
    with patch.dict(os.environ, {"HERD_TICKET_LINEAR_API_KEY": "test-key"}):
        with patch("urllib.request.urlopen", side_effect=Exception("API error")):
            results = search_issues("bug")
            assert results == []


def test_is_linear_identifier_valid():
    """Test identifying valid Linear identifiers."""
    assert is_linear_identifier("DBC-120") is True
    assert is_linear_identifier("ENG-1") is True
    assert is_linear_identifier("ABC-999") is True


def test_is_linear_identifier_invalid():
    """Test identifying invalid Linear identifiers."""
    assert is_linear_identifier("dbc-120") is False  # lowercase
    assert is_linear_identifier("DBC120") is False  # no dash
    assert is_linear_identifier("DBC-") is False  # no number
    assert is_linear_identifier("120") is False  # just number
    assert is_linear_identifier("random-text") is False  # wrong format
    assert is_linear_identifier("") is False  # empty
