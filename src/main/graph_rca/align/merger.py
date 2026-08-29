"""Merger — build merged flow by inlining callees with branch-aware tree structure."""
from __future__ import annotations
import json
from pathlib import Path

from ..models import FlowNode, FlowEdge, FlowGraph, MergedFlow, LogStep, extract_method_name
from ..store import cache_root
from src.main.code_tools import get_graph as _get_graph

_CACHE_DIR = cache_root()
_memory_cache: dict[str, MergedFlow] = {}  # in-process cache across clusters


def _cache_path(repo: str, key: str) -> Path:
    safe = str(key).replace("/", "_").replace(":", "_").replace(".", "_")
    return _CACHE_DIR / repo / "merged" / f"{safe}.json"


def _serialize_steps(steps: list[LogStep]) -> list:
    out = []
    for s in steps:
        d = {"type": s.type}
        if s.type == "log":
            d.update({"func": s.func, "fid": s.fid, "line": s.line, "level": s.level, "text": s.text})
        elif s.type == "branch":
            d["paths"] = [_serialize_steps(p) for p in (s.paths or [])]
        elif s.type == "loop":
            d["body"] = _serialize_steps(s.body or [])
        out.append(d)
    return out


def _deserialize_steps(data: list) -> list[LogStep]:
    steps = []
    for d in data:
        s = LogStep(type=d["type"])
        if s.type == "log":
            s.func, s.fid, s.line, s.level, s.text = d.get("func",""), d.get("fid",-1), d.get("line",0), d.get("level",""), d.get("text","")
        elif s.type == "branch":
            s.paths = [_deserialize_steps(p) for p in d.get("paths", [])]
        elif s.type == "loop":
            s.body = _deserialize_steps(d.get("body", []))
        steps.append(s)
    return steps


def _load_cached(repo: str, func: str) -> MergedFlow | None:
    if func in _memory_cache:
        return _memory_cache[func]
    p = _cache_path(repo, func)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
        m = MergedFlow(entry_function=func)
        m.log_tree = _deserialize_steps(d.get("log_tree", []))
        m.log_sequence = [tuple(x) for x in d.get("log_sequence", [])]
        m.anchor_index = {int(k): v for k, v in d.get("anchor_index", {}).items()}
        _memory_cache[func] = m
        return m
    except Exception:
        return None


def _save_cached(repo: str, func: str, merged: MergedFlow):
    p = _cache_path(repo, func)
    p.parent.mkdir(parents=True, exist_ok=True)
    d = {
        "log_tree": _serialize_steps(merged.log_tree),
        "log_sequence": merged.log_sequence,
        "anchor_index": merged.anchor_index,
    }
    p.write_text(json.dumps(d))
    _memory_cache[func] = merged


