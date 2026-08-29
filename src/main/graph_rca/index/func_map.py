"""Function map — call graph topology cached as flat lookup for O(1) alignment."""
from __future__ import annotations
import json

from ..store import save_func_map as _save_func_map, load_func_map as _load_func_map_raw
from src.main.shared.logging import get_logger

log = get_logger("func_map")


def build_func_map(repo: str, graph=None) -> dict:
    """Build and cache func_map.json: fid → {name, class, callers, callees, node_class, has_flow}."""
    if graph is None:
        from src.main.code_tools import get_graph
        graph = get_graph()

    # All functions with metadata
    result = graph.query(
        "MATCH (f:Function) WHERE f.path CONTAINS $repo "
        "OPTIONAL MATCH (c:Class)-[:CONTAINS]->(f) "
        "RETURN id(f), f.name, COALESCE(c.name, ''), f.node_class, "
        "CASE WHEN f.exec_flow IS NOT NULL THEN true ELSE false END",
        params={"repo": repo}
    )

    func_map: dict[int, dict] = {}
    for row in (result.result_set or []):
        fid, name, cls, node_class, has_flow = row[0], row[1], row[2], row[3], row[4]
        func_map[fid] = {
            "name": name,
            "class": cls or "",
            "callers": [],
            "callees": [],
            "node_class": node_class or "internal",
            "has_flow": bool(has_flow),
        }

    # CALLS edges
    edges = graph.query(
        "MATCH (a:Function)-[:CALLS]->(b:Function) "
        "WHERE a.path CONTAINS $repo AND b.path CONTAINS $repo "
        "RETURN id(a), id(b)",
        params={"repo": repo}
    )
    for row in (edges.result_set or []):
        caller_fid, callee_fid = row[0], row[1]
        if caller_fid in func_map:
            func_map[caller_fid]["callees"].append(callee_fid)
        if callee_fid in func_map:
            func_map[callee_fid]["callers"].append(caller_fid)

    # Save
    out = {str(k): v for k, v in func_map.items()}
    _save_func_map(repo, out)

    log.info("func_map_built", functions=len(func_map),
             with_flow=sum(1 for v in func_map.values() if v["has_flow"]),
             entries=sum(1 for v in func_map.values() if v["node_class"] == "entry"))

    return {"functions": len(func_map), "with_flow": sum(1 for v in func_map.values() if v["has_flow"])}


# --- Runtime loader ---

_loaded: dict[str, dict[int, dict]] = {}


def get_func_map(repo: str) -> dict[int, dict]:
    """Load func_map from disk cache. Returns {fid: {...}}."""
    if repo in _loaded:
        return _loaded[repo]

    data = _load_func_map_raw(repo)
    if not data:
        return {}

    func_map = {int(k): v for k, v in data.items()}
    _loaded[repo] = func_map
    return func_map
