"""Context and router models — single source of truth."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class PreparedContext:
    """Output of Phase 1 — everything needed before investigation."""
    path: object | None = None  # WalkablePath (avoid circular import)
    tiered: object | None = None  # TieredContext
    choices: dict | None = None
    flow_context: str = ""
    repo: str = ""
    prompt: str = ""


@dataclass
class InvestigationResult:
    """Output of Phase 2."""
    mode: str = "rca"  # "explain" | "rca"
    explanation: str = ""
    trace_reports: list = field(default_factory=list)
    assignments: list = field(default_factory=list)


@dataclass
class Verdict:
    """Output of Phase 3."""
    root_cause: str = ""
    root_cause_node: str | None = None
    category: str = ""
    confidence: float = 0.0
    explanation: str = ""
    evidence_chain: list[str] = field(default_factory=list)
    suggested_fix: str | None = None
    lenses: list[str] = field(default_factory=list)
    lens_verdicts: list = field(default_factory=list)


@dataclass
class ClusterSummary:
    cluster_id: str = ""
    anchor_function: str = ""
    fid: int = -1
    error_count: int = 0
    sample_messages: list[str] = field(default_factory=list)
    related_functions: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class RouterResult:
    relevant: list = field(default_factory=list)
    irrelevant: list = field(default_factory=list)
    mode: str = "autonomous"
