"""Pure graph query functions — no MCP, no agent logic, just data access.

All functions accept optional `fid` (int) as primary identifier.
When fid is provided, it's used directly (no ambiguity).
When only name is provided, falls back to name-based lookup.
All responses include fid alongside function names.
"""

from __future__ import annotations

import json
import re

from .graph_conn import get_graph


def _repo_filter(repo: str) -> str:
    """Wrap `repo` in slashes so `f.path CONTAINS` matches a directory boundary.

    `repo` is documented as the last path segment of the checkout, but a bare
    `CONTAINS` makes it a substring test: index both `app` and `myapp` and a
    query scoped to `app` silently draws nodes out of `myapp`, mixing two
    repos' tests into one selection. Indexed paths are absolute, so the repo
    segment always sits between two separators and `/repo/` is exact.

    Applied to the queries on the AgentRadar selection path only; the rest of
    this inherited module is left as-is.
    """
    trimmed = repo.strip("/")
    return f"/{trimmed}/" if trimmed else repo


def _short_name(name: str) -> str:
    """Strip package/class prefix — graph stores short names."""
    parts = re.split(r'[.::\\\/]+', name)
    return parts[-1] if parts else name


def _class_hint(raw_name: str) -> str | None:
    """Extract class name from qualified name for disambiguation."""
    parts = re.split(r'[.::\\\/]+', raw_name)
    return parts[-2] if len(parts) >= 2 else None


def _resolve_function(g, repo: str, function_name: str | None = None, fid: int | None = None):
    """Resolve a function node. fid takes priority. Returns list of (source, path, id) tuples."""
    if fid is not None:
        result = g.query(
            'MATCH (f:Function) WHERE id(f) = $fid RETURN f.source, f.path, id(f), f.name',
            params={"fid": fid}
        )
        return [(r[0], r[1], r[2], r[3]) for r in result.result_set] if result.result_set else []

    fname = _short_name(function_name or "")
    hint = _class_hint(function_name or "")

    if hint:
        result = g.query(
            'MATCH (f:Function) WHERE f.name = $name AND f.path CONTAINS $repo AND f.path CONTAINS $hint RETURN f.source, f.path, id(f), f.name',
            params={"name": fname, "repo": _repo_filter(repo), "hint": hint}
        )
        if result.result_set:
            return [(r[0], r[1], r[2], r[3]) for r in result.result_set]

    result = g.query(
        'MATCH (f:Function) WHERE f.name = $name AND f.path CONTAINS $repo RETURN f.source, f.path, id(f), f.name',
        params={"name": fname, "repo": _repo_filter(repo)}
    )
    return [(r[0], r[1], r[2], r[3]) for r in result.result_set] if result.result_set else []


def read_source(function_name: str, repo: str, max_chars: int = 1000, offset: int = 0, fid: int | None = None) -> str:
    """Read function source code. fid takes priority over name."""
    g = get_graph()
    matches = _resolve_function(g, repo, function_name, fid)

    if not matches:
        return f"Function '{function_name}' not found in code graph"

    header = ""
    if len(matches) > 1 and offset == 0 and fid is None:
        files = [f"  - {m[1]} (fid={m[2]})" for m in matches]
        header = f"Multiple matches for '{_short_name(function_name)}':\n" + "\n".join(files) + "\n\nShowing first match:\n"

    src = matches[0][0] or "No source available"
    path = matches[0][1]
    node_fid = matches[0][2]
    total = len(src)
    chunk = src[offset:offset + max_chars]
    file_info = f"File: {path} | fid={node_fid} | Total: {total} chars"
    if offset > 0 or offset + max_chars < total:
        file_info += f" | Showing: {offset}-{min(offset + max_chars, total)}"
    return f"{header}{file_info}\n\n{chunk}"


def get_callers(function_name: str, repo: str, limit: int = 10, fid: int | None = None) -> list[dict]:
    """Get functions that call this function. Returns [{name, fid, path, class_name}, ...]."""
    g = get_graph()

    if fid is not None:
        result = g.query(
            'MATCH (caller:Function)-[:CALLS]->(f:Function) WHERE id(f) = $fid AND caller.path CONTAINS $repo OPTIONAL MATCH (k:Class)-[:CONTAINS]->(caller) RETURN DISTINCT caller.name, id(caller), caller.path, k.name LIMIT $lim',
            params={"fid": fid, "repo": _repo_filter(repo), "lim": limit}
        )
    else:
        fname = _short_name(function_name)
        result = g.query(
            'MATCH (caller:Function)-[:CALLS]->(f:Function {name: $name}) WHERE caller.path CONTAINS $repo OPTIONAL MATCH (k:Class)-[:CONTAINS]->(caller) RETURN DISTINCT caller.name, id(caller), caller.path, k.name LIMIT $lim',
            params={"name": fname, "repo": _repo_filter(repo), "lim": limit}
        )

    if result.result_set:
        return [{"name": r[0], "fid": r[1], "path": r[2], "class_name": r[3]} for r in result.result_set]

    # Fallback: grep for name references
    fname = _short_name(function_name) if function_name else ""
    if fname:
        refs = _grep_source_for_refs(fname, repo, g, limit)
        return [{"name": n, "fid": None} for n in refs]
    return []


