"""Pipeline result model."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class PipelineResult:
    walkable_path: object  # WalkablePath
    assignments: list = field(default_factory=list)
    trace_reports: list = field(default_factory=list)
    lenses: list = field(default_factory=list)
    lens_verdicts: list = field(default_factory=list)
    final_verdict: object | None = None  # FinalVerdict
    short_circuited: bool = False
