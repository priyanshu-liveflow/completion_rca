"""CLI for Graph RCA — index a repo, query the code graph, or run RCA on a log."""

import asyncio

import typer

from src.main.shared.factory import make_provider
from src.main.shared.logging import configure_logging


def _run_code_rca(*, log, repo, config_file, model, prompt, interactive, visualize, output, provider, domain, verbose) -> dict:
    """Run code-rca mode. Returns result dict with status, tokens, analysis."""
    from pathlib import Path
    from src.main.graph_rca.config import DomainConfig
    from src.main.shared.base import BlockContext, RunMetrics

    if not repo:
        typer.echo("Error: --repo is required", err=True)
        raise typer.Exit(1)

    if not config_file:
        typer.echo(
            "Error: --config is required.\n\n"
            "  A YAML config tells the parser how to split log entries, extract fields,\n"
            "  and filter framework noise. Without it, the log appears as 1 giant entry.\n\n"
            "  Quick start:\n"
            "    cp configs/base/spring-boot.yaml configs/my-repo.yaml\n"
            "    # Edit: set repo, language, entry_start, line_pattern\n\n"
            "  Full guide: configs/WRITING_CONFIG.md\n"
            "  Example:    configs/ecmv4.yaml",
            err=True,
        )
        raise typer.Exit(1)

    domain_cfg = DomainConfig.from_yaml(config_file)

    from src.main.graph_rca.index.indexer import check_and_reindex
    repo_name = domain_cfg.repo or Path(repo).name
    check_and_reindex(repo, repo_name)

    if model:
        domain_cfg.model_light = model
        domain_cfg.model_default = model
        domain_cfg.model_heavy = model

    metrics = RunMetrics()
    ctx = BlockContext(provider=provider, domain=domain, dispatcher=None, metrics=metrics, verbose=verbose)
    log_file = str(Path(log).resolve())

    if interactive:
        pipeline_result = _run_code_rca_interactive(
            log_file=log_file, domain_cfg=domain_cfg, repo=repo, prompt=prompt, ctx=ctx)
    else:
        from src.main.graph_rca.pipeline import run_phased
        pipeline_result = asyncio.run(run_phased(
            config=domain_cfg, ctx=ctx, log_file=log_file, repo=repo,
            prompt=prompt, visualize=visualize, output_dir=output or "/tmp",
        ))

    return _format_rca_result(pipeline_result, metrics)


def _run_code_rca_interactive(*, log_file, domain_cfg, repo, prompt, ctx):
    """Interactive mode: prepare → display choices → user selects → investigate."""
    from src.main.graph_rca.phases import prepare
    from src.main.graph_rca.prompt_search import search_dual
    from src.main.graph_rca.router import _load_summaries_map

    repo_name = repo.split("/")[-1] if "/" in repo else repo

    typer.echo("\nPreprocessing log...", err=True)
    prepared = prepare(log_file if log_file else None, domain_cfg, repo, prompt)
    path = prepared.path

    if path:
        typer.echo(f"   {len(path.entries)} entries, {len(path.error_points)} errors", err=True)

    if not path and prompt:
        hits = search_dual(repo_name, prompt, top_k=20)
        smap = _load_summaries_map(repo_name)
        typer.echo(f"\n{'─'*60}\n  No log file — showing semantic matches for your query\n{'─'*60}", err=True)
        for i, h in enumerate(hits[:7], 1):
            s = smap.get(h["fid"], "")
            typer.echo(f"  {i}. \033[35m{h['name']}\033[0m  (score={h['score']:.3f}, {h['source']})", err=True)
            if s:
                typer.echo(f"     \033[37m{s}\033[0m", err=True)
        typer.echo("\n  Use `uv run graph-rca query` for detailed code explanation.", err=True)
        raise typer.Exit(0)

    if not path and not prompt:
        typer.echo("Provide --log and/or --prompt for interactive mode.", err=True)
        raise typer.Exit(1)

    all_items = _display_choices(prepared.choices)
    selection = typer.prompt("→")

    if selection.strip().lower() == "none":
        typer.echo("\nNo investigation.")
        raise typer.Exit(0)

    selected_ids = None
    if selection.strip().lower() != "all":
        try:
            nums = {int(x.strip()) for x in selection.split(",")}
            selected_ids = [item[1] for item in all_items if item[0] in nums]
        except ValueError:
            selected_ids = [s.strip() for s in selection.split(",")]

    typer.echo("\nRunning investigation...\n", err=True)
    from src.main.graph_rca.pipeline import run_phased
    return asyncio.run(run_phased(
        config=domain_cfg, ctx=ctx, prepared=prepared,
        repo=repo, prompt=prompt, selections=selected_ids,
    ))


