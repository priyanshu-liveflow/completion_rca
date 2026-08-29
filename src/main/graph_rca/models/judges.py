"""Judge verdict models — single source of truth."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class LensVerdict:
    lens: str
    verdict: str
    root_cause: str
    confidence: float
    supporting_evidence: list[str] = field(default_factory=list)
    contradicting_evidence: list[str] = field(default_factory=list)
    reasoning: str = ""


@dataclass
class FinalVerdict:
    root_cause: str
    root_cause_node: str | None
    category: str
    confidence: float
    evidence_chain: list[str]
    winning_lens: str
    explanation: str
    suggested_fix: str | None = None
