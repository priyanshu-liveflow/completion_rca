"""Centralized data access layer for .flow_cache/ — single source of truth for all cache paths."""
from __future__ import annotations

import contextlib
import io
import json
import logging
import os
from pathlib import Path

from .constants import EMBED_MODEL_NAME, EMBED_DEVICE

_ROOT = Path(__file__).resolve().parents[3] / ".flow_cache"

# Singleton embedding model — loaded once, reused everywhere
_EMBED_MODEL = None


def get_embed_model():
    """Get or create the shared SentenceTransformer instance."""
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
        logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
        with contextlib.redirect_stderr(io.StringIO()):
            from sentence_transformers import SentenceTransformer
            _EMBED_MODEL = SentenceTransformer(EMBED_MODEL_NAME, device=EMBED_DEVICE)
    return _EMBED_MODEL
    return _EMBED_MODEL


def cache_root() -> Path:
    """Return the .flow_cache/ root directory."""
    return _ROOT


def repo_dir(repo: str) -> Path:
    """Return .flow_cache/{repo}/ directory, creating if needed."""
    d = _ROOT / repo
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_trie_data(repo: str) -> list:
    """Load trie_data.json for a repo. Returns [] if missing."""
    p = _ROOT / repo / "trie_data.json"
    if not p.exists():
        return []
    return json.loads(p.read_text())


def save_trie_data(repo: str, data: list):
    """Save trie_data.json."""
    d = repo_dir(repo)
    (d / "trie_data.json").write_text(json.dumps(data))


def load_merged_flow(repo: str, fid: int) -> dict | None:
    """Load pre-computed merged flow for a function. Returns None if missing."""
    p = _ROOT / repo / "merged" / f"{fid}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text())


def save_merged_flow(repo: str, fid: int, data: dict):
    """Save a merged flow."""
    d = _ROOT / repo / "merged"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{fid}.json").write_text(json.dumps(data))


def load_func_map(repo: str) -> dict:
    """Load func_map.json. Returns {} if missing."""
    p = _ROOT / repo / "func_map.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def save_func_map(repo: str, data: dict):
    """Save func_map.json."""
    d = repo_dir(repo)
    (d / "func_map.json").write_text(json.dumps(data))


def load_commit(repo: str) -> str:
    """Load stored commit hash. Returns '' if missing."""
    p = _ROOT / repo / "commit.txt"
    return p.read_text().strip() if p.exists() else ""


def save_commit(repo: str, commit_hash: str):
    """Save commit hash."""
    d = repo_dir(repo)
    (d / "commit.txt").write_text(commit_hash)


def load_meta(repo: str) -> dict:
    """Load meta.json. Returns {} if missing."""
    p = _ROOT / repo / "meta.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def save_meta(repo: str, data: dict):
    """Save meta.json."""
    d = repo_dir(repo)
    (d / "meta.json").write_text(json.dumps(data))


def merged_dir(repo: str) -> Path:
    """Return the merged flows directory, creating if needed."""
    d = _ROOT / repo / "merged"
    d.mkdir(parents=True, exist_ok=True)
    return d


def semantic_search(repo: str, query: str, top_k: int = 10):
    """Search function source by semantic similarity. Returns list of SemanticHit."""
    from .index.semantic_index import SemanticIndex
    idx = SemanticIndex()
    if not idx.load(repo):
        return []
    return idx.search(query, top_k)
