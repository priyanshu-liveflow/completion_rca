"""Node classifier — topology-based function classification."""
from __future__ import annotations

from src.main.shared.logging import get_logger

log = get_logger("classifier")


def classify_node(in_degree: int, out_degree: int, has_logs: bool) -> str:
    """Classify function: entry | anchor | utility | leaf | internal."""
    if in_degree == 0:
        return "entry"
    if out_degree == 0:
        return "leaf"
    if in_degree >= 10:
        return "utility"
    if in_degree <= 3 and has_logs:
        return "anchor"
    return "internal"


def classify_all(repo: str, graph=None) -> dict[str, int]:
    """Compute and store classification for all functions."""
    if graph is None:
        from src.main.code_tools import get_graph
        graph = get_graph()

    in_deg = {r[0]: r[1] for r in (graph.query(
        "MATCH (c:Function)-[:CALLS]->(f:Function) WHERE f.path CONTAINS $repo "
        "RETURN id(f), count(DISTINCT c)", params={"repo": repo}
    ).result_set or [])}

    out_deg = {r[0]: r[1] for r in (graph.query(
        "MATCH (f:Function)-[:CALLS]->(c:Function) WHERE f.path CONTAINS $repo "
        "RETURN id(f), count(DISTINCT c)", params={"repo": repo}
    ).result_set or [])}

    has_logs = {r[0] for r in (graph.query(
        "MATCH (f:Function) WHERE f.path CONTAINS $repo "
        "AND f.exec_flow IS NOT NULL AND f.exec_flow CONTAINS '\"type\": \"log\"' "
        "RETURN id(f)", params={"repo": repo}
    ).result_set or [])}

    all_fids = [r[0] for r in (graph.query(
        "MATCH (f:Function) WHERE f.path CONTAINS $repo RETURN id(f)",
        params={"repo": repo}
    ).result_set or [])]

    for fid in all_fids:
        cls = classify_node(in_deg.get(fid, 0), out_deg.get(fid, 0), fid in has_logs)
        graph.query(
            "MATCH (f:Function) WHERE id(f) = $fid "
            "SET f.node_class = $cls, f.in_degree = $i, f.out_degree = $o",
            params={"fid": fid, "cls": cls, "i": in_deg.get(fid, 0), "o": out_deg.get(fid, 0)},
        )

    stats = graph.query(
        "MATCH (f:Function) WHERE f.path CONTAINS $repo AND f.node_class IS NOT NULL "
        "RETURN f.node_class, count(f)", params={"repo": repo}
    )
    counts = {r[0]: r[1] for r in (stats.result_set or [])}
    log.info("classified", total=len(all_fids), counts=counts)
    return counts
