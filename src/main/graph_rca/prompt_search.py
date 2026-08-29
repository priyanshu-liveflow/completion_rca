"""Prompt-guided semantic search — dual index (source + summary) with priority tiering.

Given a user prompt and resolved log entries, produces tiered function lists:
  Tier 1: prompt hits ∩ executed functions (investigate first)
  Tier 2: prompt hits − executed functions (check absence)
  Tier 3: error functions outside prompt hits (explore last)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .store import semantic_search
from .index.summary_index import search_summaries
from .models import WalkablePath
from src.main.shared.logging import get_logger

log = get_logger("prompt_search")


@dataclass
class TieredContext:
    """Priority-tiered function lists for the decomposer."""
    prompt: str
    tier1: list[dict] = field(default_factory=list)  # prompt ∩ log (highest priority)
    tier2: list[dict] = field(default_factory=list)  # prompt − log (absence signal)
    tier3: list[dict] = field(default_factory=list)  # errors outside prompt

    def to_decomposer_context(self) -> str:
        """Format for injection into decomposer input."""
        lines = []

        if self.tier1:
            lines.append("## TIER 1 — INVESTIGATE FIRST (user suspects + confirmed execution)")
            lines.append("These functions match the user's description AND appear in the log.")
            for f in self.tier1:
                lines.append(f"  • {f['name']} (score={f['score']:.2f}, log_lines={f.get('log_count', 0)})")
            lines.append("")

        if self.tier2:
            lines.append("## TIER 2 — CHECK ABSENCE (user suspects but NOT in log)")
            lines.append("These match the user's description but did NOT execute. Maybe they SHOULD have been called.")
            for f in self.tier2:
                lines.append(f"  • {f['name']} (score={f['score']:.2f})")
            lines.append("")

        if self.tier3:
            lines.append("## TIER 3 — EXPLORE LAST (errors unrelated to user's description)")
            lines.append("Real errors but possibly unrelated. Only investigate if Tier 1+2 don't explain the issue.")
            for f in self.tier3[:5]:  # cap to avoid noise
                lines.append(f"  • {f['name']} [{f['level']}]")
            if len(self.tier3) > 5:
                lines.append(f"  ... and {len(self.tier3) - 5} more")
            lines.append("")

        return "\n".join(lines)


def search_dual(repo: str, query: str, top_k: int = 20, domain_filter: set[int] | None = None) -> list[dict]:
    """Three-lane search with reciprocal rank fusion.
    
    Each lane ranks independently. Functions get points based on position in each lane.
    Multi-lane consensus is rewarded — appearing in 2+ lanes boosts ranking.
    """
    from .index.summary_index import search_mechanisms

    k = top_k * 2 if domain_filter else top_k

    # Run all three lanes
    src_hits = semantic_search(repo, query, top_k=k)
    sum_hits = search_summaries(repo, query, top_k=k)
    mech_hits = search_mechanisms(repo, query, top_k=k)

    # Apply domain filter if provided
    if domain_filter:
        src_hits = [h for h in src_hits if h.fid in domain_filter]
        sum_hits = [h for h in sum_hits if h.fid in domain_filter]
        mech_hits = [h for h in mech_hits if h.fid in domain_filter]

    # Reciprocal Rank Fusion: score = sum(1 / (k + rank)) across lanes
    # k=60 is standard RRF constant (dampens top-rank dominance)
    RRF_K = 60
    fid_scores: dict[int, float] = {}
    fid_info: dict[int, dict] = {}
    fid_lanes: dict[int, int] = {}  # count of lanes

    for lane_name, hits in [("code", src_hits), ("summary", sum_hits), ("mechanism", mech_hits)]:
        seen_in_lane = set()
        for rank, h in enumerate(hits):
            if h.fid in seen_in_lane:
                continue
            seen_in_lane.add(h.fid)
            rrf_score = 1.0 / (RRF_K + rank + 1)
            fid_scores[h.fid] = fid_scores.get(h.fid, 0) + rrf_score
            fid_lanes[h.fid] = fid_lanes.get(h.fid, 0) + 1
            if h.fid not in fid_info:
                fid_info[h.fid] = {"fid": h.fid, "name": h.name, "score": h.score, "source": lane_name}
            elif h.score > fid_info[h.fid]["score"]:
                fid_info[h.fid]["score"] = h.score
                fid_info[h.fid]["source"] = lane_name

    # Build final results sorted by RRF score
    results = []
    for fid, rrf in sorted(fid_scores.items(), key=lambda x: -x[1]):
        entry = fid_info[fid].copy()
        entry["rrf_score"] = rrf
        entry["lanes"] = fid_lanes[fid]
        results.append(entry)
        if len(results) >= top_k:
            break

    return results


def search_with_domain_routing(repo: str, query: str, top_k: int = 20, domain_top_k: int = 5, min_domain_score: float = 0.40) -> list[dict]:
    """Domain-routed search: boost functions in relevant domains.
    
    Runs both domain-filtered AND unfiltered search, boosts domain-matched results.
    Falls back to unfiltered only if domain index unavailable.
    """
    from .index.domains import DomainIndex

    idx = DomainIndex()
    if not idx.load(repo):
        return search_dual(repo, query, top_k=top_k)

    domain_hits = idx.search(query, top_k=domain_top_k)
    good_domains = [d for d in domain_hits if d.score >= min_domain_score]

    if not good_domains:
        return search_dual(repo, query, top_k=top_k)

    # Collect fids from matched domains
    domain_fids = set()
    for d in good_domains:
        domain_fids.update(d.fids)

    log.info("domain_routing",
             query=query[:50],
             domains=len(good_domains),
             fids=len(domain_fids),
             top_domain=good_domains[0].label,
             top_score=f"{good_domains[0].score:.3f}")

    # Run unfiltered search, boost domain-matched results
    results = search_dual(repo, query, top_k=top_k * 2)
    
    # Apply boosts based on domain match and node class
    from .store import load_func_map
    func_map = load_func_map(repo)

    DOMAIN_BOOST = 0.05
    ENTRY_BOOST = 0.03  # entry/anchor have call graphs to trace
    LEAF_PENALTY = -0.03  # leaf nodes are dead ends for the agent

    for r in results:
        if r["fid"] in domain_fids:
            r["score"] += DOMAIN_BOOST
            r["domain_match"] = True
        # Boost by node class
        fm = func_map.get(r["fid"], {})
        cls = fm.get("node_class", "")
        if cls in ("entry", "anchor"):
            r["score"] += ENTRY_BOOST
        elif cls == "leaf":
            r["score"] += LEAF_PENALTY

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def build_tiered_context(
    prompt: str,
    path: WalkablePath,
    repo: str,
    top_k: int = 20,
    min_score: float = 0.35,
) -> TieredContext:
    """Build priority-tiered context from prompt + resolved log.

    Args:
        prompt: user's description of the issue
        path: resolved walkable path from log
        repo: repo name for index lookup
        top_k: max candidates from semantic search
        min_score: minimum score to include (filters noise)
    """
    ctx = TieredContext(prompt=prompt)

    # Dual semantic search
    candidates = search_dual(repo, prompt, top_k=top_k)
    candidates = [c for c in candidates if c["score"] >= min_score]

    if not candidates:
        log.info("prompt_search_no_hits", prompt=prompt[:60], min_score=min_score)
        return ctx

    # Collect executed fids from log
    executed_fids: dict[int, int] = {}  # fid → count of log lines
    for entry in path.entries:
        for fid in entry.originated_from_ids:
            executed_fids[fid] = executed_fids.get(fid, 0) + 1

    # Collect error function fids
    error_fids: set[int] = set()
    error_funcs: list[dict] = []
    for idx in path.error_points:
        e = path.entries[idx]
        if e.originated_from_ids:
            fid = e.originated_from_ids[0]
            if fid not in error_fids:
                error_fids.add(fid)
                error_funcs.append({
                    "fid": fid,
                    "name": e.originated_from[0] if e.originated_from else "?",
                    "level": e.level,
                })

    # Tier candidates
    candidate_fids = set(c["fid"] for c in candidates)

    for c in candidates:
        fid = c["fid"]
        if fid in executed_fids:
            c["log_count"] = executed_fids[fid]
            ctx.tier1.append(c)
        else:
            ctx.tier2.append(c)

    # Tier 3: error functions NOT in candidate set
    for ef in error_funcs:
        if ef["fid"] not in candidate_fids:
            ctx.tier3.append(ef)

    log.info("tiered_context",
             prompt=prompt[:50],
             tier1=len(ctx.tier1), tier2=len(ctx.tier2), tier3=len(ctx.tier3),
             top_hit=candidates[0]["name"] if candidates else "?",
             top_score=f"{candidates[0]['score']:.3f}" if candidates else "0")

    return ctx
