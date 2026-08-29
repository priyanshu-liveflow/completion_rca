"""Pipeline — wires PREPROCESS → DECOMPOSE → TRACE → ROUTE → JUDGE → FINAL together."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from src.main.shared.base import BlockContext
from src.main.shared.logging import get_logger
from .config import DomainConfig
from .models import WalkablePath
from .preprocess import preprocess_chunked
from .preprocess.parser import parse_log_entries
from .resolve import resolve_entries
from .decompose import decompose, AgentAssignment
from .trace_agent import run_trace_agent, TraceReport
from .judges import route, run_lens_judge, run_final_judge, LensVerdict, FinalVerdict
from .staleness import check_staleness
from .visualize import render_walkable_path, render_traces, render_verdict

log = get_logger("pipeline")


@dataclass
class PipelineResult:
    walkable_path: WalkablePath
    assignments: list[AgentAssignment]
    trace_reports: list[TraceReport]
    lenses: list[str]
    lens_verdicts: list[LensVerdict]
    final_verdict: FinalVerdict | None
    short_circuited: bool = False


async def run_pipeline(
    log_text: str,
    repo_path: str,
    config: DomainConfig,
    ctx: BlockContext,
    jira_context: str | None = None,
    visualize: bool = False,
    output_dir: str = "/tmp",
    log_file: str | None = None,
    focus_prompt: str = "",
) -> PipelineResult:
    """DEPRECATED: Use run_phased() instead. Kept for backward compat (MCP tools)."""

    # 0. Staleness check
    try:
        status = check_staleness(repo_path)
        if status and status.get("is_stale"):
            log.warning("index_stale", indexed=status.get('indexed_commit', '?')[:8], current=status.get('current_commit', '?')[:8])
    except Exception as e:
        log.debug("staleness_check_skipped", error=str(e))

    # 1. PREPROCESS — use chunked parallel for large files
    import os
    LARGE_FILE_THRESHOLD = 50 * 1024 * 1024  # 50MB

    if log_file and os.path.getsize(log_file) > LARGE_FILE_THRESHOLD:
        from .preprocess.chunked import preprocess_chunked
        from .models import BranchPoint
        log.info("pipeline_start", repo=repo_path, file=log_file, size_mb=round(os.path.getsize(log_file) / 1024 / 1024, 1), mode="chunked")
        entries = preprocess_chunked(log_file, config)
        # Filter framework/init noise before resolution (same as small-file path)
        if config.ignore_patterns:
            import re
            ignore_pats = [re.compile(p) for p in config.ignore_patterns]
            entries = [e for e in entries if not any(p.search(e.raw_text) for p in ignore_pats)]
        if config.known_errors:
            import re
            known_pats = [re.compile(ke["pattern"]) for ke in config.known_errors if "pattern" in ke]
            entries = [e for e in entries if not any(p.search(e.raw_text) for p in known_pats)]
        log.info("filtered", entries=len(entries))
        entries, branches = resolve_entries(entries, repo_path, config)
        mapped = sum(1 for e in entries if e.resolution_tier <= 3)
        coverage = (mapped / len(entries) * 100) if entries else 0.0
        error_points = [i for i, e in enumerate(entries) if e.is_error]
        path = WalkablePath(entries=entries, branches=branches, error_points=error_points,
                           coverage_pct=round(coverage, 1), service=config.service_name, repo=repo_path)
    else:
        if not log_text and log_file:
            log_text = open(log_file).read()
        log.info("pipeline_start", repo=repo_path, log_chars=len(log_text))
        entries = parse_log_entries(log_text, config)
        # Filter known benign errors
        if config.known_errors:
            import re
            known_pats = [re.compile(ke["pattern"]) for ke in config.known_errors if "pattern" in ke]
            entries = [e for e in entries if not any(p.search(e.raw_text) for p in known_pats)]
        entries, branches = resolve_entries(entries, repo_path, config)
        mapped = sum(1 for e in entries if e.resolution_tier <= 3)
        coverage = (mapped / len(entries) * 100) if entries else 0.0
        error_points = [i for i, e in enumerate(entries) if e.is_error]
        path = WalkablePath(entries=entries, branches=branches, error_points=error_points,
                           coverage_pct=round(coverage, 1), service=config.service_name, repo=repo_path)

    log.info("preprocessed", entries=len(path.entries), coverage_pct=path.coverage_pct, errors=len(path.error_points))
    path.build_fid_index()

    # 1.5 FLOW ALIGNMENT — group by thread, align against expected flows
    flow_context = ""
    try:
        from .align.orchestrate import align_error_threads
        flow_context = align_error_threads(path, repo_path)
    except Exception as e:
        log.debug("flow_alignment_skipped", error=str(e))

    # Short-circuit: no errors
    if not path.error_points:
        log.info("no_errors_found")
        return PipelineResult(
            walkable_path=path, assignments=[], trace_reports=[],
            lenses=[], lens_verdicts=[], final_verdict=None, short_circuited=True,
        )

    # Short-circuit: obvious single cause
    if _is_obvious(path, config):
        verdict = _obvious_verdict(path)
        log.info("obvious_cause", root=verdict.root_cause_node)
        return PipelineResult(
            walkable_path=path, assignments=[], trace_reports=[],
            lenses=[], lens_verdicts=[], final_verdict=verdict, short_circuited=True,
        )

    # 2. PROMPT-GUIDED SEMANTIC SEARCH + TIERING
    tiered_context = ""
    if focus_prompt:
        from .prompt_search import build_tiered_context
        repo_name = repo_path.split("/")[-1]
        tiered = build_tiered_context(focus_prompt, path, repo_name)
        tiered_context = tiered.to_decomposer_context()
        if tiered_context:
            log.info("prompt_tiering", tier1=len(tiered.tier1), tier2=len(tiered.tier2), tier3=len(tiered.tier3))

    # 3. ROUTE — filter clusters by relevance to user prompt (or present choices)
    if path.error_points:
        from .router import route_clusters, filter_path_by_clusters
        repo_name = repo_path.split("/")[-1] if "/" in repo_path else repo_path
        router_result = await route_clusters(path, focus_prompt, repo_name, config, ctx)
        if router_result.irrelevant:
            filtered_errors = filter_path_by_clusters(path, router_result.relevant)
            log.info("router_filtered", before=len(path.error_points), after=len(filtered_errors),
                     dropped=[c.anchor_function for c in router_result.irrelevant])
            path.error_points = filtered_errors

    # 4. DECOMPOSE
    decompose_focus = tiered_context if tiered_context else focus_prompt
    assignments = await decompose(path, config, ctx, flow_context=flow_context, focus_prompt=decompose_focus)

    # Mark Tier 2 (absence) assignments so dispatch doesn't gate them on error ownership
    if focus_prompt and tiered_context:
        tier2_names = {f["name"].lower() for f in tiered.tier2}
        for a in assignments:
            if a.starting_node.lower() in tier2_names:
                a.context_mode = "absence"

    log.info("decomposed", agents=len(assignments))
    for a in assignments:
        slice_str = f" path=[{' → '.join(a.path_slice)}]" if a.path_slice else ""
        log.debug("agent_assignment", agent=a.id, start=a.starting_node, model=a.model, direction=a.direction, path_slice=slice_str)

    # 3. TRACE (parallel)
    trace_reports = await _run_traces_parallel(assignments, config, ctx, repo_path, path=path)
    log.info("traces_complete", reports=len(trace_reports))
    for r in trace_reports:
        log.debug("trace_report", agent=r.agent_id, confidence=f"{r.confidence:.2f}", root=r.root_cause_node,
                  path=" → ".join(r.path_walked), assessment=r.assessment,
                  dead_ends=r.dead_ends if r.dead_ends else None)

    # Early exit: single agent with high confidence
    if len(trace_reports) == 1 and trace_reports[0].confidence >= config.early_exit_confidence:
        r = trace_reports[0]
        log.info("early_exit", confidence=f"{r.confidence:.2f}")
        return PipelineResult(
            walkable_path=path, assignments=assignments, trace_reports=trace_reports,
            lenses=[], lens_verdicts=[],
            final_verdict=FinalVerdict(
                root_cause=r.assessment, root_cause_node=r.root_cause_node,
                category="input" if r.is_input_issue else "code",
                confidence=r.confidence, evidence_chain=[e.content for e in r.evidence],
                winning_lens="single_trace", explanation=r.assessment, suggested_fix=None,
            ),
            short_circuited=True,
        )

    # 4. ROUTE
    lenses = await route(trace_reports, config, ctx)
    log.info("routed", lenses=lenses)

    # 5. LENS JUDGES (parallel)
    lens_verdicts = await _run_judges_parallel(lenses, trace_reports, jira_context, config, ctx)
    for v in lens_verdicts:
        log.debug("lens_verdict", lens=v.lens, confidence=f"{v.confidence:.2f}")

    # 6. FINAL JUDGE
    final = await run_final_judge(lens_verdicts, trace_reports, config, ctx)
    log.info("final_verdict", category=final.category, confidence=f"{final.confidence:.2f}", root=final.root_cause_node)

    log.debug("token_usage", input=ctx.metrics.input_tokens, output=ctx.metrics.output_tokens, cache_read=ctx.metrics.cache_read, cache_write=ctx.metrics.cache_write)

    # Per-model token distribution
    model_totals: dict[str, dict] = {}
    for r in trace_reports:
        short = r.model.split(".")[-1] if "." in r.model else (r.model or "unknown")
        if short not in model_totals:
            model_totals[short] = {"agents": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
        model_totals[short]["agents"] += 1
        model_totals[short]["input"] += r.token_usage.get("input_tokens", 0)
        model_totals[short]["output"] += r.token_usage.get("output_tokens", 0)
        model_totals[short]["cache_read"] += r.token_usage.get("cache_read", 0)
        model_totals[short]["cache_write"] += r.token_usage.get("cache_write", 0)
    # Add judge calls
    judge_model = config.model_heavy.split(".")[-1] if "." in config.model_heavy else config.model_heavy
    model_totals.setdefault(judge_model, {"agents": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0})
    model_totals[judge_model]["judges"] = len(lenses) + 2  # router + lenses + final
    log.info("model_distribution", models=model_totals)

    if visualize:
        svg1 = render_walkable_path(path, output_dir)
        svg2 = render_traces(trace_reports, output_dir)
        svg3 = render_verdict(final, trace_reports, output_dir)
        log.info("visualizations", svg1=svg1, svg2=svg2, svg3=svg3)

    return PipelineResult(
        walkable_path=path, assignments=assignments, trace_reports=trace_reports,
        lenses=lenses, lens_verdicts=lens_verdicts, final_verdict=final,
    )


async def _run_traces_parallel(
    assignments: list[AgentAssignment], config: DomainConfig, ctx: BlockContext, repo_path: str,
    path: WalkablePath = None,
) -> list[TraceReport]:
    """Run trace agents. Parents first, then children with parent context."""
    from .trace_context_builder import build_agent_contexts, render_agent_context

    repo_name = repo_path.split("/")[-1]

    # Build per-agent pre-loaded context (source, flow graph, scoped cluster)
    agent_contexts = {}
    if path:
        built = build_agent_contexts(assignments, path, repo_name)
        agent_contexts = {ac.assignment.id: render_agent_context(ac) for ac in built}

        # Dump per-agent context stats
        for ac in built:
            log.debug("agent_context",
                      agent=ac.assignment.id,
                      fid=ac.validation.fid,
                      strategy=ac.validation.strategy,
                      source_chars=len(ac.source),
                      flow_chars=len(ac.flow_graph),
                      cluster_entries=len(ac.cluster_entries),
                      total_context_chars=len(agent_contexts.get(ac.assignment.id, "")),
                      warnings=ac.warnings or None)

    # Log which agents were deduped out and filter them from dispatch
    dispatched_ids = set(agent_contexts.keys())
    for a in assignments:
        if a.id not in dispatched_ids:
            log.debug("agent_deduped", agent=a.id, starting_node=a.starting_node)

    assignments = [a for a in assignments if a.id in dispatched_ids]
    parents = [a for a in assignments if not a.parent_agent]
    children = [a for a in assignments if a.parent_agent]

    parent_reports = {}
    if parents:
        tasks = [run_trace_agent(a, config, ctx, repo_path,
                                 log_context=agent_contexts.get(a.id, "")) for a in parents]
        results = await asyncio.gather(*tasks)
        for a, r in zip(parents, results):
            parent_reports[a.id] = r

    for child in children:
        if child.parent_agent in parent_reports:
            child.context_from_parent = parent_reports[child.parent_agent].assessment

    child_results = []
    if children:
        tasks = [run_trace_agent(a, config, ctx, repo_path,
                                 log_context=agent_contexts.get(a.id, "")) for a in children]
        child_results = await asyncio.gather(*tasks)

    return list(parent_reports.values()) + list(child_results)


def _build_log_context(path: WalkablePath) -> str:
    """Build concise execution context from the walkable path for trace agents."""
    lines = ["Execution flow (from log resolution):"]
    for i, entry in enumerate(path.entries):
        if i > 30:
            lines.append(f"  ... ({len(path.entries) - 30} more entries)")
            break
        func = entry.originated_from[0] if entry.originated_from else "UNMAPPED"
        marker = " ← ERROR" if i in path.error_points else ""
        tier = f"[T{entry.resolution_tier}]"
        lines.append(f"  {tier} {func}{marker}")
        if entry.stack_trace and i in path.error_points:
            lines.append(f"       Exception: {entry.stack_trace.exception}: {entry.stack_trace.message}")
    return "\n".join(lines)


async def _run_judges_parallel(
    lenses: list[str], trace_reports: list[TraceReport],
    jira_context: str | None, config: DomainConfig, ctx: BlockContext,
) -> list[LensVerdict]:
    """Run lens judges in parallel."""
    tasks = [
        run_lens_judge(lens, trace_reports, jira_context, config, ctx)
        for lens in lenses
    ]
    return await asyncio.gather(*tasks)


def _is_obvious(path: WalkablePath, config: DomainConfig) -> bool:
    """Check if all errors are obvious (stack trace, single function, high confidence)."""
    if not config.skip_judges_if_single_trace:
        return False
    for idx in path.error_points:
        e = path.entries[idx]
        if e.resolution_tier != 1 or not e.stack_trace:
            return False
    roots = set()
    for idx in path.error_points:
        e = path.entries[idx]
        # Use resolved app frame (trace_path[0]) not raw frames[0] which may be framework
        if e.trace_path:
            roots.add(e.trace_path[0])
        elif e.originated_from:
            roots.add(e.originated_from[0])
        else:
            return False
    return len(roots) == 1


def _obvious_verdict(path: WalkablePath) -> FinalVerdict:
    """Build verdict for obvious single-cause failures."""
    e = path.entries[path.error_points[0]]
    st = e.stack_trace
    node = e.trace_path[0] if e.trace_path else (e.originated_from[0] if e.originated_from else None)
    return FinalVerdict(
        root_cause=f"{st.exception}: {st.message}" if st else e.static_text,
        root_cause_node=node,
        category="code",
        confidence=0.9,
        evidence_chain=[f"Stack trace at L{e.line_number}", node or ""],
        winning_lens="stack_trace_direct",
        explanation=f"Direct stack trace resolution: {st.exception} at {node}",
        suggested_fix=None,
    )


# ═══════════════════════════════════════════════════════════
# PHASED PIPELINE — single entry point, assembled at runtime
# ═══════════════════════════════════════════════════════════

async def run_phased(
    config: DomainConfig,
    ctx: BlockContext,
    prepared: "PreparedContext | None" = None,
    log_file: str | None = None,
    repo: str = "",
    prompt: str = "",
    selections: list[str] | None = None,
    mode: str = "auto",  # "auto" | "explain" | "rca"
    jira_context: str | None = None,
    visualize: bool = False,
    output_dir: str = "/tmp",
) -> PipelineResult:
    """Single pipeline entry point — assembles phases based on inputs.

    Modes:
      auto    — picks explain or rca based on selections + log presence
      explain — Phase 2A only (code walkthrough, no log needed)
      rca     — Phase 2B + Phase 3 (full error investigation)
    """
    from .phases import prepare, explain, investigate, judge
    from .staleness import check_staleness

    # Staleness check
    try:
        status = check_staleness(repo)
        if status and status.get("is_stale"):
            log.warning("index_stale", indexed=status.get('indexed_commit', '?')[:8], current=status.get('current_commit', '?')[:8])
    except Exception:
        pass

    # Phase 1: reuse or build
    if not prepared:
        prepared = prepare(log_file, config, repo, prompt)

    # Short-circuit: no errors and no prompt → nothing to do
    if prepared.path and not prepared.path.error_points and not prompt:
        return PipelineResult(
            walkable_path=prepared.path, assignments=[], trace_reports=[],
            lenses=[], lens_verdicts=[], final_verdict=None, short_circuited=True,
        )

    # Short-circuit: obvious single cause
    if prepared.path and prepared.path.error_points and _is_obvious(prepared.path, config):
        verdict = _obvious_verdict(prepared.path)
        log.info("obvious_cause", root=verdict.root_cause_node)
        return PipelineResult(
            walkable_path=prepared.path, assignments=[], trace_reports=[],
            lenses=[], lens_verdicts=[], final_verdict=verdict, short_circuited=True,
        )

    # Decide mode
    if mode == "auto":
        has_log_errors = prepared.path and prepared.path.error_points
        if selections:
            tier2_sel = [s for s in selections if s.startswith("t2_")]
            cluster_sel = [s for s in selections if s.startswith("c_")]
            if tier2_sel and not cluster_sel:
                mode = "explain"
            else:
                mode = "rca"
        elif has_log_errors:
            mode = "rca"
        else:
            mode = "explain"

    # Phase 2A: Explain
    if mode == "explain":
        functions = []
        if selections and prepared.choices:
            all_choices = (prepared.choices.get("tier1", []) +
                          prepared.choices.get("tier2", []) +
                          prepared.choices.get("tier3", []) +
                          prepared.choices.get("error_clusters", []))
            id_to_func = {c["id"]: c["function"] for c in all_choices}
            functions = [id_to_func[s] for s in selections if s in id_to_func]
        if not functions and prompt:
            from .prompt_search import search_dual
            repo_name = repo.split("/")[-1] if "/" in repo else repo
            hits = search_dual(repo_name, prompt, top_k=3)
            functions = [h["name"] for h in hits]

        result = await explain(functions, prompt or "explain these functions", repo, ctx, config)
        from .trace_agent import TraceReport
        report = TraceReport(
            agent_id="explain", path_walked=functions, evidence=[],
            assessment=result.explanation, root_cause_node=None,
            is_input_issue=False, confidence=1.0,
        )
        return PipelineResult(
            walkable_path=prepared.path or WalkablePath(entries=[], error_points=[]),
            assignments=[], trace_reports=[report],
            lenses=[], lens_verdicts=[], final_verdict=None, short_circuited=True,
        )

    # Phase 2B: Investigate (RCA)
    cluster_ids = [s for s in (selections or []) if s.startswith("c_")]
    result = await investigate(prepared, config, ctx, selected_cluster_ids=cluster_ids or None)

    if not result.trace_reports:
        return PipelineResult(
            walkable_path=prepared.path, assignments=result.assignments,
            trace_reports=[], lenses=[], lens_verdicts=[], final_verdict=None,
        )

    # Phase 3: Judge
    verdict = await judge(result.trace_reports, config, ctx, jira_context=jira_context)

    final = FinalVerdict(
        root_cause=verdict.root_cause, root_cause_node=verdict.root_cause_node,
        category=verdict.category, confidence=verdict.confidence,
        explanation=verdict.explanation, evidence_chain=verdict.evidence_chain,
        suggested_fix=verdict.suggested_fix, winning_lens=verdict.lenses[0] if verdict.lenses else "",
    )

    # Token logging
    log.debug("token_usage", input=ctx.metrics.input_tokens, output=ctx.metrics.output_tokens,
              cache_read=ctx.metrics.cache_read, cache_write=ctx.metrics.cache_write)

    # Visualize
    if visualize and prepared.path:
        svg1 = render_walkable_path(prepared.path, output_dir)
        svg2 = render_traces(result.trace_reports, output_dir)
        svg3 = render_verdict(final, result.trace_reports, output_dir)
        log.info("visualizations", svg1=svg1, svg2=svg2, svg3=svg3)

    return PipelineResult(
        walkable_path=prepared.path, assignments=result.assignments,
        trace_reports=result.trace_reports, lenses=verdict.lenses,
        lens_verdicts=verdict.lens_verdicts, final_verdict=final,
    )
