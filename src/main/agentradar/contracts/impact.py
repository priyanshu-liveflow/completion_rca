"""Contact points, blast radius, and per-site impact verdicts."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class ContactPoint(BaseModel):
    """A call site in the indexed repo that references a dependency symbol."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    function_name: str
    fid: int
    file_path: str
    line: int | None


class BlastRadius(BaseModel):
    """Callers walked from a contact point, in BFS order."""

    model_config = ConfigDict(frozen=True)

    contact_point: ContactPoint
    callers: list[str]
    depth_reached: int


class Verdict(StrEnum):
    """Empirical status of a contact point under the new dependency version."""

    UNKNOWN = "unknown"
    BROKEN = "broken"
    SAFE = "safe"
    UNCOVERED = "uncovered"


class ImpactRow(BaseModel):
    """One row of the impact table: a site, a verdict, and why."""

    model_config = ConfigDict(frozen=True)

    contact_point: ContactPoint
    verdict: Verdict
    why: str
    evidence_ref: str | None
