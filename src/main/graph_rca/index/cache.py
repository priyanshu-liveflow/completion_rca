"""Index cache — commit-hash gated staleness check."""
from __future__ import annotations

import subprocess

from ..store import load_trie_data, save_trie_data, load_meta, save_meta, load_commit, save_commit, cache_root
from src.main.shared.logging import get_logger

log = get_logger("index_cache")

# Re-export for backwards compat (indexer.py uses CACHE_DIR for flow graph paths)
CACHE_DIR = cache_root()


def get_commit_hash(repo_path: str) -> str:
    """Get current HEAD commit hash for a repo path."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path, capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def is_stale(repo_name: str, current_hash: str) -> bool:
    """Check if cached index is stale."""
    stored = load_commit(repo_name)
    if not stored:
        return True
    return stored != current_hash


def save_cache(repo_name: str, commit_hash: str, trie_data: list, meta: dict):
    """Save index artifacts to .flow_cache/{repo}/."""
    save_commit(repo_name, commit_hash)
    save_trie_data(repo_name, trie_data)
    save_meta(repo_name, meta)
    log.info("cache_saved", repo=repo_name, commit=commit_hash[:8])


def load_cache(repo_name: str) -> tuple[list, dict] | None:
    """Load cached trie data + meta. Returns None if missing."""
    trie_data = load_trie_data(repo_name)
    meta = load_meta(repo_name)
    if not trie_data:
        return None
    log.info("cache_loaded", repo=repo_name)
    return trie_data, meta
