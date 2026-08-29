"""Pydantic v2 models shared across core, adapters, MCP, and the dashboard."""

from .collector import CollectorRun, CollectorSpec, HealthVerdict
from .dependency import Dependency, ReleaseEvent, Watchlist
from .evidence import TestCase, TestReport, TestSelection
from .impact import BlastRadius, ContactPoint, ImpactRow, Verdict
from .mission import ActionPlan, Mission, MissionState
from .patch import Patch, VerifyResult
from .web import PageContent, SearchHit, SearchResults

__all__ = [
    "ActionPlan",
    "BlastRadius",
    "CollectorRun",
    "CollectorSpec",
    "ContactPoint",
    "Dependency",
    "HealthVerdict",
    "ImpactRow",
    "Mission",
    "MissionState",
    "PageContent",
    "Patch",
    "ReleaseEvent",
    "SearchHit",
    "SearchResults",
    "TestCase",
    "TestReport",
    "TestSelection",
    "Verdict",
    "VerifyResult",
    "Watchlist",
]
