"""Resolver — matches log entries to functions via trie + class fallback + neighbours."""
from __future__ import annotations

from ..models import LogEntry, BranchPoint
from ..config import DomainConfig
from .trie import FragmentTrie
from .class_resolver import extract_logger_class, find_by_class, is_framework_log
from src.main.code_tools import get_graph
from src.main.shared.logging import get_logger

log = get_logger("resolver")


def resolve_entries(
    entries: list[LogEntry], repo_path: str, config: DomainConfig = None
) -> tuple[list[LogEntry], list[BranchPoint]]:
    """Resolve log entries to functions. Trie (O(m)) → class → neighbour."""
    from concurrent.futures import ThreadPoolExecutor
    import time as _time

    g = get_graph()
    branches: list[BranchPoint] = []
    group_by_thread = config.log_format.group_by_thread if config else False
    language = config.language if config else "java"

    repo_name = repo_path.split("/")[-1]
    frag_trie = FragmentTrie.from_cache(repo_name) or FragmentTrie.from_graph(g, repo_name)

    # Pass 1: Parallel trie matching (no DB, no sequential deps)
    _t0 = _time.monotonic()
    unresolved_indices = []

    def _trie_match(idx_entry):
        idx, entry = idx_entry
        # Stack trace — extract inline (no DB needed for frame extraction)
        if entry.stack_trace and entry.stack_trace.frames:
            return idx, "stack_trace", None
        if len(entry.static_text) < 5:
            return idx, "skip", None
        candidates = frag_trie.find_and_verify(entry.static_text)
        if not candidates:
            return idx, "miss", None
        if len(candidates) == 1:
            return idx, "hit", candidates[0]
        return idx, "ambiguous", candidates

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(_trie_match, enumerate(entries)))

    trie_hits = 0
    for idx, status, data in results:
        entry = entries[idx]
        if status == "hit":
            fname, fid, line = data
            entry.originated_from = [fname]
            entry.originated_from_ids = [fid]
            entry.originated_line = line
            entry.originated_class = fname.rsplit('.', 1)[0] if '.' in fname else None
            entry.resolution_confidence = 0.85
            entry.resolution_tier = 2
            trie_hits += 1
        elif status in ("miss", "stack_trace", "skip", "ambiguous"):
            unresolved_indices.append((idx, status, data))

    log.debug("trie_pass_complete", total=len(entries), hits=trie_hits,
              unresolved=len(unresolved_indices), duration_s=round(_time.monotonic() - _t0, 2))

    # Pass 2: Sequential resolution for unresolved entries (stack traces, class fallback, disambiguation)
    prev_by_thread: dict[str | None, str | None] = {}

    for idx, status, data in unresolved_indices:
        entry = entries[idx]
        thread_key = entry.thread_id if group_by_thread else None

        if status == "stack_trace":
            app_frames = _extract_app_frames(entry.stack_trace.frames, g, repo_path, language)
            if app_frames:
                entry.originated_from = [app_frames[0]]
                entry.trace_path = app_frames
                entry.resolution_confidence = 0.95
                entry.resolution_tier = 1
                prev_by_thread[thread_key] = app_frames[0]
                continue

        if status == "miss" or status == "skip":
            logger_class = extract_logger_class(entry.raw_text, config)
            if logger_class:
                class_cands = find_by_class(g, logger_class, repo_path, entry.static_text)
                if class_cands:
                    entry.originated_from = [class_cands[0][0]]
                    entry.originated_from_ids = [class_cands[0][1]]
                    entry.originated_class = logger_class.split('.')[-1] if logger_class else None
                    entry.resolution_confidence = 0.60
                    entry.resolution_tier = 3
                    entry.is_inferred = True
                    prev_by_thread[thread_key] = class_cands[0][0]
                    continue
                else:
                    entry.is_framework = is_framework_log(logger_class, language)
                    continue
            entry.resolution_tier = 4
            entry.is_framework = is_framework_log(entry.static_text, language)
            continue

        if status == "ambiguous":
            candidates = data
            previous_func = prev_by_thread.get(thread_key)
            scored = _score(g, [(c[0], c[1]) for c in candidates], previous_func)
            if scored[0][2] > 0.5 and (len(scored) < 2 or scored[0][2] - scored[1][2] > 0.2):
                entry.originated_from = [scored[0][0]]
                entry.originated_from_ids = [scored[0][1]]
                entry.resolution_confidence = scored[0][2]
                entry.resolution_tier = 3
                prev_by_thread[thread_key] = scored[0][0]
            elif scored[0][2] > 0.3:
                entry.originated_from = [s[0] for s in scored[:3]]
                entry.originated_from_ids = [s[1] for s in scored[:3]]
                entry.resolution_confidence = scored[0][2]
                entry.resolution_tier = 3
                branches.append(BranchPoint(entry_index=idx, candidates=[s[0] for s in scored[:3]],
                                           scores=[s[2] for s in scored[:3]]))
                prev_by_thread[thread_key] = scored[0][0]
            else:
                entry.resolution_tier = 4

    # Second pass: neighbour inference
    _infer_neighbours(entries, g, repo_path, config, group_by_thread, language)
    return entries, branches


