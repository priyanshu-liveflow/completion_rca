"""Query agent — rewrites prompt, classifies intent, searches, routes, and explains.

Full QUERY flow:  rewrite → dual search → router (pick entry points) → explain agent
Full RCA flow:    rewrite → dual search → return hits for tiering (pipeline handles rest)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .prompt_search import search_dual
from .store import load_func_map, load_merged_flow
from .index.summary_index import get_summary_by_fid
from src.main.shared.llm import call_llm_loop
from src.main.shared.base import BlockContext
from src.main.shared.logging import get_logger
from .config import DomainConfig

log = get_logger("query_agent")

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass
class QueryResult:
    original_query: str
    rewritten_query: str
    intent: str  # "QUERY" or "RCA"
    hits: list[dict] = field(default_factory=list)
    routed_functions: list[str] = field(default_factory=list)  # selected by router
    explanation: str = ""  # filled for QUERY intent


async def _rewrite_query(raw_query: str, ctx: BlockContext, config: DomainConfig = None) -> tuple[str, str]:
    """Rewrite user query and classify intent. Returns (rewritten, intent)."""
    try:
        system = (PROMPTS_DIR / "query_rewrite.md").read_text()
        model = config.model_default if config else "us.anthropic.claude-sonnet-4-6"
        text, metrics = await call_llm_loop(
            provider=ctx.provider,
            system_prompt=system,
            user_message=raw_query,
            tools=None,
            max_turns=1,
            model=model,
        )
        ctx.metrics.add(metrics, model=model)

        intent = "RCA"
        rewritten = raw_query
        for line in text.strip().split("\n"):
            line = line.strip()
            if line.upper().startswith("INTENT:"):
                val = line.split(":", 1)[1].strip().upper()
                if val in ("QUERY", "RCA"):
                    intent = val
            elif line.upper().startswith("REWRITTEN:"):
                val = line.split(":", 1)[1].strip().strip('"').strip("'")
                if val and len(val) > 5:
                    rewritten = val

        return rewritten, intent
    except Exception as e:
        log.debug("rewrite_failed", error=str(e))
    return raw_query, "RCA"


def _build_router_input(hits: list[dict], repo: str) -> str:
    """Build rich context for the router: name, summary, and depth-3 call subtree for anchor/entry nodes."""
    func_map = load_func_map(repo)
    lines = []

    for i, h in enumerate(hits, 1):
        fid = h["fid"]
        name = h["name"]
        fm = func_map.get(str(fid), {})

        node_class = fm.get("node_class", "internal")

        # Get summary by fid (direct lookup, no semantic mismatch)
        summary = ""
        if fid:
            summary = get_summary_by_fid(repo, fid)

        lines.append(f"{i}. {name} [{node_class}]")
        lines.append(f"   Summary: {summary}")

        # Full detail for top 10 only
        if i <= 10:
            if node_class in ("entry", "anchor", "internal"):
                # Show callees (subflows)
                subtree = _get_call_subtree(fid, func_map, depth=3)
                if subtree:
                    lines.append(f"   Subflows:")
                    for branch in subtree:
                        lines.append(f"     → {branch}")
            if node_class in ("leaf", "utility"):
                # Show callers — who calls this function
                callers = fm.get("callers", [])
                caller_names = [func_map.get(c, {}).get("name", "") for c in callers[:5] if func_map.get(c, {}).get("name")]
                if caller_names:
                    lines.append(f"   Called by: {', '.join(caller_names)}")
        lines.append("")

    return "\n".join(lines)


def _get_call_subtree(fid: int, func_map: dict, depth: int = 3) -> list[str]:
    """Get call chain paths from a function up to `depth` levels. Returns list of paths."""
    paths = []
    
    def _walk(current_fid, path, d):
        if d >= depth:
            paths.append(" → ".join(path))
            return
        callees = func_map.get(str(current_fid), {}).get("callees", [])
        if not callees:
            if len(path) > 1:
                paths.append(" → ".join(path))
            return
        for cfid in callees[:4]:
            cname = func_map.get(str(cfid), {}).get("name", "")
            if cname and cname not in path:
                _walk(cfid, path + [cname], d + 1)

    root_name = func_map.get(str(fid), {}).get("name", "?")
    _walk(fid, [root_name], 0)
    return paths[:6]


async def _route_query(query: str, hits: list[dict], repo: str, ctx: BlockContext, config: DomainConfig) -> list[str]:
    """Pick 1-3 best starting functions from hits."""
    system = (PROMPTS_DIR / "query_router.md").read_text()
    router_input = _build_router_input(hits, repo)
    user_msg = f"User question: {query}\n\nCandidates:\n{router_input}"

    text, metrics = await call_llm_loop(
        provider=ctx.provider,
        system_prompt=system,
        user_message=user_msg,
        tools=None,
        max_turns=1,
        model=config.model_default,
    )
    ctx.metrics.add(metrics, model=config.model_default)

    # Parse SELECTED: func1, func2
    selected = []
    for line in text.strip().split("\n"):
        if line.upper().startswith("SELECTED:"):
            names = line.split(":", 1)[1].strip()
            selected = [n.strip() for n in names.split(",") if n.strip()]
            break

    # Fallback: pick top 2 hits
    if not selected:
        selected = [h["name"] for h in hits[:2]]

    log.info("query_routed", selected=selected)
    return selected


async def _run_explain_agent(
    functions: list[str], query: str, repo: str, ctx: BlockContext, config: DomainConfig
) -> str:
    """Run explain agents in parallel — one per function, merge results."""
    from .trace_agent import run_trace_agent
    from .decompose import AgentAssignment
    import asyncio

    system = (PROMPTS_DIR / "explain_agent.md").read_text()
    func_map = load_func_map(repo)

    async def _explain_one(fname: str, idx: int) -> str:
        fid = next((fid for fid, fm in func_map.items() if fm.get("name") == fname), None)
        context_lines = [f"User question: {query}", ""]
        if fid:
            fm = func_map[fid]
            callees = [func_map.get(c, {}).get("name", "") for c in fm.get("callees", [])[:10]]
            context_lines.append(f"Function: {fname} (class={fm.get('class','')}, node_class={fm.get('node_class','')})")
            context_lines.append(f"  Callees: {', '.join(c for c in callees if c)}")

        assignment = AgentAssignment(
            id=f"explain_{idx}",
            starting_node=fname,
            scope=f"Explain: {query}",
            direction="forward",
            model="heavy",
            tools="graph_plus_codebase",
            path_slice=[fname],
        )
        report = await run_trace_agent(
            assignment, config, ctx, repo,
            log_context="\n".join(context_lines),
            system_override=system,
            raw_output=True,
        )
        return report.assessment if report else ""

    results = await asyncio.gather(*[_explain_one(f, i) for i, f in enumerate(functions, 1)])
    return "\n\n---\n\n".join(r for r in results if r)


async def run_query_agent(
    raw_query: str,
    repo: str,
    ctx: BlockContext,
    config: DomainConfig | None = None,
    top_k: int = 20,
) -> QueryResult:
    """Full query agent pipeline.

    QUERY intent: rewrite → search → route → explain → structured answer
    RCA intent:   rewrite → search → return hits (pipeline does tiering + decompose)
    """
    # Step 1: Rewrite + classify
    rewritten, intent = await _rewrite_query(raw_query, ctx, config)
    log.info("query_agent", original=raw_query, rewritten=rewritten, intent=intent)

    # Step 2: Dual search with domain routing (both original and rewritten)
    hits_rewritten = search_dual(repo, rewritten, top_k=top_k)
    hits_original = search_dual(repo, raw_query, top_k=top_k)

    merged: dict[int, dict] = {}
    for h in hits_original:
        merged[h["fid"]] = h
    for h in hits_rewritten:
        if h["fid"] not in merged or h["score"] > merged[h["fid"]]["score"]:
            merged[h["fid"]] = h

    ranked = sorted(merged.values(), key=lambda x: x["score"], reverse=True)[:top_k]

    log.info("query_search_done", hits=len(ranked),
             top=ranked[0]["name"] if ranked else "?",
             top_score=f"{ranked[0]['score']:.3f}" if ranked else "0")

    result = QueryResult(
        original_query=raw_query,
        rewritten_query=rewritten,
        intent=intent,
        hits=ranked,
    )

    # Step 3: Route + explain/investigate (both intents use the agent when no log file)
    if config and ranked:
        selected = await _route_query(rewritten, ranked, repo, ctx, config)
        result.routed_functions = selected

        explanation = await _run_explain_agent(selected, rewritten, repo, ctx, config)
        result.explanation = explanation
        log.info("query_explained", functions=selected, explanation_len=len(explanation))

    return result


@dataclass
class InteractiveCandidate:
    name: str
    score: float
    source: str
    fid: int
    summary: str


async def get_interactive_candidates(
    raw_query: str, repo: str, ctx: BlockContext, config: DomainConfig | None = None, top_k: int = 20
) -> tuple[str, str, list[InteractiveCandidate]]:
    """Rewrite query and return candidates with summaries for user selection.
    
    Returns (rewritten_query, intent, candidates).
    """
    rewritten, intent = await _rewrite_query(raw_query, ctx, config)
    repo_name = repo.split("/")[-1] if "/" in repo else repo
    hits = search_dual(repo_name, rewritten, top_k=top_k)

    from .router import _load_summaries_map
    smap = _load_summaries_map(repo_name)

    candidates = [
        InteractiveCandidate(
            name=h["name"], score=h["score"], source=h["source"],
            fid=h["fid"], summary=smap.get(h["fid"], ""),
        )
        for h in hits
    ]
    return rewritten, intent, candidates


async def run_interactive_explain(
    functions: list[str], query: str, repo: str, ctx: BlockContext, config: DomainConfig | None = None
) -> str:
    """Run explain agent on user-selected functions. Returns explanation text."""
    return await _run_explain_agent(functions, query, repo, ctx, config)
