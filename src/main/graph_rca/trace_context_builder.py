"""Trace Context Builder — pre-assembles per-agent context with function validation.

Resolves starting nodes to FIDs, loads source/flow/merged context upfront,
scopes log entries to relevant clusters, and flags unresolvable functions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .store import load_func_map, load_trie_data, load_merged_flow
from .models import FlowGraph, WalkablePath, extract_method_name
from .decompose import AgentAssignment
from src.main.code_tools import get_graph
from src.main.shared.logging import get_logger

log = get_logger("trace_context")


@dataclass
class FunctionValidation:
    """Result of validating a function name against the code graph."""
    name: str
    fid: int  # -1 if not found
    found: bool
    source: str  # empty if not found
    strategy: str  # how it was resolved: exact, short_name, class_hint, pattern
    ambiguous: bool  # multiple matches
    candidates: list[str] = field(default_factory=list)  # if ambiguous, the options


@dataclass
class AgentContext:
    """Pre-assembled context for a single trace agent."""
    assignment: AgentAssignment
    validation: FunctionValidation
    source: str  # pre-loaded source (empty if NOT_IN_GRAPH)
    flow_graph: str  # text rendering of exec_flow
    merged_flow: str  # text rendering of merged callers/callees sequence
    callers: list[str]
    callees: list[str]
    cluster_entries: list[str]  # scoped log entries for this agent's cluster
    unmapped_entries: list[str]  # entries in cluster that couldn't resolve
    warnings: list[str]  # NOT_IN_GRAPH, ambiguous, etc.


# --- Function Validation Harness ---

class FunctionValidator:
    """Resolves function names to FIDs using multiple fallback strategies."""

    def __init__(self, repo: str):
        self.repo = repo
        self._func_map = load_func_map(repo)
        # Build lookup indexes
        self._by_name: dict[str, list[str]] = {}  # name → [fid_str, ...]
        self._by_class_method: dict[str, str] = {}  # "Class.method" → fid_str
        for fid_str, data in self._func_map.items():
            self._by_name.setdefault(data["name"], []).append(fid_str)
            if data.get("class"):
                key = f"{data['class']}.{data['name']}"
                self._by_class_method[key] = fid_str

    def validate(self, raw_name: str) -> FunctionValidation:
        """Resolve raw function name to FID with fallback strategies."""
        # Strategy 1: exact match on short name with class hint
        short = _extract_short_name(raw_name)
        class_hint = _extract_class_hint(raw_name)

        if class_hint:
            # Try Class.method exact match
            key = f"{class_hint}.{short}"
            if key in self._by_class_method:
                fid_str = self._by_class_method[key]
                return self._success(raw_name, fid_str, "class_hint")

        # Strategy 2: unambiguous short name match
        if short in self._by_name:
            matches = self._by_name[short]
            if len(matches) == 1:
                return self._success(raw_name, matches[0], "short_name")
            # Ambiguous — try to disambiguate with class hint
            if class_hint:
                for fid_str in matches:
                    data = self._func_map[fid_str]
                    if data.get("class", "").lower() == class_hint.lower():
                        return self._success(raw_name, fid_str, "class_disambig")
                    # Also try partial match on class name
                    if class_hint.lower() in data.get("class", "").lower():
                        return self._success(raw_name, fid_str, "class_partial")
            # Still ambiguous
            candidates = [f"{self._func_map[f]['class']}.{self._func_map[f]['name']}" for f in matches[:5]]
            return FunctionValidation(
                name=raw_name, fid=int(matches[0]), found=True,
                source="", strategy="ambiguous", ambiguous=True, candidates=candidates,
            )

        # Strategy 3: pattern match (handles inner classes, closures)
        # e.g. "FlatViewJobcontrolController$_closure5_closure80.doCall" → find functions in that class
        if "$" in raw_name or "_closure" in raw_name:
            outer_class = raw_name.split("$")[0].split(".")[-1] if "$" in raw_name else ""
            if outer_class:
                # Try exact short name in that class
                for fid_str, data in self._func_map.items():
                    if data.get("class") == outer_class and data["name"] == short:
                        return self._success(raw_name, fid_str, "closure_class")
                # Try: the path_slice often has the real function name — look for any function
                # in this class that has a flow graph (likely the closure action)
                class_fids = [fid_str for fid_str, data in self._func_map.items()
                              if data.get("class") == outer_class and data.get("has_flow")]
                if class_fids:
                    # Return as ambiguous with class context
                    candidates = [f"{self._func_map[f]['class']}.{self._func_map[f]['name']}" for f in class_fids[:5]]
                    return FunctionValidation(
                        name=raw_name, fid=int(class_fids[0]), found=True,
                        source="", strategy="closure_class_fuzzy", ambiguous=True,
                        candidates=candidates,
                    )

        # Strategy 4: not in graph
        return FunctionValidation(
            name=raw_name, fid=-1, found=False,
            source="", strategy="not_found", ambiguous=False,
        )

    def _success(self, raw_name: str, fid_str: str, strategy: str) -> FunctionValidation:
        data = self._func_map[fid_str]
        return FunctionValidation(
            name=raw_name, fid=int(fid_str), found=True,
            source="", strategy=strategy, ambiguous=False,
        )

    def get_source(self, fid: int) -> str:
        """Get function source from graph by FID."""
        g = get_graph()
        r = g.query("MATCH (f:Function) WHERE id(f) = $fid RETURN f.source", params={"fid": fid})
        return r.result_set[0][0] if r.result_set and r.result_set[0][0] else ""

    def get_flow_graph(self, fid: int) -> str:
        """Get exec_flow as text representation."""
        g = get_graph()
        r = g.query("MATCH (f:Function) WHERE id(f) = $fid RETURN f.exec_flow", params={"fid": fid})
        if not r.result_set or not r.result_set[0][0]:
            return ""
        try:
            fg = FlowGraph.from_json(r.result_set[0][0])
            return _render_flow_graph(fg)
        except Exception:
            return ""

    def get_callers_callees(self, fid: int) -> tuple[list[str], list[str]]:
        """Get callers and callees from func_map."""
        fid_str = str(fid)
        data = self._func_map.get(fid_str, {})
        callers = []
        for c_fid in data.get("callers", []):
            c_data = self._func_map.get(str(c_fid), {})
            if c_data:
                callers.append(f"{c_data.get('class', '')}.{c_data['name']}" if c_data.get("class") else c_data["name"])
        callees = []
        for c_fid in data.get("callees", []):
            c_data = self._func_map.get(str(c_fid), {})
            if c_data:
                callees.append(f"{c_data.get('class', '')}.{c_data['name']}" if c_data.get("class") else c_data["name"])
        return callers, callees


# --- Context Assembly ---

def build_agent_contexts(
    assignments: list[AgentAssignment],
    path: WalkablePath,
    repo: str,
) -> list[AgentContext]:
    """Build pre-loaded context for each trace agent. Deduplicates agents resolving to same FID."""
    validator = FunctionValidator(repo)
    contexts = []
    seen_fids: dict[int, AgentContext] = {}  # fid → first context that claimed it

    for assignment in assignments:
        validation = validator.validate(assignment.starting_node)
        warnings: list[str] = []

        # If validation failed or is ambiguous, try path_slice for a better match
        if (not validation.found or validation.ambiguous) and assignment.path_slice:
            for alt_name in assignment.path_slice:
                if alt_name == assignment.starting_node:
                    continue
                alt = validator.validate(alt_name)
                if alt.found and not alt.ambiguous:
                    validation = alt
                    break

        # Dedup: if another agent already resolved to same FID, merge scopes
        if validation.found and validation.fid > 0 and validation.fid in seen_fids:
            existing = seen_fids[validation.fid]
            # Merge scope info into existing agent's context
            if assignment.scope and assignment.scope not in (existing.assignment.scope or ""):
                existing.warnings.append(f"MERGED: {assignment.id} ({assignment.scope}) also targets this function")
            continue

        # Load source + flow + merged
        source = ""
        flow_text = ""
        merged_text = ""
        callers, callees = [], []

        if validation.found and validation.fid > 0:
            source = validator.get_source(validation.fid)
            flow_text = validator.get_flow_graph(validation.fid)
            callers, callees = validator.get_callers_callees(validation.fid)

            # Load merged flow
            mf = load_merged_flow(repo, validation.fid)
            if mf and mf.get("sequence"):
                merged_text = _render_merged_flow(mf["sequence"])

            if validation.ambiguous:
                warnings.append(f"AMBIGUOUS: '{validation.name}' matches {len(validation.candidates)} functions: {', '.join(validation.candidates[:3])}")
        else:
            warnings.append(f"NOT_IN_GRAPH: '{validation.name}' — no source available, likely library/framework code")

        # Scope cluster entries — find errors owned by this agent
        cluster_entries, unmapped, owned_error_count = _scope_cluster(assignment, path, validation)

        # Dispatch gate: no owned errors = don't run (unless absence mode)
        if owned_error_count == 0 and assignment.context_mode != "absence":
            log.debug("agent_dropped", agent=assignment.id, reason="no_owned_errors",
                      fid=validation.fid, strategy=validation.strategy)
            continue

        # Absence mode: provide expected flow as context instead of error cluster
        if assignment.context_mode == "absence" and not cluster_entries:
            if merged_text:
                warnings.append("ABSENCE: This function was expected but NOT seen in the log. Investigate why.")
                cluster_entries = [f"[EXPECTED] {merged_text}"]

        ctx_obj = AgentContext(
            assignment=assignment,
            validation=validation,
            source=source,
            flow_graph=flow_text,
            merged_flow=merged_text,
            callers=callers[:10],
            callees=callees[:15],
            cluster_entries=cluster_entries,
            unmapped_entries=unmapped,
            warnings=warnings,
        )
        contexts.append(ctx_obj)
        if validation.found and validation.fid > 0:
            seen_fids[validation.fid] = ctx_obj

    return contexts


def render_agent_context(ctx: AgentContext) -> str:
    """Render AgentContext into the text block passed to the trace agent prompt."""
    lines = []

    # Warnings first
    if ctx.warnings:
        lines.append("## ⚠️ Warnings")
        for w in ctx.warnings:
            lines.append(f"  {w}")
        lines.append("")

    # Source
    if ctx.source:
        lines.append(f"## Starting Function: {ctx.assignment.starting_node} (FID: {ctx.validation.fid})")
        lines.append("Source (pre-loaded — do NOT call read_function_source for this function):")
        lines.append(f"```\n{ctx.source}\n```")
        lines.append("")
    else:
        lines.append(f"## Starting Function: {ctx.assignment.starting_node}")
        lines.append("⚠️ Source NOT available — this function is not in the code graph.")
        lines.append("Focus on what called this function (from stack traces) or search for related app-level functions.")
        lines.append("")

    # Flow graph
    if ctx.flow_graph:
        lines.append("## Execution Flow Graph")
        lines.append(ctx.flow_graph)
        lines.append("")

    # Call context
    if ctx.callers or ctx.callees:
        lines.append("## Call Context")
        if ctx.callers:
            lines.append(f"  Callers: {', '.join(ctx.callers[:8])}")
        if ctx.callees:
            lines.append(f"  Callees: {', '.join(ctx.callees[:12])}")
        lines.append("")

    # Merged flow
    if ctx.merged_flow:
        lines.append("## Expected Log Sequence (from merged flow)")
        lines.append(ctx.merged_flow)
        lines.append("")

    # Log cluster
    if ctx.cluster_entries:
        lines.append("## Log Cluster (scoped to your investigation area)")
        for entry in ctx.cluster_entries:
            lines.append(f"  {entry}")
        lines.append("")

    # Unmapped
    if ctx.unmapped_entries:
        lines.append("## Unmapped Entries (could not resolve to code)")
        for entry in ctx.unmapped_entries[:10]:
            lines.append(f"  {entry}")
        lines.append("")

    return "\n".join(lines)


# --- Private helpers ---

def _extract_short_name(raw: str) -> str:
    """Extract method name from qualified name."""
    parts = re.split(r'[.$:]+', raw)
    return parts[-1] if parts else raw


def _extract_class_hint(raw: str) -> str | None:
    """Extract class name from qualified name."""
    # Handle inner class: com.pkg.Class$_closure.doCall → Class
    if "$" in raw:
        before_dollar = raw.split("$")[0]
        parts = before_dollar.split(".")
        return parts[-1] if parts else None
    parts = raw.split(".")
    if len(parts) >= 2:
        return parts[-2]
    return None


def _render_flow_graph(fg: FlowGraph) -> str:
    """Render a FlowGraph as concise text."""
    if not fg.nodes:
        return "(empty flow)"
    lines = []
    node_map = {n.id: n for n in fg.nodes}
    # Build adjacency
    children: dict[int, list[int]] = {}
    for e in fg.edges:
        children.setdefault(e.src, []).append(e.dst)

    visited = set()

    def _walk(nid: int, depth: int = 0):
        if nid in visited or depth > 15:
            return
        visited.add(nid)
        n = node_map.get(nid)
        if not n:
            return
        indent = "  " * depth
        if n.type == "log":
            lines.append(f"{indent}→ log({n.log_level}): {n.log_text[:60]}" if n.log_text else f"{indent}→ log({n.log_level})")
        elif n.type == "branch":
            lines.append(f"{indent}→ branch: {n.condition[:50]}" if n.condition else f"{indent}→ branch")
        elif n.type == "call":
            lines.append(f"{indent}→ call: {n.call_target}")
        elif n.type == "return":
            lines.append(f"{indent}→ return")
        else:
            lines.append(f"{indent}→ {n.type}")
        for child in children.get(nid, []):
            _walk(child, depth + 1 if n.type == "branch" else depth)

    _walk(fg.entry_node or (fg.nodes[0].id if fg.nodes else 0))
    return "\n".join(lines) if lines else "(no reachable nodes)"


def _render_merged_flow(sequence: list) -> str:
    """Render merged flow sequence as text."""
    lines = []
    for entry in sequence[:20]:
        if len(entry) >= 5:
            func, line, level, frags, text = entry[0], entry[1], entry[2], entry[3], entry[4]
            lines.append(f"  [{level or '?'}] {func}: {text}")
        elif len(entry) >= 3:
            lines.append(f"  {entry[0]}: {entry[2] if len(entry) > 2 else ''}")
    return "\n".join(lines) if lines else ""


def _scope_cluster(assignment: AgentAssignment, path: WalkablePath, validation: FunctionValidation) -> tuple[list[str], list[str], int]:
    """Scope log entries for this agent using resolved FID mapping.

    Returns (cluster_entries, unmapped_entries, owned_error_count).
    Error ownership is the dispatch signal — 0 errors = don't run.
    """
    error_set = set(path.error_points)
    repo_name = path.repo.split("/")[-1] if path.repo else ""

    # 1. Find all entry indices owned by this agent's resolved FID
    owned_indices: set[int] = set()
    if validation.found and validation.fid > 0:
        owned_indices = set(path.fid_to_entries.get(validation.fid, []))

        # Also match by originated_from name (for closures without FID)
        fm = load_func_map(repo_name)
        fm_entry = fm.get(str(validation.fid), {})
        resolved_name = fm_entry.get("name", "").lower()
        match_names = set()
        if resolved_name:
            match_names.add(resolved_name)
        match_names.add(assignment.starting_node.lower())

        for i, entry in enumerate(path.entries):
            if i in owned_indices:
                continue
            for fname in (entry.originated_from or []):
                fl = fname.lower()
                if fl in match_names or any(fl.endswith(f".{mn}") or fl == mn or mn == fl for mn in match_names):
                    owned_indices.add(i)
                    break

    # 2. Stack trace check (only for meaningful function names)
    if validation.found and validation.fid > 0:
        fm_entry = fm.get(str(validation.fid), {})
        func_name = fm_entry.get("name", "").lower() if fm_entry else ""
        if func_name and func_name not in ("docall", "call", "invoke", "run", "execute"):
            for idx in path.error_points:
                if idx in owned_indices:
                    continue
                entry = path.entries[idx]
                if entry.stack_trace and hasattr(entry.stack_trace, "frames"):
                    for fr in entry.stack_trace.frames[:8]:
                        if func_name in f"{fr.class_name}.{fr.method}".lower():
                            owned_indices.add(idx)
                            break

    # 3. Proximity-based error resolution: unresolved errors near owned entries
    #    If an error has no originated_from_ids but its neighbors (±3) belong to us, claim it
    if owned_indices:
        for idx in path.error_points:
            if idx in owned_indices:
                continue
            entry = path.entries[idx]
            if entry.originated_from_ids:
                continue  # already resolved to someone else
            # Check if neighbors resolve to our FID
            for offset in range(-3, 4):
                neighbor_idx = idx + offset
                if neighbor_idx == idx or neighbor_idx < 0 or neighbor_idx >= len(path.entries):
                    continue
                if neighbor_idx in owned_indices:
                    owned_indices.add(idx)
                    break

    # Count owned errors
    owned_errors = owned_indices & error_set
    owned_error_count = len(owned_errors)

    if not owned_errors:
        return [], [], 0

    # 4. Build cluster: window around each owned error
    cluster_entries = []
    unmapped = []
    seen = set()
    for idx in sorted(owned_errors):
        window_start = max(0, idx - 10)
        window_end = min(len(path.entries), idx + 6)
        for i in range(window_start, window_end):
            if i in seen:
                continue
            seen.add(i)
            e = path.entries[i]
            func = e.originated_from[0] if e.originated_from else "UNMAPPED"
            lvl = (e.level or "?")[0].upper()
            msg_text = e.static_text or e.raw_text or ""
            marker = " ← ERROR" if i in error_set else ""
            line = f"[{lvl}] {func}: {msg_text}{marker}"
            cluster_entries.append(line)
            if func == "UNMAPPED":
                unmapped.append(line)

    return cluster_entries, unmapped, owned_error_count
