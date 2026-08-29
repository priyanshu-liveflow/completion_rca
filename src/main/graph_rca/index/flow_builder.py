"""Flow builder — orchestrates extraction + transformation + persistence + templates."""
from __future__ import annotations
import os

from .flow_extractor import extract_flow_graph
from .flow_transform import inject_calls, resolve_call_targets, filter_junk_calls
from .template_scanner import scan_templates, index_orphan_closures
from .semantic_index import SemanticIndex
from .supplement import _find_function_end
from ..models import extract_method_name
from src.main.shared.logging import get_logger

log = get_logger("flow_builder")


def build_flow_index(repo: str, graph=None, verbose: bool = False) -> dict:
    """Build flow graphs + log templates for all functions in a repo."""
    if graph is None:
        from src.main.code_tools import get_graph
        graph = get_graph()

    # --- Data loading ---
    result = graph.query(
        "MATCH (f:Function) WHERE f.path CONTAINS $repo "
        "AND f.source IS NOT NULL "
        "RETURN id(f), f.name, f.source, f.lang, f.start_line, f.end_line, f.path",
        params={"repo": repo},
    )
    if not result.result_set:
        return {"error": "No functions found"}

    calls_by_caller = _load_calls(graph, repo)
    name_counts, name_to_fid = _build_name_lookup(result.result_set)
    class_method_fid = _load_class_methods(graph, repo)

    # --- Per-function processing ---
    flow_count = 0
    template_count = 0
    effective_lang = "java"
    semantic_functions = []  # (fid, name, source) for semantic indexing

    for row in result.result_set:
        fid, fname, source, lang, start_line, end_line, fpath = row
        effective_lang = (lang or "java").lower()

        original_source = _bound_source(source, start_line, end_line, effective_lang)
        trimmed_source = _trim_source_for_flow(source, start_line, end_line, fpath, effective_lang)

        # Collect for semantic indexing
        semantic_functions.append((fid, fname, original_source))

        # Extract flow graph
        fg = extract_flow_graph(trimmed_source, fname, lang or "java")

        # Transform: inject calls, resolve targets, filter junk
        inject_calls(fg, fid, calls_by_caller)
        resolve_call_targets(fg, name_to_fid, class_method_fid)
        filter_junk_calls(fg, name_counts)

        # Persist flow graph
        if len(fg.nodes) >= 2:
            try:
                graph.query(
                    "MATCH (f:Function) WHERE id(f) = $fid SET f.exec_flow = $fg",
                    params={"fid": fid, "fg": fg.to_json()},
                )
                flow_count += 1
            except Exception:
                pass

        # Scan for log templates (independent of flow graph)
        template_count += scan_templates(original_source, fid, repo, effective_lang, graph)

        if verbose and flow_count % 200 == 0 and flow_count > 0:
            log.info("progress", count=flow_count)

    # Orphan closure pass
    orphan_templates = index_orphan_closures(repo, graph, effective_lang)
    template_count += orphan_templates

    log.info("flow_graphs_done", total=flow_count, templates=template_count,
             orphan_templates=orphan_templates)

    # --- Semantic index ---
    sem_idx = SemanticIndex()
    sem_idx.build(semantic_functions)
    sem_idx.save(repo)

    return {"flow_graphs_built": flow_count, "templates_created": template_count}


# --- Private helpers (source boundary logic) ---

def _load_calls(graph, repo: str) -> dict[int, dict[str, int]]:
    """Pre-fetch all CALLS edges for the repo."""
    calls_result = graph.query(
        "MATCH (f:Function)-[:CALLS]->(g:Function) WHERE f.path CONTAINS $repo "
        "RETURN id(f), id(g), g.name",
        params={"repo": repo},
    )
    calls_by_caller: dict[int, dict[str, int]] = {}
    for row in (calls_result.result_set or []):
        calls_by_caller.setdefault(row[0], {})[row[2]] = row[1]
    log.info("calls_prefetched", total=sum(len(v) for v in calls_by_caller.values()))
    return calls_by_caller


def _build_name_lookup(rows) -> tuple[dict, dict]:
    """Build name→[fids] counts and unambiguous name→fid mapping."""
    name_counts: dict[str, list[int]] = {}
    for row in rows:
        name_counts.setdefault(row[1], []).append(row[0])
    name_to_fid = {n: ids[0] for n, ids in name_counts.items() if len(ids) == 1}
    return name_counts, name_to_fid


def _load_class_methods(graph, repo: str) -> dict[str, int]:
    """Build class.method→fid for Grails-style service injection resolution."""
    result = graph.query(
        "MATCH (c:Class)-[:CONTAINS]->(f:Function) WHERE c.path CONTAINS $repo "
        "RETURN c.name, f.name, id(f)", params={"repo": repo})
    class_method_fid: dict[str, int] = {}
    if result.result_set:
        for cls, method, cfid in result.result_set:
            lc_cls = cls[0].lower() + cls[1:] if cls else ""
            class_method_fid[f"{lc_cls}.{method}"] = cfid
    return class_method_fid


def _bound_source(source: str, start_line, end_line, lang: str) -> str:
    """Get original source bounded for template extraction."""
    if start_line and end_line and end_line > start_line:
        return '\n'.join(source.split('\n')[:end_line - start_line + 1])
    lines = source.split('\n')
    end = _find_function_end(lines, 0, lang)
    return '\n'.join(lines[:end]) if end > 1 else source


def _trim_source_for_flow(source: str, start_line, end_line, fpath, lang: str) -> str:
    """Trim source to function boundaries for flow graph extraction."""
    if start_line and end_line and end_line > start_line:
        lines = source.split('\n')
        return '\n'.join(lines[:end_line - start_line + 1])

    if start_line and fpath and os.path.exists(fpath):
        try:
            with open(fpath) as f:
                file_lines = [l.rstrip('\n') for l in f.readlines()]
            end_idx = _find_function_end(file_lines, start_line - 1, lang)
            func_len = end_idx - (start_line - 1)
            stored_len = len(source.split('\n'))
            if func_len > 1 and func_len <= stored_len * 3 and func_len >= stored_len // 2:
                return '\n'.join(file_lines[start_line - 1:end_idx])
        except Exception:
            pass

    # Fallback: brace counting on stored source
    lines = source.split('\n')
    end = _find_function_end(lines, 0, lang)
    if end > 1:
        return '\n'.join(lines[:end + 1])
    if len(lines) > 2000:
        return '\n'.join(lines[:2000])
    return source