def get_import_edges(repo: str, limit: int = 2000) -> list[dict]:
    """Every IMPORTS edge in the repo. Returns [{file_path, imported}, ...].

    Edges run File -> Module and the Module nodes are leaves, so a transitive
    walk has to rejoin names to files in code. There were 183 edges for the
    demo repo, so one fetch beats a query per hop.
    """
    g = get_graph()
    result = g.query(
        'MATCH (f:File)-[:IMPORTS]->(m:Module) WHERE f.path CONTAINS $repo RETURN f.path, m.name LIMIT $lim',
        params={"repo": _repo_filter(repo), "lim": limit}
    )
    return [{"file_path": r[0], "imported": r[1]} for r in result.result_set] if result.result_set else []


def get_functions_in_file(file_path: str, repo: str, limit: int = 500) -> list[dict]:
    """Function nodes in one file. Returns [{name, fid, path, class_name}, ...].

    Method names are stored bare, with ownership on a separate Class CONTAINS
    edge, so `class_name` is what makes a runnable pytest node id possible.
    """
    g = get_graph()
    result = g.query(
        'MATCH (f:Function) WHERE f.path CONTAINS $path AND f.path CONTAINS $repo '
        'OPTIONAL MATCH (c:Class)-[:CONTAINS]->(f) '
        'RETURN f.name, id(f), f.path, c.name LIMIT $lim',
        params={"path": file_path, "repo": _repo_filter(repo), "lim": limit}
    )
    return [{"name": r[0], "fid": r[1], "path": r[2], "class_name": r[3]} for r in result.result_set] if result.result_set else []


def get_callees(function_name: str, repo: str, limit: int = 15, fid: int | None = None) -> list[dict]:
    """Get functions called by this function. Returns [{name, fid}, ...]."""
    g = get_graph()

    if fid is not None:
        result = g.query(
            'MATCH (f:Function)-[:CALLS]->(callee:Function) WHERE id(f) = $fid AND callee.path CONTAINS $repo RETURN DISTINCT callee.name, id(callee) LIMIT $lim',
            params={"fid": fid, "repo": repo, "lim": limit}
        )
    else:
        fname = _short_name(function_name)
        result = g.query(
            'MATCH (f:Function {name: $name})-[:CALLS]->(callee:Function) WHERE f.path CONTAINS $repo RETURN DISTINCT callee.name, id(callee) LIMIT $lim',
            params={"name": fname, "repo": repo, "lim": limit}
        )

    return [{"name": r[0], "fid": r[1]} for r in result.result_set] if result.result_set else []


def get_class_info(class_name: str, repo: str) -> dict:
    """Get class details: methods with fids, injected dependencies, source."""
    g = get_graph()
    cname = _short_name(class_name)
    class_src = g.query(
        'MATCH (c:Class {name: $name}) WHERE c.path CONTAINS $repo RETURN c.source, c.path',
        params={"name": cname, "repo": repo}
    )
    methods = g.query(
        'MATCH (c:Class {name: $name})-[:CONTAINS]->(f:Function) WHERE c.path CONTAINS $repo RETURN f.name, id(f)',
        params={"name": cname, "repo": repo}
    )
    injects = g.query(
        'MATCH (c:Class {name: $name})-[:INJECTS]->(d:Class) WHERE c.path CONTAINS $repo RETURN d.name',
        params={"name": cname, "repo": repo}
    )
    source = class_src.result_set[0][0] if class_src.result_set else None
    path = class_src.result_set[0][1] if class_src.result_set else None
    out = {
        "class": cname,
        "path": path,
        "methods": [{"name": r[0], "fid": r[1]} for r in methods.result_set] if methods.result_set else [],
        "injects": [r[0] for r in injects.result_set] if injects.result_set else [],
    }
    if source:
        out["source"] = source[:3000]
    return out


def get_inheritance(class_name: str, repo: str) -> dict:
    """Get parent and child classes."""
    g = get_graph()
    cname = _short_name(class_name)
    parents = g.query(
        'MATCH (c:Class {name: $name})-[:INHERITS]->(p) WHERE c.path CONTAINS $repo RETURN p.name',
        params={"name": cname, "repo": repo}
    )
    children = g.query(
        'MATCH (child:Class)-[:INHERITS]->(c:Class {name: $name}) WHERE child.path CONTAINS $repo RETURN child.name',
        params={"name": cname, "repo": repo}
    )
    return {
        "class": cname,
        "parents": [r[0] for r in parents.result_set] if parents.result_set else [],
        "children": [r[0] for r in children.result_set] if children.result_set else [],
    }


