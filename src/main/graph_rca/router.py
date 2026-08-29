"""Pre-decompose router — filters error clusters by relevance to user prompt.

Autonomous: Haiku classifies clusters as relevant/irrelevant.
Interactive: returns cluster list with summaries for user selection.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from src.main.shared.llm import call_llm_loop, parse_json
from src.main.shared.base import BlockContext
from src.main.shared.logging import get_logger
from .models import WalkablePath
from .config import DomainConfig
from .store import load_func_map

log = get_logger("router")

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass
class ClusterSummary:
    cluster_id: str
    anchor_function: str
    fid: int
    error_count: int
    sample_messages: list[str]
    related_functions: list[str]
    summary: str = ""


@dataclass
class RouterResult:
    relevant: list[ClusterSummary]
    irrelevant: list[ClusterSummary]
    mode: str  # "autonomous" | "interactive"


def _group_errors_by_fid(path: WalkablePath, repo: str) -> list[ClusterSummary]:
    """Group error points by resolved fid into cluster summaries."""
    func_map = load_func_map(repo)
    fid_errors: dict[int, list[int]] = {}
    for idx in path.error_points:
        entry = path.entries[idx]
        fid = entry.originated_from_ids[0] if entry.originated_from_ids else -1
        fid_errors.setdefault(fid, []).append(idx)

    clusters = []
    for fid, indices in fid_errors.items():
        fm = func_map.get(str(fid), {}) if fid > 0 else {}
        name = fm.get("name", "UNMAPPED")
        samples = []
        for idx in indices[:5]:
            e = path.entries[idx]
            if e.stack_trace:
                samples.append(f"{e.stack_trace.exception}: {e.stack_trace.message}")
            else:
                samples.append(e.static_text or e.raw_text or "")
        # Neighbors
        related = set()
        for idx in indices[:3]:
            for offset in range(-3, 4):
                ni = idx + offset
                if 0 <= ni < len(path.entries) and ni != idx:
                    for fname in path.entries[ni].originated_from:
                        if fname != name:
                            related.add(fname)

        clusters.append(ClusterSummary(
            cluster_id=f"c_{fid}",
            anchor_function=name,
            fid=fid,
            error_count=len(indices),
            sample_messages=samples,
            related_functions=list(related)[:8],
            summary=fm.get("summary", ""),
        ))
    return sorted(clusters, key=lambda c: c.error_count, reverse=True)


async def route_clusters(
    path: WalkablePath,
    user_prompt: str,
    repo: str,
    config: DomainConfig,
    ctx: BlockContext,
) -> RouterResult:
    """Autonomous: Haiku filters clusters by relevance to user prompt."""
    clusters = _group_errors_by_fid(path, repo)

    if not user_prompt or not clusters:
        return RouterResult(relevant=clusters, irrelevant=[], mode="autonomous")

    system = (PROMPTS_DIR / "cluster_router.md").read_text()

    cluster_text = []
    for c in clusters:
        lines = [f"[{c.cluster_id}] {c.anchor_function} ({c.error_count} errors)"]
        if c.summary:
            lines.append(f"  Summary: {c.summary}")
        lines.append(f"  Errors: {'; '.join(c.sample_messages[:3])}")
        if c.related_functions:
            lines.append(f"  Related: {', '.join(c.related_functions)}")
        cluster_text.append("\n".join(lines))

    user_msg = f"User question: {user_prompt}\n\nClusters:\n" + "\n---\n".join(cluster_text)

    text, metrics = await call_llm_loop(
        provider=ctx.provider,
        system_prompt=system,
        user_message=user_msg,
        tools=None,
        max_turns=1,
        model=config.model_router,
    )
    ctx.metrics.add(metrics, model=config.model_router)

    parsed = parse_json(text)
    if not parsed or "relevant" not in parsed:
        log.warning("router_parse_failed", falling_back="all_relevant")
        return RouterResult(relevant=clusters, irrelevant=[], mode="autonomous")

    relevant_ids = {r["cluster_id"] for r in parsed["relevant"]}
    relevant = [c for c in clusters if c.cluster_id in relevant_ids]
    irrelevant = [c for c in clusters if c.cluster_id not in relevant_ids]

    log.info("router_done", total=len(clusters), relevant=len(relevant), irrelevant=len(irrelevant))
    return RouterResult(relevant=relevant, irrelevant=irrelevant, mode="autonomous")


def build_interactive_choices(path: WalkablePath, repo: str, tiered=None) -> dict:
    """Interactive: return full tiered view with summaries for user to pick from.

    Shows semantic hits (by tier) + error clusters, each with summary attached.
    User can select 'all', comma-separated IDs, or 'none'.
    """
    summaries_by_fid = _load_summaries_map(repo)
    clusters = _group_errors_by_fid(path, repo)

    # Attach summaries to clusters
    cluster_choices = []
    for c in clusters:
        c.summary = c.summary or summaries_by_fid.get(c.fid, "")
        cluster_choices.append({
            "id": c.cluster_id,
            "function": c.anchor_function,
            "error_count": c.error_count,
            "summary": c.summary or "; ".join(c.sample_messages[:2]),
            "related": c.related_functions[:5],
        })

    # Build tiered semantic hits with summaries
    tier1_choices, tier2_choices, tier3_choices = [], [], []
    if tiered:
        for hit in tiered.tier1:
            tier1_choices.append({
                "id": f"t1_{hit['fid']}",
                "function": hit["name"],
                "score": round(hit["score"], 3),
                "source": hit.get("source", ""),
                "log_count": hit.get("log_count", 0),
                "summary": summaries_by_fid.get(hit["fid"], ""),
            })
        for hit in tiered.tier2:
            tier2_choices.append({
                "id": f"t2_{hit['fid']}",
                "function": hit["name"],
                "score": round(hit["score"], 3),
                "source": hit.get("source", ""),
                "summary": summaries_by_fid.get(hit["fid"], ""),
            })
        for hit in tiered.tier3:
            tier3_choices.append({
                "id": f"t3_{hit['fid']}",
                "function": hit["name"],
                "level": hit.get("level", "ERROR"),
                "summary": summaries_by_fid.get(hit["fid"], ""),
            })

    return {
        "tier1": tier1_choices,
        "tier2": tier2_choices,
        "tier3": tier3_choices,
        "error_clusters": cluster_choices,
        "instructions": "Select what to investigate: 'all', comma-separated IDs, or 'none'",
        "total_errors": len(path.error_points),
    }


def _load_summaries_map(repo: str) -> dict[int, str]:
    """Load fid→summary mapping from summary index."""
    from .index.summary_index import repo_dir
    import numpy as np

    idx_dir = repo_dir(repo) / "summary_index"
    if not (idx_dir / "fids.npy").exists() or not (idx_dir / "summaries.txt").exists():
        return {}

    fids = np.load(idx_dir / "fids.npy")
    raw = (idx_dir / "summaries.txt").read_text(encoding="utf-8")
    texts = raw.split("\0")
    return {int(fids[i]): texts[i] for i in range(min(len(fids), len(texts))) if texts[i].strip()}


def select_clusters(path: WalkablePath, repo: str, selection: str) -> list[ClusterSummary]:
    """Parse user selection and return matching ClusterSummary objects.
    
    selection: "all" | "c_200" | "c_200, c_350, c_-1"
    """
    clusters = _group_errors_by_fid(path, repo)
    if selection.strip().lower() == "all":
        return clusters
    selected_ids = {s.strip() for s in selection.split(",")}
    return [c for c in clusters if c.cluster_id in selected_ids]


def filter_path_by_clusters(path: WalkablePath, selected: list[ClusterSummary]) -> list[int]:
    """Return filtered error_points for only the selected clusters."""
    selected_fids = {c.fid for c in selected}
    return [
        idx for idx in path.error_points
        if (path.entries[idx].originated_from_ids and path.entries[idx].originated_from_ids[0] in selected_fids)
        or (not path.entries[idx].originated_from_ids and -1 in selected_fids)
    ]
