"""Comparator — match each entry against its own resolved function's flow, not the anchor's."""
from __future__ import annotations

from ..models import Cluster, MergedFlow, AlignmentResult, extract_method_name


# Cache of per-function log sequences: fid → [(func, line, level, frags)]
_func_logs: dict[str, dict[int, list[tuple]]] = {}


def _frags_match(frags: list[str], message: str) -> bool:
    """Check if template fragments match the message.
    
    First substantial fragment (>3 chars) MUST be present.
    Subsequent fragments are checked in order but we allow partial matches
    (message may be truncated).
    """
    if not frags:
        return False
    # Find first substantial fragment
    first = next((f.strip() for f in frags if len(f.strip()) > 3), None)
    if not first:
        return False
    idx = message.find(first)
    if idx == -1:
        return False
    # If multi-fragment, verify at least one more is present (stronger confirmation)
    if len(frags) > 1:
        pos = idx + len(first)
        for frag in frags[1:]:
            f = frag.strip()
            if len(f) <= 2:
                continue
            found = message.find(f, pos)
            if found >= 0:
                return True  # first + at least one more = confirmed
        # Only first matched, no subsequent — still accept (message may be truncated)
    return True


def _get_func_logs(repo: str) -> dict[int, list[tuple]]:
    """Load all function log sequences from trie cache, keyed by fid."""
    if repo in _func_logs:
        return _func_logs[repo]

    from ..store import load_trie_data

    logs_by_fid: dict[int, list[tuple]] = {}
    for row in load_trie_data(repo):
        frags, fname, fid = row[0], row[1], row[2]
        line = row[3] if len(row) > 3 else 0
        if fid not in logs_by_fid:
            logs_by_fid[fid] = []
        logs_by_fid[fid].append((fname, line, None, frags))

    _func_logs[repo] = logs_by_fid
    return logs_by_fid


def compare_cluster(cluster: Cluster, merged: MergedFlow, repo: str = "") -> tuple[int, list[tuple], list[dict]]:
    """Match each entry against its OWN function's log sequence.
    
    The anchor's merged flow is used for ordering context only.
    Each entry with an fid gets matched against that fid's logs.
    """
    entries = [e for e in cluster.entries if e.get("function")]
    if not entries:
        return 0, [], []

    func_logs = _get_func_logs(repo) if repo else {}

    aligned = []
    divergences = []
    matches = 0

    for entry in entries:
        func = entry.get("function", "")
        fid = entry.get("fid", -1)
        act_method = extract_method_name(func)
        act_msg = entry.get("message", "")
        is_error = entry.get("level", "") in ("error", "fatal")
        matched = False

        # Get THIS function's expected logs
        expected = func_logs.get(fid, []) if fid > 0 else []

        # Try matching against the function's own log sequence
        for ei, (exp_func, exp_line, exp_level, exp_frags) in enumerate(expected):
            if not exp_frags:
                aligned.append((cluster.anchor_idx, "match", f"{exp_func}[{ei}]"))
                matches += 1
                matched = True
                break
            # Check all fragments exist in the message in order
            if _frags_match(exp_frags, act_msg):
                aligned.append((cluster.anchor_idx, "match", f"{exp_func}[{ei}]"))
                matches += 1
                matched = True
                break

        # Fallback: check pre-built merged flow for this function
        if not matched and fid > 0:
            from ..store import load_merged_flow
            merged_data = load_merged_flow(repo, fid) if repo else None
            merged_seq = merged_data.get("sequence") if merged_data else None
            if merged_seq:
                for ei, entry_data in enumerate(merged_seq):
                    exp_text = entry_data[4] if len(entry_data) > 4 else ""
                    if exp_text and len(exp_text) > 3 and exp_text in act_msg:
                        aligned.append((cluster.anchor_idx, "match", f"merged[{ei}]"))
                        matches += 1
                        matched = True
                        break

        # Fallback 2: check anchor's merged flow (runtime, if pre-built not available)
        if not matched and merged and merged.log_sequence:
            for ei, (exp_func, exp_line, exp_level, exp_text) in enumerate(merged.log_sequence):
                if act_method != exp_func:
                    continue
                if not exp_text or exp_text in act_msg:
                    aligned.append((cluster.anchor_idx, "match", f"{cluster.anchor_func}[{ei}]"))
                    matches += 1
                    matched = True
                    break

        if not matched:
            div_type = "error_unmapped" if is_error else "unexpected_entry"
            divergences.append({
                "type": div_type,
                "position": cluster.anchor_idx,
                "expected": func,
                "actual": f"{func} [{entry.get('level','')}] {act_msg[:60]}",
                "is_error": is_error,
                "fid": fid,
            })

    return matches, aligned, divergences


def align_thread(thread_entries: list[dict], clusters: list[Cluster],
                 merged_flows: dict[str, MergedFlow], repo: str = "") -> AlignmentResult:
    """Align all clusters for a thread."""
    thread_id = thread_entries[0].get("thread_id", "unknown") if thread_entries else ""
    result = AlignmentResult(thread_id=thread_id)

    total_entries = 0
    total_matched = 0

    for cluster in clusters:
        merged = merged_flows.get(cluster.anchor_func)
        entry_count = sum(1 for e in cluster.entries if e.get("function"))
        total_entries += entry_count

        matches, aligned, divergences = compare_cluster(cluster, merged, repo)
        total_matched += matches
        result.aligned.extend(aligned)
        result.divergences.extend(divergences)

    result.coverage = (total_matched / total_entries * 100) if total_entries else 0.0
    result.matched_flow = f"{len(clusters)} clusters: {', '.join(c.anchor_func for c in clusters[:5])}"
    return result
