"""Repository operations adapter protocol.

Implemented by: herd-repo-github (reference), or any git hosting platform.

Responsible for branch management, worktree isolation, pull requests, and
code review operations. Each agent gets an isolated worktree — no shared
checkouts between concurrent agents.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from herd_core.types import PRRecord


@runtime_checkable
class RepoAdapter(Protocol):
    """Manages repository operations for agent isolation and collaboration.

    Design principles:
    - Worktree isolation: each agent spawn gets a dedicated worktree.
    - Branch naming: herd/{agent}/{ticket}-description convention.
    - Never push to main. All work goes through PRs.
    - PR comments are append-only (reviews post, never edit).
    """

    def create_branch(self, name: str, *, base: str = "main") -> str:
        """Create a new branch from base. Returns branch name."""
        ...

    def create_worktree(self, branch: str, path: str) -> str:
        """Create a git worktree for isolated agent work.

        Args:
            branch: Branch name (created if it doesn't exist).
            path: Filesystem path for the worktree.

        Returns:
            Absolute path to the created worktree.
        """
        ...

    def remove_worktree(self, path: str) -> None:
        """Remove a git worktree after agent completion."""
        ...

    def push(self, branch: str) -> None:
        """Push a branch to the remote."""
        ...

    def create_pr(
        self,
        title: str,
        body: str,
        *,
        head: str,
        base: str = "main",
    ) -> str:
        """Create a pull request. Returns the PR identifier."""
        ...

    def get_pr(self, pr_id: str) -> PRRecord:
        """Get current state of a pull request."""
        ...

    def merge_pr(self, pr_id: str) -> None:
        """Merge a pull request."""
        ...

    def add_pr_comment(self, pr_id: str, body: str) -> None:
        """Add a review comment to a pull request."""
        ...
