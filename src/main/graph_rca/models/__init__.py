"""All data models for the flow graph system."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# --- Utilities ---

_METHOD_SEP = re.compile(r'[.:/]')  # Java: . | Rust/C++: :: | Go: / | mixed


def extract_method_name(qualified: str) -> str:
    """Extract bare method/function name from any qualified path.
    
    Handles: Java (pkg.Class.method), Rust (crate::mod::func),
    C++ (ns::Class::method), Go (pkg/func), Python (module.func).
    """
    if '::' in qualified:
        return qualified.rsplit('::', 1)[-1]
    if '.' in qualified:
        return qualified.rsplit('.', 1)[-1]
    if '/' in qualified:
        return qualified.rsplit('/', 1)[-1]
    return qualified


# --- Flow Graph Models ---

@dataclass
class FlowNode:
    id: int
    type: str  # "log" | "call" | "branch" | "branch_end" | "return" | "throw"
    line: int
    log_level: str = ""
    log_text: str = ""
    call_target: str = ""
    call_target_id: int = -1
    branch_type: str = ""  # "if" | "else" | "try" | "catch" | "switch" | "case"
    condition: str = ""
    branch_depth: int = 0
    branch_path: str = ""


@dataclass
class FlowEdge:
    src: int
    dst: int
    edge_type: str = "next"  # "next" | "branch_true" | "branch_false" | "exception" | "fallthrough"


@dataclass
class FlowGraph:
    function_name: str
    nodes: list[FlowNode] = field(default_factory=list)
    edges: list[FlowEdge] = field(default_factory=list)
    entry_node: int = 0
    exit_nodes: list[int] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps({
            "function": self.function_name,
            "nodes": [{"id": n.id, "type": n.type, "line": n.line, "log_level": n.log_level,
                       "log_text": n.log_text, "call_target": n.call_target,
                       "call_target_id": n.call_target_id, "branch_type": n.branch_type,
                       "condition": n.condition, "branch_depth": n.branch_depth,
                       "branch_path": n.branch_path} for n in self.nodes],
            "edges": [{"src": e.src, "dst": e.dst, "edge_type": e.edge_type} for e in self.edges],
            "entry": self.entry_node,
            "exits": self.exit_nodes,
        })

    @classmethod
    def from_json(cls, data: str) -> "FlowGraph":
        d = json.loads(data)
        fg = cls(function_name=d["function"])
        fg.nodes = [FlowNode(**n) for n in d["nodes"]]
        fg.edges = [FlowEdge(**e) for e in d["edges"]]
        fg.entry_node = d["entry"]
        fg.exit_nodes = d["exits"]
        return fg


# --- Merged Flow ---

@dataclass
class MergedFlow:
    entry_function: str
    nodes: list[FlowNode] = field(default_factory=list)
    edges: list[FlowEdge] = field(default_factory=list)
    log_sequence: list[tuple[str, int, str, str]] = field(default_factory=list)  # flat fallback
    log_tree: list = field(default_factory=list)       # branch-aware: list[LogStep]
    anchor_index: dict[int, int] = field(default_factory=dict)  # fid → node position in merged

    def expected_logs(self) -> list[tuple[str, int, str, str]]:
        """Flat fallback for backward compat."""
        return self.log_sequence


@dataclass
class LogStep:
    """A node in the expected execution tree."""
    type: str  # "log" | "branch" | "loop" | "exit"
    # type="log":
    func: str = ""
    fid: int = -1
    line: int = 0
    level: str = ""
    text: str = ""
    # type="branch": N paths, any ONE should match
    paths: list = field(default_factory=list)  # list[list[LogStep]]
    # type="loop": body may match 0+ times
    body: list = field(default_factory=list)   # list[LogStep]


# --- Alignment ---

@dataclass
class AlignmentResult:
    thread_id: str
    matched_flow: str | None = None
    aligned: list[tuple[int, str, str]] = field(default_factory=list)
    divergences: list[dict] = field(default_factory=list)
    coverage: float = 0.0


@dataclass
class Cluster:
    anchor_func: str
    anchor_idx: int
    entries: list[dict] = field(default_factory=list)


# --- Log Template ---

@dataclass
class DynamicPart:
    variable: str
    type: str | None = None
    position: int = 0


@dataclass
class LogTemplate:
    static_text: str
    static_fragments: list[str]
    log_level: str
    line_in_function: int
    dynamic_parts: list[DynamicPart] = field(default_factory=list)
    regex_pattern: str = ""


# --- Preprocessor ---

@dataclass
class StackFrame:
    class_name: str
    method: str
    file: str
    line: int


@dataclass
class StackTrace:
    exception: str
    message: str
    frames: list[StackFrame] = field(default_factory=list)
    caused_by: list["StackTrace"] = field(default_factory=list)


@dataclass
class LogEntry:
    line_number: int
    line_end: int
    raw_text: str
    level: str
    timestamp: str | None
    static_text: str
    dynamic_values: list[str]
    service: str | None
    thread_id: str | None
    stack_trace: StackTrace | None
    originated_from: list[str] = field(default_factory=list)
    originated_from_ids: list[int] = field(default_factory=list)
    originated_class: str | None = None  # Class the function belongs to
    originated_line: int | None = None   # Line within function where the log call is
    resolution_confidence: float = 0.0
    resolution_tier: int = 4
    is_error: bool = False
    is_framework: bool = False
    is_inferred: bool = False
    repeat_count: int = 1  # How many times this exact entry appeared (after dedup)
    # Stack trace path: [crash_point, caller, ..., entry_point] — app frames only
    trace_path: list[str] = field(default_factory=list)


@dataclass
class BranchPoint:
    entry_index: int
    candidates: list[str] = field(default_factory=list)
    scores: list[float] = field(default_factory=list)


@dataclass
class WalkablePath:
    entries: list[LogEntry]
    branches: list[BranchPoint] = field(default_factory=list)
    error_points: list[int] = field(default_factory=list)
    coverage_pct: float = 0.0
    service: str | None = None
    repo: str | None = None
    fid_to_entries: dict[int, list[int]] = field(default_factory=dict)  # fid → [entry indices]

    def build_fid_index(self):
        """Build fid_to_entries mapping from resolved entries."""
        self.fid_to_entries = {}
        for idx, entry in enumerate(self.entries):
            for fid in entry.originated_from_ids:
                if fid not in self.fid_to_entries:
                    self.fid_to_entries[fid] = []
                self.fid_to_entries[fid].append(idx)


# --- Index Cache Bundle ---

@dataclass
class IndexBundle:
    """Everything needed at analysis time, loaded from cache or built fresh."""
    commit_hash: str
    repo: str
    trie_data: list[tuple[list[str], str, int]] | None = None  # raw template data for trie build
    flow_graphs_count: int = 0
    classification: dict[str, int] = field(default_factory=dict)


# Re-export from submodules for convenience
from .agents import AgentAssignment, Evidence, TraceReport
from .judges import LensVerdict, FinalVerdict
from .pipeline import PipelineResult
from .context import PreparedContext, InvestigationResult, Verdict, ClusterSummary, RouterResult