def _display_choices(choices: dict) -> list[tuple]:
    """Display tiered interactive choices. Returns [(number, id, name), ...]."""
    all_items = []
    n = 1

    typer.echo(f"\n{'─'*60}", err=True)
    if choices.get("tier1"):
        typer.echo(f"  TIER 1 — In your question AND in the log\n{'─'*60}", err=True)
        for c in choices["tier1"]:
            typer.echo(f"  {n}. \033[35m{c['function']}\033[0m  (score={c['score']}, {c['log_count']} log lines)", err=True)
            if c.get("summary"):
                typer.echo(f"     \033[37m{c['summary']}\033[0m", err=True)
            all_items.append((n, c["id"], c["function"]))
            n += 1
        typer.echo("", err=True)

    if choices.get("tier2"):
        show_count = min(7, len(choices["tier2"]))
        typer.echo(f"{'─'*60}\n  TIER 2 — Matches your question, NOT in log ({len(choices['tier2'])} functions)\n{'─'*60}", err=True)
        for c in choices["tier2"][:show_count]:
            typer.echo(f"  {n}. \033[35m{c['function']}\033[0m  (score={c['score']}, {c['source']})", err=True)
            if c.get("summary"):
                typer.echo(f"     \033[37m{c['summary']}\033[0m", err=True)
            all_items.append((n, c["id"], c["function"]))
            n += 1
        if len(choices["tier2"]) > show_count:
            typer.echo(f"     ({len(choices['tier2'])-show_count} more — select 'all' to include them)", err=True)
        typer.echo("", err=True)

    if choices.get("error_clusters"):
        typer.echo(f"{'─'*60}\n  ERROR CLUSTERS in log ({choices['total_errors']} total errors)\n{'─'*60}", err=True)
        for c in choices["error_clusters"]:
            typer.echo(f"  {n}. \033[35m{c['function']}\033[0m  ({c['error_count']} errors)", err=True)
            if c.get("summary"):
                typer.echo(f"     \033[37m{c['summary']}\033[0m", err=True)
            all_items.append((n, c["id"], c["function"]))
            n += 1
        typer.echo("", err=True)

    if choices.get("tier3"):
        typer.echo(f"{'─'*60}\n  TIER 3 — Other errors, not matching question ({len(choices['tier3'])})\n{'─'*60}", err=True)
        for c in choices["tier3"][:7]:
            typer.echo(f"  {n}. \033[35m{c['function']}\033[0m  [{c['level']}]", err=True)
            if c.get("summary"):
                typer.echo(f"     \033[37m{c['summary']}\033[0m", err=True)
            all_items.append((n, c["id"], c["function"]))
            n += 1
        if len(choices["tier3"]) > 7:
            typer.echo(f"     ... and {len(choices['tier3'])-7} more", err=True)
        typer.echo("", err=True)

    typer.echo(f"{'─'*60}\n  Select: 'all' | numbers (e.g. 1,3,5) | 'none'\n{'─'*60}", err=True)
    return all_items


def _render_markdown(text: str):
    """Render markdown text with rich formatting in terminal."""
    from rich.console import Console
    from rich.markdown import Markdown
    console = Console()
    console.print(Markdown(text))


