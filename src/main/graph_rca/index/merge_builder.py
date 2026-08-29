"""Pre-compute bidirectional merged flows at index time — no DB queries at runtime."""
from __future__ import annotations
import json
from pathlib import Path

from ..models import FlowGraph, FlowNode, extract_method_name
from ..store import cache_root, load_func_map as _load_func_map, merged_dir
from src.main.shared.logging import get_logger

log = get_logger("merge_builder")

_CACHE_DIR = cache_root()


def build_merged_flows(repo: str, graph=None) -> dict:
    """Pre-compute merged flows for all functions with logs. Pure in-memory, one DB read."""
    if graph is None:
        from src.main.code_tools import get_graph
        graph = get_graph()

    # 1. Load all exec_flows in one batch
    result = graph.query(
        "MATCH (f:Function) WHERE f.path CONTAINS $repo AND f.exec_flow IS NOT NULL "
        "RETURN id(f), f.name, f.exec_flow",
        params={"repo": repo},
    )
    if not result.result_set:
        return {"error": "No flows found"}

    flows: dict[int, tuple[str, FlowGraph]] = {}  # fid → (name, FlowGraph)
    for row in result.result_set:
        fid, name, flow_json = row
        try:
            fg = FlowGraph.from_json(flow_json)
            flows[fid] = (name, fg)
        except Exception:
            pass

    log.info("flows_loaded", count=len(flows))

    # 2. Load func_map for caller/callee topology
    func_map = _load_func_map(repo)

    # 3. Build merged flows for functions that have log nodes
    out_dir = merged_dir(repo)

    merged_count = 0
    for fid, (name, fg) in flows.items():
        logs_in_func = [n for n in fg.nodes if n.type == "log"]
        if not logs_in_func:
            continue

        # Build merged log sequence: callers (up) + self + callees (down)
        sequence = _build_sequence(fid, name, fg, flows, func_map, max_down=4, max_up=3)
        if not sequence:
            continue

        # Write to disk
        data = {"fid": fid, "name": name, "sequence": sequence}
        (out_dir / f"{fid}.json").write_text(json.dumps(data))
        merged_count += 1

    log.info("merged_flows_built", count=merged_count)
    return {"merged_flows": merged_count}


def _build_sequence(
    fid: int, name: str, fg: FlowGraph,
    all_flows: dict[int, tuple[str, FlowGraph]],
    func_map: dict,
    max_down: int = 4, max_up: int = 3,
) -> list[list]:
    """Build merged log sequence: [caller_logs..., self_logs..., callee_logs...].
    
    Each entry: [func_name, fid, line, level, text]
    """
    visited: set[int] = set()
    visited.add(fid)

    # Self logs
    self_logs = _extract_logs_with_callees(fid, name, fg, all_flows, func_map, visited, max_down)

    # Caller logs (walk up)
    caller_logs: list[list] = []
    current_fid = fid
    for _ in range(max_up):
        entry = func_map.get(str(current_fid))
        if not entry or not entry.get("callers"):
            break
        caller_fid = entry["callers"][0]
        if caller_fid in visited:
            break
        visited.add(caller_fid)

        caller_data = all_flows.get(caller_fid)
        if caller_data:
            caller_name, caller_fg = caller_data
            caller_own_logs = [[caller_name, caller_fid, n.line, n.log_level or "", n.log_text or ""]
                               for n in caller_fg.nodes if n.type == "log"]
            caller_logs = caller_own_logs + caller_logs
        current_fid = caller_fid

    return caller_logs + self_logs


def _extract_logs_with_callees(
    fid: int, name: str, fg: FlowGraph,
    all_flows: dict[int, tuple[str, FlowGraph]],
    func_map: dict,
    visited: set[int],
    max_depth: int,
    depth: int = 0,
) -> list[list]:
    """Extract logs from a function, inlining callee logs at call sites."""
    if depth > max_depth:
        return []

    result: list[list] = []
    for node in fg.nodes:
        if node.type == "log":
            result.append([name, fid, node.line, node.log_level or "", node.log_text or ""])
        elif node.type == "call" and node.call_target_id > 0 and node.call_target_id not in visited:
            callee_data = all_flows.get(node.call_target_id)
            if callee_data:
                callee_name, callee_fg = callee_data
                callee_logs = [n for n in callee_fg.nodes if n.type == "log"]
                if callee_logs:
                    visited.add(node.call_target_id)
                    result.extend(_extract_logs_with_callees(
                        node.call_target_id, callee_name, callee_fg,
                        all_flows, func_map, visited, max_depth, depth + 1
                    ))
    return result


def load_merged(repo: str, fid: int) -> list[list] | None:
    """Load pre-built merged flow for a function. Returns sequence or None."""
    from ..store import load_merged_flow
    data = load_merged_flow(repo, fid)
    if not data:
        return None
    return data.get("sequence")
