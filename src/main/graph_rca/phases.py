"""Pipeline phases — separated concerns, composable at runtime.

Phase 1: PREPARE   — stateless preprocessing, reusable across modes
Phase 2: INVESTIGATE — mode-based (explain OR rca)  
Phase 3: JUDGE     — multi-lens convergence (only for rca mode)
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.main.shared.base import BlockContext
from src.main.shared.logging import get_logger
from .config import DomainConfig
from .models import WalkablePath
from .models.agents import TraceReport
from .models.context import PreparedContext, InvestigationResult, Verdict

log = get_logger("phases")


# ═══════════════════════════════════════════════════════════
# PHASE 1: PREPARE
# ═══════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════
# PHASE 1: PREPARE
# ═══════════════════════════════════════════════════════════

def prepare(
    log_file: str | None,
    config: DomainConfig,
    repo: str,
    prompt: str = "",
) -> PreparedContext:
    """Phase 1: Parse log, resolve, tier, build choices. Stateless, no LLM calls."""
    from .preprocess.parser import parse_log_entries
    from .preprocess.chunked import preprocess_chunked
    from .resolve import resolve_entries

    path = None

    if log_file and os.path.exists(log_file):
        LARGE = 50 * 1024 * 1024
        if os.path.getsize(log_file) > LARGE:
            entries = preprocess_chunked(log_file, config)
        else:
            entries = parse_log_entries(open(log_file).read(), config)

        # Filter noise
        if config.ignore_patterns:
            pats = [re.compile(p) for p in config.ignore_patterns]
            entries = [e for e in entries if not any(p.search(e.raw_text) for p in pats)]
        if config.known_errors:
            pats = [re.compile(ke["pattern"]) for ke in config.known_errors if "pattern" in ke]
            entries = [e for e in entries if not any(p.search(e.raw_text) for p in pats)]

        entries, branches = resolve_entries(entries, repo, config)
        mapped = sum(1 for e in entries if e.resolution_tier <= 3)
        coverage = (mapped / len(entries) * 100) if entries else 0.0
        error_points = [i for i, e in enumerate(entries) if e.is_error]
        path = WalkablePath(
            entries=entries, branches=branches, error_points=error_points,
            coverage_pct=round(coverage, 1), service=config.service_name, repo=repo,
        )
        path.build_fid_index()
        log.info("prepared", entries=len(entries), errors=len(error_points), coverage=f"{coverage:.1f}%")

    # Tier
    tiered = None
    if prompt and path:
        from .prompt_search import build_tiered_context
        repo_name = repo.split("/")[-1] if "/" in repo else repo
        tiered = build_tiered_context(prompt, path, repo_name)
        log.info("tiered", tier1=len(tiered.tier1), tier2=len(tiered.tier2), tier3=len(tiered.tier3))

    # Choices
    choices = None
    if path:
        from .router import build_interactive_choices
        repo_name = repo.split("/")[-1] if "/" in repo else repo
        choices = build_interactive_choices(path, repo_name, tiered=tiered)

    # Flow alignment
    flow_context = ""
    if path and path.error_points:
        try:
            from .align.orchestrate import align_error_threads
            flow_context = align_error_threads(path, repo)
        except Exception as e:
            log.debug("alignment_skipped", error=str(e))

    return PreparedContext(
        path=path, tiered=tiered, choices=choices,
        flow_context=flow_context, repo=repo, prompt=prompt,
    )


# ═══════════════════════════════════════════════════════════
# PHASE 2A: EXPLAIN (Tier 2 / query mode)
# ═══════════════════════════════════════════════════════════

async def explain(
    functions: list[str],
    query: str,
    repo: str,
    ctx: BlockContext,
    config: DomainConfig,
) -> InvestigationResult:
    """Phase 2A: Explain selected functions — code walkthrough, no log needed."""
    from .query_agent import _run_explain_agent, _route_query
    from .prompt_search import search_dual

    # Search to get scored hits for routing
    hits = search_dual(repo.split("/")[-1] if "/" in repo else repo, query)
    # Filter to only the selected functions
    selected_hits = [h for h in hits if h["name"] in functions] or hits[:len(functions)]

    explanation = await _run_explain_agent(functions, query, repo, ctx, config)
    return InvestigationResult(mode="explain", explanation=explanation)


# ═══════════════════════════════════════════════════════════
# PHASE 2B: INVESTIGATE (error RCA mode)
# ═══════════════════════════════════════════════════════════

async def investigate(
    prepared: PreparedContext,
    config: DomainConfig,
    ctx: BlockContext,
    selected_cluster_ids: list[str] | None = None,
) -> InvestigationResult:
    """Phase 2B: Decompose + trace on selected error clusters."""
    from .decompose import decompose
    from .router import route_clusters, filter_path_by_clusters, select_clusters

    path = prepared.path
    if not path or not path.error_points:
        return InvestigationResult(mode="rca")

    # Filter to selected clusters if provided
    if selected_cluster_ids:
        repo_name = prepared.repo.split("/")[-1] if "/" in prepared.repo else prepared.repo
        selected = select_clusters(path, repo_name, ",".join(selected_cluster_ids))
        filtered = filter_path_by_clusters(path, selected)
        path.error_points = filtered
    elif prepared.prompt:
        # Autonomous: let Haiku filter
        repo_name = prepared.repo.split("/")[-1] if "/" in prepared.repo else prepared.repo
        result = await route_clusters(path, prepared.prompt, repo_name, config, ctx)
        if result.irrelevant:
            path.error_points = filter_path_by_clusters(path, result.relevant)

    if not path.error_points:
        return InvestigationResult(mode="rca")

    # Decompose
    tiered_text = prepared.tiered.to_decomposer_context() if prepared.tiered else ""
    focus = tiered_text or prepared.prompt
    assignments = await decompose(path, config, ctx, flow_context=prepared.flow_context, focus_prompt=focus)

    # Mark absence agents
    if prepared.tiered and tiered_text:
        tier2_names = {f["name"].lower() for f in prepared.tiered.tier2}
        for a in assignments:
            if a.starting_node.lower() in tier2_names:
                a.context_mode = "absence"

    log.info("investigate_decomposed", agents=len(assignments))

    # Trace
    from .trace_context_builder import build_agent_contexts, render_agent_context
    from .trace_agent import run_trace_agent

    repo_name = prepared.repo.split("/")[-1] if "/" in prepared.repo else prepared.repo
    built = build_agent_contexts(assignments, path, repo_name)
    agent_contexts = {ac.assignment.id: render_agent_context(ac) for ac in built}

    dispatched = [ac.assignment for ac in built]
    log.info("investigate_dispatched", agents=len(dispatched))

    import asyncio
    tasks = [
        run_trace_agent(a, config, ctx, prepared.repo, log_context=agent_contexts.get(a.id, ""))
        for a in dispatched
    ]
    reports = await asyncio.gather(*tasks)
    trace_reports = [r for r in reports if r]

    return InvestigationResult(mode="rca", trace_reports=trace_reports, assignments=dispatched)


# ═══════════════════════════════════════════════════════════
# PHASE 3: JUDGE
# ═══════════════════════════════════════════════════════════

async def judge(
    trace_reports: list[TraceReport],
    config: DomainConfig,
    ctx: BlockContext,
    jira_context: str | None = None,
) -> Verdict:
    """Phase 3: Multi-lens judging → final verdict."""
    from .judges import route, run_lens_judge, run_final_judge

    if not trace_reports:
        return Verdict(root_cause="No evidence collected", root_cause_node=None,
                       category="unknown", confidence=0.0, explanation="No traces produced results.")

    # Early exit: single high-confidence agent
    if len(trace_reports) == 1 and trace_reports[0].confidence >= config.early_exit_confidence:
        r = trace_reports[0]
        return Verdict(
            root_cause=r.assessment, root_cause_node=r.root_cause_node,
            category="input" if r.is_input_issue else "code",
            confidence=r.confidence, explanation=r.assessment,
            evidence_chain=[e.content for e in r.evidence],
        )

    # Route → Lens → Final
    lenses = await route(trace_reports, config, ctx)
    log.info("judge_lenses", lenses=lenses)

    import asyncio
    lens_verdicts = await asyncio.gather(*[
        run_lens_judge(lens, trace_reports, jira_context, config, ctx)
        for lens in lenses
    ])

    final = await run_final_judge(lens_verdicts, trace_reports, config, ctx)
    log.info("judge_final", confidence=f"{final.confidence:.2f}", root=final.root_cause_node)

    return Verdict(
        root_cause=final.root_cause, root_cause_node=final.root_cause_node,
        category=final.category, confidence=final.confidence,
        explanation=final.explanation, evidence_chain=final.evidence_chain,
        suggested_fix=final.suggested_fix, lenses=lenses, lens_verdicts=lens_verdicts,
    )