def get_db_tables(function_name: str, repo: str, fid: int | None = None) -> dict:
    """Get database tables a function reads from or writes to."""
    g = get_graph()

    if fid is not None:
        reads = g.query(
            'MATCH (f:Function)-[:READS]->(t:DbTable) WHERE id(f) = $fid RETURN t.name',
            params={"fid": fid}
        )
        writes = g.query(
            'MATCH (f:Function)-[:WRITES]->(t:DbTable) WHERE id(f) = $fid RETURN t.name',
            params={"fid": fid}
        )
    else:
        fname = _short_name(function_name)
        reads = g.query(
            'MATCH (f:Function {name: $name})-[:READS]->(t:DbTable) WHERE f.path CONTAINS $repo RETURN t.name',
            params={"name": fname, "repo": repo}
        )
        writes = g.query(
            'MATCH (f:Function {name: $name})-[:WRITES]->(t:DbTable) WHERE f.path CONTAINS $repo RETURN t.name',
            params={"name": fname, "repo": repo}
        )
    return {
        "function": function_name or f"fid:{fid}",
        "reads": [r[0] for r in reads.result_set] if reads.result_set else [],
        "writes": [r[0] for r in writes.result_set] if writes.result_set else [],
    }


def find_by_pattern(pattern: str, repo: str, limit: int = 15) -> list[dict]:
    """Search functions by name substring OR source code. Returns [{name, fid}, ...].

    Both searches always run and each is given the full ``limit``; the cap is
    applied to the deduplicated union afterwards. Running the source search
    only when the name search came up short meant a repo with ``limit``
    functions merely *named* after the symbol hid every site that actually
    *imports* it -- and for a dependency break the import sites are the whole
    point. Name matches still come first: they are the stronger signal.
    """
    g = get_graph()
    short = _short_name(pattern)
    seen: set[int] = set()
    out: list[dict] = []

    def collect(result) -> None:
        if not result.result_set:
            return
        for row in result.result_set:
            fid = row[1]
            if fid in seen:
                continue
            seen.add(fid)
            out.append({"name": row[0], "fid": fid})

    for field, needle in (("f.name", short), ("f.source", pattern)):
        collect(
            g.query(
                f"MATCH (f:Function) WHERE {field} CONTAINS $pattern AND f.path CONTAINS $repo "
                "RETURN DISTINCT f.name, id(f) LIMIT $lim",
                params={"pattern": needle, "repo": _repo_filter(repo), "lim": limit},
            )
        )
    return out[:limit]


def get_call_chain(from_function: str, to_function: str, repo: str, max_hops: int = 4) -> list[dict] | None:
    """Get shortest call chain. Returns [{name, fid}, ...] or None."""
    g = get_graph()
    from_f = _short_name(from_function)
    to_f = _short_name(to_function)
    max_hops = min(max_hops, 6)
    try:
        result = g.query(
            f'MATCH (a:Function {{name: $from_f}}), (b:Function {{name: $to_f}}) '
            f'WHERE a.path CONTAINS $repo AND b.path CONTAINS $repo '
            f'WITH shortestPath((a)-[:CALLS*1..{max_hops}]->(b)) as p '
            f'WHERE p IS NOT NULL RETURN [n IN nodes(p) | [n.name, id(n)]]',
            params={"from_f": from_f, "to_f": to_f, "repo": repo}
        )
        if result.result_set:
            return [{"name": n[0], "fid": n[1]} for n in result.result_set[0][0]]
    except Exception:
        pass
    return None


def get_log_templates(function_name: str, repo: str, fid: int | None = None) -> list[dict]:
    """Get log templates emitted by a function."""
    g = get_graph()

    if fid is not None:
        result = g.query(
            'MATCH (lt:LogTemplate)-[:EMITTED_BY]->(f:Function) WHERE id(f) = $fid RETURN lt.static_text, lt.log_level, lt.line_in_function',
            params={"fid": fid}
        )
    else:
        fname = _short_name(function_name)
        result = g.query(
            'MATCH (lt:LogTemplate)-[:EMITTED_BY]->(f:Function {name: $name}) WHERE lt.repo_path CONTAINS $repo RETURN lt.static_text, lt.log_level, lt.line_in_function',
            params={"name": fname, "repo": repo}
        )
    return [
        {"text": r[0], "level": r[1], "line": r[2]}
        for r in result.result_set
    ] if result.result_set else []


def _grep_source_for_refs(fname: str, repo: str, g=None, limit: int = 10) -> list[str]:
    """Grep all function sources for references to fname."""
    if g is None:
        g = get_graph()
    result = g.query(
        'MATCH (f:Function) WHERE f.source CONTAINS $fname AND f.name <> $fname AND f.path CONTAINS $repo RETURN DISTINCT f.name LIMIT $lim',
        params={"fname": fname, "repo": repo, "lim": limit}
    )
    return [r[0] for r in result.result_set] if result.result_set else []
