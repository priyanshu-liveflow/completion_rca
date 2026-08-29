"""Pydantic v2 models shared across core, adapters, MCP, and the dashboard."""

from .collector import CollectorRun, CollectorSpec, HealthVerdict
from .dependency import Dependency, ReleaseEvent, Watchlist
from .evidence import TestCase, TestReport, TestSelection
from .impact import (
    BlastRadius,
    ContactPoint,
    ContactPointList,
    FunctionSource,
    GraphNode,
    GraphNodeList,
    ImpactRow,
    Verdict,
)
from .mission import ActionPlan, Mission, MissionState
from .patch import Patch, VerifyResult

__all__ = [
    "ActionPlan",
    "BlastRadius",
    "CollectorRun",
    "CollectorSpec",
    "ContactPoint",
    "ContactPointList",
    "Dependency",
    "FunctionSource",
    "GraphNode",
    "GraphNodeList",
    "HealthVerdict",
    "ImpactRow",
    "Mission",
    "MissionState",
    "Patch",
    "ReleaseEvent",
    "TestCase",
    "TestReport",
    "TestSelection",
    "Verdict",
    "VerifyResult",
    "Watchlist",
]
