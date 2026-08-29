"""Supplemental Groovy function indexer — catches methods tree-sitter misses.

Scans repo source files with regex, compares against graph, inserts missing
Function nodes with source. Runs after codegraphcontext indexing.
"""
from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path

from src.main.shared.logging import get_logger

log = get_logger("groovy_func_supplement")

# Match method definitions: modifiers + return type + name(
_DEF_RE = re.compile(
    r'^[ \t]*(?:(?:public|private|protected|static|final|synchronized|abstract)\s+)*'
    r'(?:def|void|boolean|int|long|String|Map|List|Set|Object|Boolean|Integer|Long|Double|Float|'
    r'[A-Z]\w*(?:<[^>]+>)?)\s+'
    r'([a-z]\w*)\s*\(',
    re.MULTILINE
)


def _extract_method_source(content: str, match_start: int) -> str:
    """Extract method body from opening { to matching }."""
    # Find first { after the match
    brace_start = content.find('{', match_start)
    if brace_start == -1:
        return ""
    
    depth = 0
    i = brace_start
    while i < len(content):
        if content[i] == '{':
            depth += 1
        elif content[i] == '}':
            depth -= 1
            if depth == 0:
                return content[match_start:i + 1]
        i += 1
    return content[match_start:min(match_start + 5000, len(content))]


def supplement_missing_functions(repo_path: str, repo_name: str, graph=None) -> dict:
    """Scan repo for method definitions not in graph, insert them.
    
    Returns stats dict.
    """
    if graph is None:
        from src.main.code_tools import get_graph
        graph = get_graph()

    repo_root = Path(repo_path)
    exclude_dirs = {'web-app', 'target', 'build', '.gradle', 'node_modules', 'test'}

    # Get existing functions from graph (by file + name)
    result = graph.query(
        "MATCH (f:Function) WHERE f.path CONTAINS $repo RETURN f.name, f.path",
        params={"repo": repo_name},
    )
    existing = defaultdict(set)
    for row in result.result_set:
        existing[row[1]].add(row[0])

    # Scan files
    missing_funcs = []  # (abs_path, name, source)

    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for f in files:
            if not (f.endswith('.groovy') or f.endswith('.java')):
                continue
            filepath = os.path.join(root, f)
            graph_names = existing.get(filepath, set())

            try:
                content = open(filepath).read()
            except Exception:
                continue

            for match in _DEF_RE.finditer(content):
                name = match.group(1)
                if name in graph_names:
                    continue
                # Extract source
                source = _extract_method_source(content, match.start())
                if len(source) < 20:
                    continue
                missing_funcs.append((filepath, name, source))
                graph_names.add(name)  # avoid duplicates within same file

    if not missing_funcs:
        log.info("no_missing_functions", repo=repo_name)
        return {"added": 0}

    # Insert into graph
    added = 0
    batch_size = 100
    for i in range(0, len(missing_funcs), batch_size):
        batch = missing_funcs[i:i + batch_size]
        for filepath, name, source in batch:
            try:
                # Find parent class node
                class_result = graph.query(
                    "MATCH (c:Class) WHERE c.path = $path RETURN id(c) LIMIT 1",
                    params={"path": filepath},
                )
                if class_result.result_set:
                    class_id = class_result.result_set[0][0]
                    graph.query(
                        "MATCH (c:Class) WHERE id(c) = $cid "
                        "CREATE (f:Function {name: $name, path: $path, source: $source, "
                        "node_class: 'internal', supplemental: true})"
                        "-[:DEFINED_IN]->(c)",
                        params={"cid": class_id, "name": name, "path": filepath, "source": source},
                    )
                else:
                    # No class node — create standalone function
                    graph.query(
                        "CREATE (f:Function {name: $name, path: $path, source: $source, "
                        "node_class: 'internal', supplemental: true})",
                        params={"name": name, "path": filepath, "source": source},
                    )
                added += 1
            except Exception as e:
                log.debug("insert_failed", name=name, error=str(e)[:60])

    log.info("supplement_functions_done", added=added, scanned=len(missing_funcs), repo=repo_name)
    return {"added": added, "scanned_missing": len(missing_funcs)}