def _format_rca_result(pipeline_result, metrics) -> dict:
    """Format PipelineResult into the standard CLI result dict."""
    v = pipeline_result.final_verdict
    if v:
        analysis = (
            f"## Root Cause Analysis\n\n"
            f"**Root Cause:** {v.root_cause}\n"
            f"**Node:** {v.root_cause_node}\n"
            f"**Category:** {v.category}\n"
            f"**Confidence:** {v.confidence:.0%}\n\n"
            f"**Explanation:**\n{v.explanation}\n\n"
            f"**Evidence Chain:**\n" + "\n".join(f"  - {e}" for e in v.evidence_chain) + "\n"
        )
        if v.suggested_fix:
            analysis += f"\n**Suggested Fix:** {v.suggested_fix}\n"
    elif pipeline_result.short_circuited:
        if pipeline_result.trace_reports and pipeline_result.trace_reports[0].assessment:
            analysis = pipeline_result.trace_reports[0].assessment
        elif pipeline_result.walkable_path and pipeline_result.walkable_path.error_points:
            analysis = f"Short-circuited: {len(pipeline_result.walkable_path.error_points)} errors, all resolved via stack trace."
        else:
            analysis = "No actionable findings."
    else:
        analysis = "No errors found in log."

    return {
        "status": "complete",
        "turns": len(pipeline_result.trace_reports),
        "total_input_tokens": metrics.input_tokens,
        "total_output_tokens": metrics.output_tokens,
        "cache_read_tokens": metrics.cache_read,
        "cache_creation_tokens": metrics.cache_write,
        "tokens_by_model": metrics.by_model,
        "analysis": analysis,
    }


app = typer.Typer(
    name="graph-rca",
    help="Graph RCA — map application logs to a code graph and find root cause.",
    no_args_is_help=True,
)


