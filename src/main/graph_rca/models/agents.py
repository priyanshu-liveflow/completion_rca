"""Agent-related models."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class AgentAssignment:
    id: str
    starting_node: str
    scope: str
    direction: str  # "backward" | "forward" | "both"
    model: str  # "light" | "default" | "heavy"
    tools: str  # "graph_only" | "graph_plus_codebase"
    parent_agent: str | None = None
    context_from_parent: str | None = None
    path_slice: list[str] | None = None
    context_mode: str = "error"  # "error" | "absence"


@dataclass
class Evidence:
    type: str  # "log_line" | "source_code" | "graph_edge" | "inference"
    content: str
    location: str


@dataclass
class TraceReport:
    agent_id: str
    path_walked: list[str]
    evidence: list[Evidence]
    assessment: str
    root_cause_node: str | None
    is_input_issue: bool
    confidence: float
    dead_ends: list[str] = field(default_factory=list)
    model: str = ""
    token_usage: dict = field(default_factory=dict)
