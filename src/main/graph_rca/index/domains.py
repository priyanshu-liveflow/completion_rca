"""Domain index — entry-point BFS + embedding for broad query routing.

Identifies domains by:
1. Finding entry points (in-degree=0, out-degree>0)
2. BFS forward (depth-limited) to get each entry point's subtree
3. Embedding the entry point's name + file + callees + summary as a searchable vector
4. At query time: query → cosine against domain vectors → top-K → narrow search to those fids
"""
from __future__ import annotations

import json
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..store import repo_dir
from src.main.shared.logging import get_logger

log = get_logger("domains")

BFS_DEPTH = 5
MIN_TREE_SIZE = 5


@dataclass
class DomainHit:
    domain_id: int
    label: str
    score: float
    fids: list[int]


def build_domain_index(repo: str, graph=None) -> dict:
    """Build domain index from graph entry points. Returns stats."""
    if graph is None:
        from src.main.code_tools import get_graph
        graph = get_graph()

    # Load all functions and edges
    funcs = graph.query(
        "MATCH (f:Function) WHERE f.path CONTAINS $repo RETURN id(f), f.name, f.path",
        params={"repo": repo},
    )
    edges = graph.query(
        "MATCH (a:Function)-[:CALLS]->(b:Function) "
        "WHERE a.path CONTAINS $repo AND b.path CONTAINS $repo RETURN id(a), id(b)",
        params={"repo": repo},
    )

    id_to_info = {r[0]: (r[1], r[2]) for r in funcs.result_set}
    adj_fwd = defaultdict(set)
    in_deg = defaultdict(int)
    for r in edges.result_set:
        adj_fwd[r[0]].add(r[1])
        in_deg[r[1]] += 1

    # Entry points: in-degree=0, has outgoing
    entry_points = [fid for fid in id_to_info if in_deg[fid] == 0 and len(adj_fwd[fid]) > 0]

    # Load summaries if available
    sum_dir = repo_dir(repo) / "summary_index"
    fid_to_summary = {}
    if (sum_dir / "summaries.txt").exists() and (sum_dir / "fids.npy").exists():
        sum_fids = np.load(sum_dir / "fids.npy")
        sum_texts = (sum_dir / "summaries.txt").read_text().splitlines()
        for i in range(min(len(sum_fids), len(sum_texts))):
            fid_to_summary[int(sum_fids[i])] = sum_texts[i]

    # BFS from each entry point
    def bfs(start):
        visited = set()
        queue = deque([(start, 0)])
        while queue:
            node, depth = queue.popleft()
            if node in visited or depth > BFS_DEPTH:
                continue
            visited.add(node)
            if depth < BFS_DEPTH:
                for nb in adj_fwd.get(node, []):
                    if nb not in visited:
                        queue.append((nb, depth + 1))
        return visited

    # Build domain texts for embedding
    domain_texts = []
    domain_fids = []
    domain_labels = []

    for ep in entry_points:
        tree = bfs(ep)
        if len(tree) < MIN_TREE_SIZE:
            continue

        ep_name, ep_path = id_to_info[ep]
        ep_file = ep_path.split("/")[-1].replace(".groovy", "").replace(".java", "")

        # Callee names (depth-1 only)
        callees = [id_to_info[c][0] for c in adj_fwd.get(ep, set()) if c in id_to_info][:5]

        # Entry point summary
        ep_sum = fid_to_summary.get(ep, "")[:200]

        # Domain text: name + file + callees + summary
        text = f"{ep_name} {ep_file} {' '.join(callees)} {ep_sum}"
        domain_texts.append(text)
        domain_fids.append(sorted(tree))
        domain_labels.append(f"{ep_name} ({ep_file})")

    if not domain_texts:
        log.warning("no_domains_found", repo=repo)
        return {"domains": 0}

    # Embed domain texts
    from ..store import get_embed_model

    model = get_embed_model()
    embeddings = model.encode(domain_texts, show_progress_bar=False, batch_size=256)
    embeddings = embeddings / np.linalg.norm(embeddings, axis=1, keepdims=True)

    # Save
    out_dir = repo_dir(repo) / "domain_index"
    out_dir.mkdir(exist_ok=True)
    np.save(out_dir / "embeddings.npy", embeddings.astype(np.float32))
    with open(out_dir / "domains.json", "w") as f:
        json.dump({"labels": domain_labels, "fids": domain_fids}, f)

    log.info("domain_index_built", domains=len(domain_texts), repo=repo)
    return {"domains": len(domain_texts)}


class DomainIndex:
    """Loads and searches the domain index."""

    def __init__(self):
        self._embeddings: np.ndarray | None = None
        self._labels: list[str] = []
        self._fids: list[list[int]] = []

    def load(self, repo: str) -> bool:
        d = repo_dir(repo) / "domain_index"
        if not (d / "embeddings.npy").exists():
            return False
        self._embeddings = np.load(d / "embeddings.npy")
        with open(d / "domains.json") as f:
            data = json.load(f)
        self._labels = data["labels"]
        self._fids = data["fids"]
        return True

    def search(self, query: str, top_k: int = 5) -> list[DomainHit]:
        """Find top-K domains matching query. Returns DomainHit with fid sets."""
        if self._embeddings is None:
            return []

        from ..store import get_embed_model

        model = get_embed_model()
        q_emb = model.encode([query])
        q_emb = q_emb / np.linalg.norm(q_emb)

        sims = (q_emb @ self._embeddings.T)[0]
        top_idx = np.argsort(sims)[-top_k:][::-1]

        return [
            DomainHit(
                domain_id=int(i),
                label=self._labels[i],
                score=float(sims[i]),
                fids=self._fids[i],
            )
            for i in top_idx
        ]

    def get_fids_for_domains(self, domain_ids: list[int]) -> set[int]:
        """Union of fids from selected domains."""
        result = set()
        for did in domain_ids:
            if 0 <= did < len(self._fids):
                result.update(self._fids[did])
        return result
