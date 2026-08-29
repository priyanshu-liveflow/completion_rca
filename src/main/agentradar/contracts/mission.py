"""A mission is one release event walked through locate → prove → act."""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .dependency import ReleaseEvent
from .evidence import TestReport, TestSelection
from .impact import ImpactRow
from .patch import VerifyResult


class MissionState(StrEnum):
    """Lifecycle of a mission as the conductor walks the pipeline."""

    WATCHING = "watching"
    LOCATING = "locating"
    REPRODUCING = "reproducing"
    PATCHING = "patching"
    AWAITING_APPROVAL = "awaiting_approval"
    DONE = "done"
    FAILED = "failed"


class Mission(BaseModel):
    """Mutable mission record. The store persists this; the dashboard renders it."""

    model_config = ConfigDict(frozen=False)

    id: str
    release: ReleaseEvent
    state: MissionState
    impact_rows: list[ImpactRow] = []
    selection: TestSelection | None = None
    reports: list[TestReport] = []
    verify: VerifyResult | None = None


class ActionPlan(BaseModel):
    """An approval-gated write the conductor wants to perform."""

    model_config = ConfigDict(frozen=True)

    target: Literal["github_pr", "github_issue", "slack", "export"]
    summary: str
    payload: dict[str, Any]
    requires_approval: bool
