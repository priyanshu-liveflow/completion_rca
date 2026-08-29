"""Semantic index — embeds function source with MiniLM-v6 at function level.

Chunks each function's source with 100-token overlap, embeds with
all-MiniLM-L6-v2, stores embeddings + metadata as numpy arrays in .flow_cache/.
Search returns top-k function matches by cosine similarity.
"""
from __future__ import annotations

import numpy as np
from pathlib import Path
from dataclasses import dataclass, field

from ..store import repo_dir, get_embed_model
from ..constants import EMBED_DIM
from src.main.shared.logging import get_logger

log = get_logger("semantic_index")

_CHUNK_SIZE = 256  # words per chunk
_CHUNK_OVERLAP = 100  # word overlap between chunks


@dataclass
class SemanticHit:
    fid: int
    name: str
    score: float
    chunk_text: str


class SemanticIndex:
    """In-memory semantic index for function source code."""

    def __init__(self):
        self._embeddings: np.ndarray | None = None  # (N, 384)
        self._fids: np.ndarray | None = None  # (N,) int
        self._names: list[str] = []  # (N,) function names
        self._chunks: list[str] = []  # (N,) chunk texts
        self._model = None

    def _get_model(self):
        if self._model is None:
            from ..store import get_embed_model
            self._model = get_embed_model()
        return self._model

    def build(self, functions: list[tuple[int, str, str]]):
        """Build index from list of (fid, name, source) tuples."""
        all_chunks = []
        all_fids = []
        all_names = []

        for fid, name, source in functions:
            if not source or len(source.strip()) < 20:
                continue
            chunks = _chunk_source(source, _CHUNK_SIZE, _CHUNK_OVERLAP)
            for chunk in chunks:
                all_chunks.append(chunk)
                all_fids.append(fid)
                all_names.append(name)

        if not all_chunks:
            log.warning("semantic_index_empty", reason="no chunks generated")
            return

        model = self._get_model()
        log.info("semantic_embedding_start", chunks=len(all_chunks))
        embeddings = model.encode(all_chunks, show_progress_bar=True, batch_size=256,
                                  normalize_embeddings=True)

        self._embeddings = np.array(embeddings, dtype=np.float32)
        self._fids = np.array(all_fids, dtype=np.int64)
        self._names = all_names
        self._chunks = all_chunks

        log.info("semantic_index_built", chunks=len(all_chunks),
                 functions=len(set(all_fids)))

    def save(self, repo: str):
        """Persist index to .flow_cache/{repo}/semantic_index/."""
        if self._embeddings is None:
            return
        out_dir = repo_dir(repo) / "semantic_index"
        out_dir.mkdir(parents=True, exist_ok=True)

        np.save(out_dir / "embeddings.npy", self._embeddings)
        np.save(out_dir / "fids.npy", self._fids)
        # Save names and chunks as line-delimited text
        (out_dir / "names.txt").write_text("\n".join(self._names))
        (out_dir / "chunks.txt").write_text("\x00".join(self._chunks))

        log.info("semantic_index_saved", path=str(out_dir), chunks=len(self._chunks))

    def load(self, repo: str) -> bool:
        """Load persisted index. Returns True if loaded successfully."""
        idx_dir = repo_dir(repo) / "semantic_index"
        if not (idx_dir / "embeddings.npy").exists():
            return False

        self._embeddings = np.load(idx_dir / "embeddings.npy")
        self._fids = np.load(idx_dir / "fids.npy")
        self._names = (idx_dir / "names.txt").read_text().split("\n")
        self._chunks = (idx_dir / "chunks.txt").read_text().split("\x00")

        log.info("semantic_index_loaded", chunks=len(self._chunks),
                 functions=len(set(self._fids.tolist())))
        return True

    def search(self, query: str, top_k: int = 10) -> list[SemanticHit]:
        """Search by text similarity. Returns top-k function matches."""
        if self._embeddings is None or len(self._embeddings) == 0:
            return []

        model = self._get_model()
        q_emb = model.encode([query], show_progress_bar=False)[0].astype(np.float32)

        # Cosine similarity via dot product (embeddings are normalized by sentence-transformers)
        scores = self._embeddings @ q_emb
        top_indices = np.argsort(scores)[::-1]

        # Deduplicate by FID — return best chunk per function
        seen_fids = set()
        results = []
        for idx in top_indices:
            fid = int(self._fids[idx])
            if fid in seen_fids:
                continue
            seen_fids.add(fid)
            results.append(SemanticHit(
                fid=fid,
                name=self._names[idx],
                score=float(scores[idx]),
                chunk_text=self._chunks[idx],
            ))
            if len(results) >= top_k:
                break

        return results

    @property
    def size(self) -> int:
        return len(self._chunks) if self._chunks else 0


def _chunk_source(source: str, chunk_size: int, overlap: int) -> list[str]:
    """Split source into token-approximate chunks with overlap."""
    # Approximate tokens as whitespace-split words (good enough for code)
    words = source.split()
    if len(words) <= chunk_size:
        return [source]

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + chunk_size, len(words))
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end >= len(words):
            break
        start += chunk_size - overlap

    return chunks
