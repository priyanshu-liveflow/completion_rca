"""Flow alignment orchestration — groups entries by thread and runs alignment."""
from __future__ import annotations

from ..models import WalkablePath, AlignmentResult
from .clusterer import cluster_thread
from .merger import merge_flow
from .comparator import align_thread
from src.main.shared.logging import get_logger

log = get_logger("align_orchestrate")


def align_error_threads(path: WalkablePath, repo_path: str) -> str:
    """Run flow alignment on error threads. Returns context string for decomposer."""
    # Group entries by thread
    thread_groups: dict[str, list[dict]] = {}
    for e in path.entries:
        tid = e.thread_id or "unknown"
        if tid not in thread_groups:
            thread_groups[tid] = []
        thread_groups[tid].append({
            "function": e.originated_from[0] if e.originated_from else None,
            "fid": e.originated_from_ids[0] if e.originated_from_ids else -1,
            "line": e.line_number,
            "level": e.level,
            "message": e.static_text,
            "thread_id": tid,
        })

    # Only align threads that contain errors
    error_threads = set()
    for idx in path.error_points:
        e = path.entries[idx]
        error_threads.add(e.thread_id or "unknown")

    if not error_threads:
        return ""

    repo_name = repo_path.split("/")[-1]
    alignments: list[AlignmentResult] = []

    for tid in error_threads:
        if tid in thread_groups:
            clusters = cluster_thread(thread_groups[tid], repo_path)
            merged_flows = {}
            for c in clusters:
                merged_flows[c.anchor_func] = merge_flow(c.anchor_func, repo_name, max_depth=3)
            r = align_thread(thread_groups[tid], clusters, merged_flows, repo=repo_name)
            if r.divergences:
                alignments.append(r)

    if not alignments:
        return ""

    log.info("flow_alignment", threads_with_divergences=len(alignments),
             total_divergences=sum(len(a.divergences) for a in alignments))

    lines = ["## Flow Alignment Divergences\n"]
    for a in alignments[:5]:
        lines.append(f"Thread {a.thread_id} (flow: {a.matched_flow}, coverage: {a.coverage:.0f}%):")
        for d in a.divergences[:8]:
            lines.append(f"  [{d['type']}] expected: {d['expected']}")
            if d.get('actual'):
                lines.append(f"             actual: {d['actual']}")
        lines.append("")

    return "\n".join(lines)