def _score(g, candidates, prev_func):
    if not prev_func:
        return [(c[0], c[1], 0.4) for c in candidates]
    from src.main.graph_rca.models import extract_method_name
    prev_short = extract_method_name(prev_func)
    scored = []
    for fname, fid in candidates:
        if fname == prev_func:
            scored.append((fname, fid, 0.9))
            continue
        target_short = extract_method_name(fname)
        try:
            r = g.query(
                'MATCH (a:Function {name: $f}), (b:Function {name: $t}) '
                'WITH shortestPath((a)-[:CALLS*1..6]->(b)) as p '
                'WHERE p IS NOT NULL RETURN length(p)',
                params={"f": prev_short, "t": target_short})
            hop = r.result_set[0][0] if r.result_set else 0
        except Exception:
            hop = 0
        scored.append((fname, fid, 0.4 + (0.5 / hop if hop > 0 else 0.0)))
    scored.sort(key=lambda x: x[2], reverse=True)
    return scored


def _infer_neighbours(entries, g, repo_path, config, group_by_thread, language):
    for idx, entry in enumerate(entries):
        if entry.resolution_tier != 4:
            continue
        thread_key = entry.thread_id if group_by_thread else None
        anchors = []
        for off in range(-3, 4):
            ni = idx + off
            if ni == idx or ni < 0 or ni >= len(entries):
                continue
            nb = entries[ni]
            if nb.resolution_tier > 3 or not nb.originated_from:
                continue
            if group_by_thread and nb.thread_id != thread_key:
                continue
            anchors.append(nb.originated_from[0])
        if not anchors:
            continue

        logger_class = extract_logger_class(entry.raw_text, config)
        if logger_class:
            cands = find_by_class(g, logger_class, repo_path, entry.static_text)
            if cands:
                entry.originated_from = cands
                entry.resolution_confidence = 0.55
                entry.resolution_tier = 3
                entry.is_inferred = True
            else:
                entry.is_framework = is_framework_log(logger_class, language)


def _extract_app_frames(frames, g, repo_path: str, language: str = "java") -> list[str]:
    """Extract key app frames: first 2 (crash + caller) + last 2 (entry region).
    
    Filters out framework frames using markers from language YAML config.
    """
    from ..index.flow_extractor import load_patterns

    patterns = load_patterns(language)
    fw_markers = patterns.framework_markers

    app_frames = []
    for frame in frames:
        qualified = f"{frame.class_name}.{frame.method}"
        cls = frame.class_name
        if fw_markers and any(cls.startswith(m) for m in fw_markers):
            continue
        if cls.startswith(("java.", "javax.", "sun.", "com.sun.", "jdk.", "groovy.", "org.codehaus.groovy")):
            continue
        app_frames.append(qualified)

    if not app_frames:
        f = frames[0]
        return [f"{f.class_name}.{f.method}"]

    # Keep first 2 + last 2 (deduped, preserving order)
    if len(app_frames) <= 4:
        return app_frames
    head = app_frames[:2]
    tail = app_frames[-2:]
    # Avoid duplicates if head and tail overlap
    result = head + [t for t in tail if t not in head]
    return result
