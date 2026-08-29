"""Flow graph transformations — CALLS injection, name resolution, junk filtering."""
from __future__ import annotations

from ..models import FlowNode, FlowEdge, FlowGraph, extract_method_name


def inject_calls(fg: FlowGraph, fid: int, calls_by_caller: dict[int, dict[str, int]]) -> None:
    """Inject resolved CALLS edges from pre-fetched call graph into flow graph nodes."""
    for callee_name, callee_id in calls_by_caller.get(fid, {}).items():
        existing = next(
            (n for n in fg.nodes if n.type == "call" and
             extract_method_name(n.call_target) == callee_name),
            None
        )
        if existing and existing.call_target_id <= 0:
            existing.call_target_id = callee_id
        elif not existing:
            new_id = len(fg.nodes)
            node = FlowNode(id=new_id, type="call", line=-1,
                          call_target=callee_name, call_target_id=callee_id)
            if fg.nodes:
                fg.edges.append(FlowEdge(src=fg.nodes[-1].id, dst=new_id))
            fg.nodes.append(node)


def resolve_call_targets(fg: FlowGraph, name_to_fid: dict[str, int],
                         class_method_fid: dict[str, int]) -> None:
    """Resolve unresolved call targets via name lookup and class.method injection convention."""
    for node in fg.nodes:
        if node.type == "call" and node.call_target_id <= 0 and node.call_target:
            short = extract_method_name(node.call_target)
            if short in name_to_fid:
                node.call_target_id = name_to_fid[short]
            elif node.call_target in class_method_fid:
                node.call_target_id = class_method_fid[node.call_target]


def filter_junk_calls(fg: FlowGraph, name_counts: dict[str, list[int]]) -> None:
    """Remove call nodes with short names or unknown targets, bridging edges around them."""
    remove_ids = set()
    for node in fg.nodes:
        if node.type == "call":
            short = extract_method_name(node.call_target) if node.call_target else ""
            if len(short) <= 3 or short not in name_counts:
                remove_ids.add(node.id)

    if not remove_ids:
        return

    # Build adjacency for bridging
    outgoing: dict[int, list[int]] = {}
    for e in fg.edges:
        outgoing.setdefault(e.src, []).append(e.dst)

    def _find_kept_successors(node_id: int) -> list[int]:
        """Follow outgoing edges through removed nodes until reaching kept ones."""
        result = []
        visited = set()
        queue = list(outgoing.get(node_id, []))
        while queue:
            nxt = queue.pop(0)
            if nxt in visited:
                continue
            visited.add(nxt)
            if nxt not in remove_ids:
                result.append(nxt)
            else:
                queue.extend(outgoing.get(nxt, []))
        return result

    new_edges = []
    seen_edges = set()
    for e in fg.edges:
        if e.src not in remove_ids and e.dst not in remove_ids:
            new_edges.append(e)
            seen_edges.add((e.src, e.dst))

    # Bridge from kept nodes through removed chains
    kept_ids = set(n.id for n in fg.nodes) - remove_ids
    for kid in kept_ids:
        for dst in outgoing.get(kid, []):
            if dst in remove_ids:
                for kept_dst in _find_kept_successors(dst):
                    if (kid, kept_dst) not in seen_edges:
                        new_edges.append(FlowEdge(src=kid, dst=kept_dst, edge_type="next"))
                        seen_edges.add((kid, kept_dst))

    fg.nodes = [n for n in fg.nodes if n.id not in remove_ids]
    fg.edges = new_edges

    # Update entry_node if it was removed
    if fg.entry_node in remove_ids or fg.entry_node is None:
        fg.entry_node = fg.nodes[0].id if fg.nodes else 0