def merge_flow(entry_func: str, repo: str, max_depth: int = 6) -> MergedFlow:
    """Build merged flow: tree-structured with branches, depth 6, fid-visited."""
    cached = _load_cached(repo, entry_func)
    if cached:
        return cached

    g = _get_graph()
    merged = MergedFlow(entry_function=entry_func)
    _counter = [0]
    _visited: set[int] = set()  # FalkorDB node ids — prevents infinite recursion
    _MAX_NODES = 500  # Hard cap to prevent explosion
    _flow_cache: dict[int | str, tuple] = {}  # cache DB queries

    def _get_flow(func_id: int, func_name: str):
        """Fetch exec_flow for a function. Returns (FlowGraph, name, fid) or (None, name, -1)."""
        cache_key = func_id if func_id > 0 else func_name
        if cache_key in _flow_cache:
            return _flow_cache[cache_key]

        result = None, func_name, -1
        if func_id > 0:
            r = g.query(
                "MATCH (f:Function) WHERE id(f) = $nid AND f.exec_flow IS NOT NULL "
                "RETURN f.exec_flow, f.name, id(f)", params={"nid": func_id})
            if r.result_set and r.result_set[0][0]:
                try:
                    result = FlowGraph.from_json(r.result_set[0][0]), r.result_set[0][1], r.result_set[0][2]
                except Exception:
                    pass
        if result[0] is None:
            short = extract_method_name(func_name)
            r = g.query(
                "MATCH (f:Function {name: $name}) WHERE f.path CONTAINS $repo "
                "AND f.exec_flow IS NOT NULL RETURN f.exec_flow, f.name, id(f) LIMIT 1",
                params={"name": short, "repo": repo})
            if r.result_set and r.result_set[0][0]:
                try:
                    result = FlowGraph.from_json(r.result_set[0][0]), r.result_set[0][1], r.result_set[0][2]
                except Exception:
                    pass
        _flow_cache[cache_key] = result
        return result

    def _build_adj(fg: FlowGraph) -> dict[int, list[tuple[int, str]]]:
        """Build adjacency list from flow graph edges: node_id → [(target_id, edge_type)]."""
        adj: dict[int, list[tuple[int, str]]] = {}
        for e in fg.edges:
            adj.setdefault(e.src, []).append((e.dst, e.edge_type))
        return adj

    def _node_map(fg: FlowGraph) -> dict[int, FlowNode]:
        return {n.id: n for n in fg.nodes}

    def _walk_tree(fg: FlowGraph, func_name: str, func_id: int, depth: int) -> list[LogStep]:
        """Walk a flow graph and produce a LogStep tree respecting branches."""
        if not fg or not fg.nodes:
            return []

        adj = _build_adj(fg)
        nodes = _node_map(fg)
        steps: list[LogStep] = []
        visited_nodes: set[int] = set()

        def _walk_from(node_id: int, target_steps: list[LogStep]):
            if node_id in visited_nodes:
                return
            visited_nodes.add(node_id)

            node = nodes.get(node_id)
            if not node:
                return

            if node.type == "log":
                target_steps.append(LogStep(
                    type="log", func=func_name, fid=func_id,
                    line=node.line, level=node.log_level, text=node.log_text,
                ))

            elif node.type == "call" and node.call_target:
                # Inline callee
                target_id = node.call_target_id if node.call_target_id > 0 else -1
                target_name = node.call_target
                callee_steps = _inline_callee(target_id, target_name, depth + 1)
                target_steps.extend(callee_steps)

            elif node.type == "branch":
                # Collect paths from this branch node
                outgoing = adj.get(node_id, [])
                branch_paths: list[list[LogStep]] = []
                continuation_targets: set[int] = set()

                for (target, etype) in outgoing:
                    if etype in ("branch_true", "branch_false", "exception", "fallthrough"):
                        path_steps: list[LogStep] = []
                        _walk_from(target, path_steps)
                        branch_paths.append(path_steps)
                    else:
                        # "next" edge after branch_end → continuation
                        continuation_targets.add(target)

                if branch_paths:
                    target_steps.append(LogStep(type="branch", paths=branch_paths))

                # Continue after branch convergence
                for ct in continuation_targets:
                    _walk_from(ct, target_steps)
                return  # Don't follow normal edges — we handled them

            elif node.type in ("return", "throw"):
                target_steps.append(LogStep(type="exit"))
                return  # Dead code after return/throw

            # Follow "next" edges
            outgoing = adj.get(node_id, [])
            for (target, etype) in outgoing:
                if etype == "next":
                    _walk_from(target, target_steps)

        # Start from entry node
        start = fg.entry_node if fg.entry_node in nodes else (fg.nodes[0].id if fg.nodes else -1)
        if start >= 0:
            _walk_from(start, steps)

        return steps

    def _inline_callee(func_id: int, func_name: str, depth: int) -> list[LogStep]:
        """Inline a callee function, respecting depth and visited."""
        if depth > max_depth:
            return []
        if _counter[0] > _MAX_NODES:
            return []
        if func_id > 0 and func_id in _visited:
            return []
        if func_id > 0:
            _visited.add(func_id)

        fg, resolved_name, resolved_id = _get_flow(func_id, func_name)
        if not fg:
            return []

        # Record anchor
        if resolved_id > 0:
            merged.anchor_index[resolved_id] = len(merged.nodes)

        # Build graph nodes (for visualization/debugging)
        id_map = {}
        for node in fg.nodes:
            new_id = _counter[0]
            _counter[0] += 1
            id_map[node.id] = new_id
            new_node = FlowNode(
                id=new_id, type=node.type, line=node.line,
                log_level=node.log_level, log_text=node.log_text,
                call_target=node.call_target, call_target_id=node.call_target_id,
                branch_type=node.branch_type, condition=node.condition,
                branch_depth=node.branch_depth, branch_path=f"{resolved_name}:{node.branch_depth}")
            merged.nodes.append(new_node)
        for edge in fg.edges:
            if edge.src in id_map and edge.dst in id_map:
                merged.edges.append(FlowEdge(src=id_map[edge.src], dst=id_map[edge.dst], edge_type=edge.edge_type))

        # Also build flat log_sequence for backward compat
        for node in fg.nodes:
            if node.type == "log":
                merged.log_sequence.append((resolved_name, node.line, node.log_level, node.log_text))

        # Build tree
        steps = _walk_tree(fg, resolved_name, resolved_id, depth)
        return steps

    # Entry point
    merged.log_tree = _inline_callee(-1, entry_func, 0)
    _save_cached(repo, entry_func, merged)
    return merged



