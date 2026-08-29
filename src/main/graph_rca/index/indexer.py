"""Unified indexer — builds all indexes with progress bars, auto-reindex on hash change."""
from __future__ import annotations

import subprocess
from pathlib import Path

from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.console import Console

from .cache import get_commit_hash, is_stale, save_cache, CACHE_DIR
from src.main.shared.logging import get_logger

log = get_logger("indexer")
console = Console()


def index_repo(
    repo_path: str,
    repo_name: str,
    force: bool = False,
    skip_codegraph: bool = False,
) -> dict:
    """Full index pipeline: codegraph → lite index → supplement → flow graphs.
    
    Auto-detects staleness via commit hash. Pass force=True to rebuild regardless.
    """
    repo_path = str(Path(repo_path).resolve())
    current_hash = get_commit_hash(repo_path)

    if not force and current_hash and not is_stale(repo_name, current_hash):
        console.print(f"[green]✓[/] Index up-to-date for [bold]{repo_name}[/] (commit {current_hash[:8]})")
        return {"status": "up-to-date", "commit": current_hash}

    console.print(f"[yellow]⟳[/] Indexing [bold]{repo_name}[/] (commit {current_hash[:8] if current_hash else 'unknown'})")

    stats = {}

    # 1. Codegraph context (has its own progress bar — runs outside our Progress)
    if not skip_codegraph:
        console.print("  [dim]Codegraph (tree-sitter → FalkorDB)...[/]")
        console.print("  [dim]  Note: after file scan hits 100%, CALLS resolution runs (5-8 min for large repos)[/]")
        cgc_result = _run_codegraph(repo_path)
        stats["codegraph"] = cgc_result
        console.print("  [green]✓[/] Codegraph done")

        # 1.5. Supplement: insert Function nodes that tree-sitter missed (BEFORE edge building)
        console.print("  [dim]Supplementing missing function definitions...[/]")
        from .groovy_func_supplement import supplement_missing_functions
        func_stats = supplement_missing_functions(repo_path, repo_name)
        stats["func_supplement"] = func_stats
        if func_stats.get("added", 0) > 0:
            console.print(f"  [green]✓[/] +{func_stats['added']} supplemental functions indexed")

        # 1.6. Supplement: add synthetic CALLS for Groovy property access + inner class calls
        # Runs AFTER func_supplement so supplemental nodes get edges too
        console.print("  [dim]Supplementing Groovy CALLS edges...[/]")
        from .groovy_calls import supplement_groovy_calls
        groovy_stats = supplement_groovy_calls(repo_name)
        stats["groovy_calls"] = groovy_stats
        if groovy_stats.get("edges_added", 0) > 0:
            console.print(f"  [green]✓[/] +{groovy_stats['edges_added']} synthetic CALLS edges")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:

        # Unified single pass: flow graphs + templates (replaces lite_index + supplement + flow_builder)
        task = progress.add_task("Flows + templates (unified)", total=1)
        from .flow_builder import build_flow_index
        from src.main.code_tools import get_graph
        g = get_graph()

        # Clear old data
        g.query("MATCH (lt:LogTemplate) WHERE lt.repo_path CONTAINS $repo DETACH DELETE lt",
                params={"repo": repo_name})
        g.query("MATCH (f:Function) WHERE f.path CONTAINS $repo SET f.exec_flow = NULL",
                params={"repo": repo_name})

        flow_stats = build_flow_index(repo_name, graph=g)
        stats["flow_graphs"] = flow_stats
        progress.update(task, completed=1,
                       description=f"Flows: {flow_stats.get('flow_graphs_built', 0)} | Templates: {flow_stats.get('templates_created', 0)}")

        # Classification
        task = progress.add_task("Classification (topology)", total=1)
        from .classifier import classify_all
        class_stats = classify_all(repo_name, graph=g)
        stats["classification"] = class_stats
        progress.update(task, completed=1)

        # Function map
        task = progress.add_task("Function map (call topology)", total=1)
        from .func_map import build_func_map
        map_stats = build_func_map(repo_name, graph=g)
        stats["func_map"] = map_stats
        progress.update(task, completed=1,
                       description=f"Function map ({map_stats.get('functions', 0)} mapped)")

        # Pre-compute merged flows
        task = progress.add_task("Merged flows (bidirectional)", total=1)
        from .merge_builder import build_merged_flows
        merge_stats = build_merged_flows(repo_name, graph=g)
        stats["merged_flows"] = merge_stats
        progress.update(task, completed=1,
                       description=f"Merged flows: {merge_stats.get('merged_flows', 0)}")

        # Domain index (entry-point BFS + embedding)
        task = progress.add_task("Domain index (entry-point routing)", total=1)
        from .domains import build_domain_index
        domain_stats = build_domain_index(repo_name, graph=g)
        stats["domains"] = domain_stats
        progress.update(task, completed=1,
                       description=f"Domains: {domain_stats.get('domains', 0)}")

    # Save cache
    if current_hash:
        # Load trie data for cache
        result = g.query(
            'MATCH (lt:LogTemplate)-[:EMITTED_BY]->(f:Function) '
            'WHERE lt.repo_path CONTAINS $repo '
            'RETURN lt.static_fragments, f.name, id(f), lt.line_in_function',
            params={"repo": repo_name}
        )
        trie_data = [[r[0], r[1], r[2], r[3]] for r in result.result_set] if result.result_set else []
        save_cache(repo_name, current_hash, trie_data, stats)

    total_templates = flow_stats.get('templates_created', 0)
    console.print(f"\n[green]✓[/] Indexed [bold]{repo_name}[/]:")
    console.print(f"  Templates: {total_templates} | Flow graphs: {flow_stats.get('flow_graphs_built', 0)} | Classification: {sum(class_stats.values()) if class_stats else 0}")

    return stats


def _run_codegraph(repo_path: str) -> dict:
    """Run codegraphcontext index — streams its own progress bar to terminal."""
    try:
        result = subprocess.run(
            ["uv", "run", "codegraphcontext", "index", repo_path, "--force"],
            timeout=600,
            cwd=str(Path(__file__).parent.parent.parent.parent.parent),
        )
        return {"status": "success" if result.returncode == 0 else "error"}
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    except FileNotFoundError:
        return {"status": "not_installed"}


def check_and_reindex(repo_path: str, repo_name: str) -> bool:
    """Check if reindex needed. Returns True if reindexed."""
    current_hash = get_commit_hash(repo_path)
    if not current_hash or not is_stale(repo_name, current_hash):
        return False
    index_repo(repo_path, repo_name)
    return True