@app.command()
def run(
    log: str = typer.Option(..., "--log", "-l", help="Path to the application log file"),
    repo: str = typer.Option(..., "--repo", "-r", help="Path to the repo for code graph analysis"),
    config_file: str = typer.Option(..., "--config", "-c", help="YAML domain config file"),
    model: str = typer.Option("", "--model", help="Override MODEL_ID for all pipeline stages"),
    prompt: str = typer.Option("", "--prompt", "-p", help="Focus prompt — biases decomposer toward specific issues"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Show cluster choices and let user select before investigating"),
    visualize: bool = typer.Option(False, "--visualize", help="Generate SVG visualizations"),
    output: str = typer.Option("", "--output", "-o", help="Save analysis markdown to this file or directory"),
    domain: str = typer.Option("", "--domain", "-d", help="Optional domain label for the run"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Print turn-by-turn progress to stderr"),
):
    """Run graph-driven RCA on an application log."""
    import os
    from datetime import datetime
    from pathlib import Path

    if model:
        os.environ["MODEL_ID"] = model

    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    log_file_path = str(logs_dir / f"code_rca_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl")
    configure_logging(verbose=verbose, log_file=log_file_path)

    try:
        provider = make_provider()
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)

    from src.main.config import get_cloud_provider_configs
    resolved_model = get_cloud_provider_configs().get("main_model", "")
    typer.echo(f"Model:    {resolved_model}")
    typer.echo(f"Log:      {log}")
    typer.echo(f"Repo:     {repo}")
    typer.echo("Running analysis…\n")

    result = _run_code_rca(
        log=log, repo=repo, config_file=config_file, model=model,
        prompt=prompt, interactive=interactive, visualize=visualize,
        output=output, provider=provider, domain=domain, verbose=verbose,
    )

    typer.echo("=" * 60)
    if result.get("time_taken"):
        typer.echo(f"Status: {result['status']}  |  Time: {result['time_taken']}s")
    else:
        typer.echo(f"Status: {result['status']}  |  Turns: {result['turns']}")
    typer.echo(
        f"Tokens — in:{result.get('total_input_tokens', 0):,}  "
        f"out:{result.get('total_output_tokens', 0):,}  "
        f"cache_read:{result.get('cache_read_tokens', 0):,}  "
        f"cache_write:{result.get('cache_creation_tokens', 0):,}"
    )
    for model_id, stats in result.get("tokens_by_model", {}).items():
        if not model_id:
            continue
        short = model_id.rsplit(".", 1)[-1] if "." in model_id else model_id
        typer.echo(
            f"  {short}: in={stats['input_tokens']:,} out={stats['output_tokens']:,} "
            f"cache_read={stats['cache_read']:,} cache_write={stats['cache_write']:,} calls={stats['turns']}"
        )
    typer.echo("=" * 60)
    _render_markdown(result["analysis"])

    if output:
        out_path = Path(output)
        if out_path.is_dir() or not out_path.suffix:
            out_path.mkdir(parents=True, exist_ok=True)
            out_path = out_path / "analysis.md"
        out_path.write_text(result["analysis"])
        typer.echo(f"\nSaved to {out_path}")


@app.command()
def index(
    repo: str = typer.Option(..., "--repo", "-r", help="Path to the source repo"),
    name: str = typer.Option("", "--name", "-n", help="Repo name (default: dirname)"),
    force: bool = typer.Option(False, "--force", "-f", help="Force reindex regardless of commit hash"),
    skip_codegraph: bool = typer.Option(False, "--skip-codegraph", help="Skip codegraphcontext (tree-sitter) step"),
    summary: bool = typer.Option(False, "--summary", help="Also build summary semantic index (requires ollama, adds ~1-3h)"),
):
    """Build or rebuild all indexes: codegraph → lite index → supplement → flow graphs."""
    from pathlib import Path
    configure_logging(verbose=True)

    repo_path = str(Path(repo).resolve())
    repo_name = name or Path(repo_path).name

    from src.main.graph_rca.index.indexer import index_repo
    stats = index_repo(repo_path, repo_name, force=force, skip_codegraph=skip_codegraph)

    if stats.get("status") == "up-to-date" and not summary:
        raise typer.Exit(0)

    if summary:
        from src.main.graph_rca.index.summary_index import build_summary_index, _load_functions_from_semantic_index
        functions = _load_functions_from_semantic_index(repo_name)
        if functions:
            small = sum(1 for _, _, s in functions if len(s.split()) >= 5 and len(s.split()) < 400)
            large = sum(1 for _, _, s in functions if len(s.split()) >= 400)
            est_seconds = small * 0.6 + large * 3.0
            est_min = est_seconds / 60
            typer.echo(f"\n[summary] {small + large} functions to summarize ({small} small → 0.5b, {large} large → 1.5b)")
            typer.echo(f"[summary] Estimated time: ~{est_min:.0f} minutes. Requires ollama running locally.")
            typer.echo("[summary] Starting...\n")
        sum_stats = build_summary_index(repo_name, verbose=True)
        if "error" in sum_stats:
            typer.echo(f"[summary] Error: {sum_stats['error']}", err=True)
        else:
            typer.echo(f"[summary] ✓ {sum_stats.get('functions_summarized', 0)} functions summarized")


@app.command()
def summarize(
    name: str = typer.Option(..., "--name", "-n", help="Repo name (must match indexed name)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show progress"),
):
    """Generate LLM summaries for all functions and build summary semantic index."""
    configure_logging(verbose=verbose)

    from src.main.graph_rca.index.summary_index import build_summary_index
    stats = build_summary_index(name, verbose=verbose)

    if "error" in stats:
        typer.echo(f"Error: {stats['error']}", err=True)
        raise typer.Exit(1)

    typer.echo(f"\n✓ Summary index built: {stats['functions_summarized']} functions "
               f"({stats['small_model']} small + {stats['large_model']} large), "
               f"{stats['errors']} errors, {stats['time_seconds']}s")


@app.command()
def query(
    prompt: str = typer.Argument(..., help="Your question about the codebase"),
    repo: str = typer.Option(..., "--repo", "-r", help="Repo name (must match indexed name)"),
    config: str = typer.Option("", "--config", "-c", help="Path to repo YAML config"),
    runtime: str = typer.Option("", "--runtime", "-R", help="Path to runtime YAML (models, budget). Overrides config models."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show debug output"),
    interactive: bool = typer.Option(False, "--interactive", "-i", help="Show candidates and let user select"),
):
    """Ask a question about the codebase. Routes to explain (QUERY) or RCA pipeline.

    Examples:
      uv run graph-rca query "how to upload sav file" --repo ecmv4-g2 --config configs/ecmv4.yaml
      uv run graph-rca query "what is the API to create a security system" --repo ecmv4-g2
    """
    configure_logging(verbose=verbose)

    from src.main.graph_rca.config import DomainConfig
    from src.main.shared.base import BlockContext, RunMetrics

    provider = make_provider()
    ctx = BlockContext(provider=provider, metrics=RunMetrics(), verbose=verbose)
    domain_config = DomainConfig.from_yaml(config) if config else DomainConfig()
    if runtime:
        domain_config.apply_runtime(runtime)

    async def _run():
        if interactive:
            from src.main.graph_rca.query_agent import get_interactive_candidates, run_interactive_explain

            rewritten, intent, candidates = await get_interactive_candidates(prompt, repo, ctx, domain_config)
            typer.echo(f"\n  Intent: {intent} | Rewritten: {rewritten}", err=True)

            typer.echo(f"\n{'─'*60}", err=True)
            typer.echo(f"  Candidates ({len(candidates)} matches)", err=True)
            typer.echo(f"{'─'*60}", err=True)
            for i, c in enumerate(candidates[:10], 1):
                typer.echo(f"  {i}. \033[35m{c.name}\033[0m  (score={c.score:.3f}, {c.source})", err=True)
                if c.summary:
                    typer.echo(f"     \033[37m{c.summary}\033[0m", err=True)
            if len(candidates) > 10:
                typer.echo(f"     ({len(candidates)-10} more — type 'more' to see)", err=True)

            typer.echo(f"\n{'─'*60}", err=True)
            selection = typer.prompt("Select (numbers e.g. 1,2,3 | all | more | none)")

            if selection.strip().lower() == "more" and len(candidates) > 10:
                for i, c in enumerate(candidates[10:], 11):
                    typer.echo(f"  {i}. \033[35m{c.name}\033[0m  (score={c.score:.3f}, {c.source})", err=True)
                    if c.summary:
                        typer.echo(f"     \033[37m{c.summary}\033[0m", err=True)
                typer.echo(f"\n{'─'*60}", err=True)
                selection = typer.prompt("Select (numbers e.g. 1,2,3 | all | none)")

            if selection.strip().lower() == "none":
                raise typer.Exit(0)

            if selection.strip().lower() == "all":
                functions = [c.name for c in candidates[:5]]
            else:
                try:
                    nums = {int(x.strip()) for x in selection.split(",")}
                    functions = [candidates[n-1].name for n in nums if 0 < n <= len(candidates)]
                except (ValueError, IndexError):
                    functions = [candidates[0].name]

            typer.echo(f"\nInvestigating: {', '.join(functions)}\n", err=True)
            explanation = await run_interactive_explain(functions, rewritten, repo, ctx, domain_config)
            typer.echo(f"\n{'='*60}")
            _render_markdown(explanation)
        else:
            from src.main.graph_rca.query_agent import run_query_agent

            result = await run_query_agent(prompt, repo, ctx, config=domain_config)
            typer.echo(f"\nIntent: {result.intent}")
            typer.echo(f"Rewritten: {result.rewritten_query}")
            typer.echo("\nTop hits:")
            for h in result.hits[:5]:
                typer.echo(f"  {h['score']:.3f} [{h['source']}] {h['name']}")
            if result.routed_functions:
                typer.echo(f"\nRouted to: {', '.join(result.routed_functions)}")
            if result.explanation:
                typer.echo(f"\n{'='*60}")
                _render_markdown(result.explanation)

    asyncio.run(_run())

    metrics = ctx.metrics
    if metrics.input_tokens > 0:
        typer.echo(f"\n{'─'*60}")
        typer.echo(
            f"Tokens — in:{metrics.input_tokens:,}  out:{metrics.output_tokens:,}  "
            f"cache_read:{metrics.cache_read:,}  cache_write:{metrics.cache_write:,}"
        )
        if metrics.by_model:
            for model_id, t in metrics.by_model.items():
                if not model_id:
                    continue
                short = model_id.split(":")[-1] if ":" in model_id else model_id.split("/")[-1]
                typer.echo(f"  {short}: in={t['input_tokens']:,} out={t['output_tokens']:,} cache_r={t['cache_read']:,} cache_w={t['cache_write']:,}")
        typer.echo(f"{'─'*60}")


def main():
    app()


if __name__ == "__main__":
    main()
