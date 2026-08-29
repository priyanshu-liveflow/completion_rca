"""Staleness checker — verifies code graph index is current before analysis."""
from __future__ import annotations

import subprocess
from pathlib import Path

from src.main.code_tools import get_graph
from .index.cache import get_commit_hash


def check_staleness(repo_path: str) -> dict:
    """Check if the indexed repo is stale (commits since last index).
    
    Returns:
        dict with keys: is_stale, indexed_commit, current_commit, indexed_at, branch
    """
    g = get_graph()
    repo_path_str = str(repo_path)

    # Get stored metadata from Repository node
    result = g.query(
        f'MATCH (r:Repository) WHERE r.path CONTAINS "{Path(repo_path_str).name}" '
        f'RETURN r.branch, r.commit_hash, r.indexed_at'
    )

    stored_branch = None
    stored_commit = None
    stored_at = None

    if result.result_set:
        stored_branch = result.result_set[0][0]
        stored_commit = result.result_set[0][1]
        stored_at = result.result_set[0][2]

    current_commit = get_commit_hash(repo_path_str) or None
    current_branch = _git_branch(repo_path_str)

    if stored_commit is None and current_commit is None:
        return {"is_stale": False, "indexed_commit": None, "current_commit": None,
                "indexed_at": stored_at, "indexed_branch": stored_branch,
                "current_branch": None, "repo_path": repo_path_str}

    is_stale = (stored_commit is None) or (current_commit is not None and stored_commit != current_commit)

    return {
        "is_stale": is_stale,
        "indexed_commit": stored_commit,
        "current_commit": current_commit,
        "indexed_at": stored_at,
        "indexed_branch": stored_branch,
        "current_branch": current_branch,
        "repo_path": repo_path_str,
    }


def _git_branch(repo_path: str) -> str | None:
    """Get current branch name."""
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=5, cwd=repo_path,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
