"""Clusterer — split thread entries at anchor boundaries."""
from __future__ import annotations

from ..models import Cluster, extract_method_name
from ..store import load_func_map


def cluster_thread(thread_entries: list[dict], repo: str) -> list[Cluster]:
    """Split entries into clusters at anchor function boundaries.
    
    Preceding non-anchor lines attach to the NEXT anchor (lead-up context).
    """
    if not thread_entries:
        return []

    # Use cached func_map instead of live DB queries
    raw_map = load_func_map(repo)
    # Build name→node_class lookup
    _name_class: dict[str, str] = {}
    for v in raw_map.values():
        _name_class[v["name"]] = v.get("node_class", "internal")

    def _get_class(func: str) -> str:
        method = extract_method_name(func)
        return _name_class.get(method, "unknown")

    clusters: list[Cluster] = []
    current: Cluster | None = None
    pending: list[dict] = []

    for i, entry in enumerate(thread_entries):
        func = entry.get("function")
        if not func:
            if current:
                current.entries.append(entry)
            else:
                pending.append(entry)
            continue

        node_class = _get_class(func)
        if node_class in ("entry", "anchor"):
            if current:
                clusters.append(current)
            current = Cluster(
                anchor_func=extract_method_name(func),
                anchor_idx=i,
                entries=pending + [entry],
            )
            pending = []
        else:
            if current:
                current.entries.append(entry)
            else:
                pending.append(entry)

    if current:
        clusters.append(current)
    elif pending:
        fallback = next((e["function"] for e in pending if e.get("function")), None)
        if fallback:
            clusters.append(Cluster(
                anchor_func=extract_method_name(fallback),
                anchor_idx=0, entries=pending))

    return clusters
